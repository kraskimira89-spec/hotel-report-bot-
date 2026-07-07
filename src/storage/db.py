"""Инициализация SQLite, миграции, запись и чтение истории."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Generator, Iterable

from src.config import get_config, get_db_path
from src.storage.models import (
    INDEXES,
    MIGRATIONS_V2,
    SCHEMA_VERSION,
    TABLES,
    BookingDailyRecord,
    ErrorLogRecord,
    GuestRecord,
    MetricsDailyRecord,
    PeriodComparison,
    PricePeriodComparison,
    PriceSnapshotRecord,
    ReportLogRecord,
)

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Получить подключение к SQLite с row_factory."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session() -> Generator[sqlite3.Connection, None, None]:
    """Контекстный менеджер с автокоммитом."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _date_str(value: date) -> str:
    return value.isoformat()


def _dt_str(value: datetime) -> str:
    return value.isoformat()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row_to_price_snapshot(row: sqlite3.Row) -> PriceSnapshotRecord:
    snapshot_at = row["snapshot_at"] or row["created_at"]
    return PriceSnapshotRecord(
        id=row["id"],
        snapshot_at=_parse_dt(snapshot_at),
        category=row["category"],
        price=row["price"],
        source=row["source"],
        is_estimated=bool(row["is_estimated"]),
        is_fallback=bool(row["is_fallback"]),
        url=row["url"],
    )


def _row_to_metrics(row: sqlite3.Row) -> MetricsDailyRecord:
    return MetricsDailyRecord(
        id=row["id"],
        report_date=_parse_date(row["report_date"]),
        metric_type=row["metric_type"] or "daily",
        occupancy_pct=row["occupancy_pct"],
        adr=row["adr"],
        revpar=row["revpar"],
        als=row["als"],
        revenue=row["revenue"],
        bookings_count=row["bookings_count"],
        is_estimated=bool(row["is_estimated"]),
    )


def _apply_migrations(conn: sqlite3.Connection, current: int) -> None:
    if current >= SCHEMA_VERSION:
        return
    if current < 2:
        for ddl in MIGRATIONS_V2:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def init_db() -> None:
    """Создать таблицы при старте, если их нет."""
    with db_session() as conn:
        for ddl in TABLES:
            conn.execute(ddl)
        for idx in INDEXES:
            conn.execute(idx)
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
        else:
            _apply_migrations(conn, row["version"])
    logger.info("БД инициализирована: %s", get_db_path())


def migrate() -> None:
    """Применить миграции схемы."""
    init_db()


def save_price_snapshots(
    snapshots: Iterable[PriceSnapshotRecord],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Сохранить snapshot цен (upsert по дате+категории+источнику)."""
    items = list(snapshots)
    if not items:
        return 0

    sql = """
        INSERT INTO price_snapshots (
            snapshot_at, snapshot_date, category, price, source,
            is_estimated, is_fallback, url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_date, category, source) DO UPDATE SET
            snapshot_at = excluded.snapshot_at,
            price = excluded.price,
            is_estimated = excluded.is_estimated,
            is_fallback = excluded.is_fallback,
            url = excluded.url
    """

    def _save(connection: sqlite3.Connection) -> int:
        count = 0
        for item in items:
            snapshot_date = item.snapshot_at.date().isoformat()
            connection.execute(
                sql,
                (
                    _dt_str(item.snapshot_at),
                    snapshot_date,
                    item.category,
                    item.price,
                    item.source,
                    int(item.is_estimated),
                    int(item.is_fallback),
                    item.url,
                ),
            )
            count += 1
        return count

    if conn is not None:
        return _save(conn)

    with db_session() as connection:
        return _save(connection)


def get_price_snapshots(
    start_date: date,
    end_date: date,
    category: str | None = None,
) -> list[PriceSnapshotRecord]:
    """Прочитать snapshot цен за период."""
    sql = """
        SELECT * FROM price_snapshots
        WHERE snapshot_date >= ? AND snapshot_date <= ?
    """
    params: list[object] = [_date_str(start_date), _date_str(end_date)]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY snapshot_date DESC, category"

    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_price_snapshot(row) for row in rows]


def get_price_snapshots_by_date(
    snapshot_date: date,
) -> list[PriceSnapshotRecord]:
    """Snapshot цен за конкретную дату."""
    return get_price_snapshots(snapshot_date, snapshot_date)


def compare_prices_to_date(
    reference_date: date,
    compare_date: date,
) -> list[PricePeriodComparison]:
    """Сравнить цены категорий: reference_date vs compare_date."""
    ref_map = {s.category: s.price for s in get_price_snapshots_by_date(reference_date)}
    cmp_map = {s.category: s.price for s in get_price_snapshots_by_date(compare_date)}
    categories = sorted(set(ref_map) | set(cmp_map))
    return [
        PricePeriodComparison(
            category=cat,
            reference_date=reference_date,
            compare_date=compare_date,
            reference_price=ref_map.get(cat),
            compare_price=cmp_map.get(cat),
        )
        for cat in categories
    ]


def compare_prices_yesterday(
    reference_date: date,
) -> list[PricePeriodComparison]:
    """Сравнение цен «к вчера»."""
    return compare_prices_to_date(reference_date, reference_date - timedelta(days=1))


def compare_prices_last_week(
    reference_date: date,
) -> list[PricePeriodComparison]:
    """Сравнение цен «к прошлой неделе» (7 дней назад)."""
    return compare_prices_to_date(reference_date, reference_date - timedelta(days=7))


def save_metrics_daily(
    record: MetricsDailyRecord,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Сохранить ежедневные метрики."""
    sql = """
        INSERT INTO metrics_daily (
            report_date, metric_type, occupancy_pct, adr, revpar, als,
            revenue, bookings_count, is_estimated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(report_date, metric_type) DO UPDATE SET
            occupancy_pct = excluded.occupancy_pct,
            adr = excluded.adr,
            revpar = excluded.revpar,
            als = excluded.als,
            revenue = excluded.revenue,
            bookings_count = excluded.bookings_count,
            is_estimated = excluded.is_estimated
    """
    params = (
        _date_str(record.report_date),
        record.metric_type,
        record.occupancy_pct,
        record.adr,
        record.revpar,
        record.als,
        record.revenue,
        record.bookings_count,
        int(record.is_estimated),
    )

    if conn is not None:
        conn.execute(sql, params)
        return

    with db_session() as connection:
        connection.execute(sql, params)


def get_metrics_daily(
    start_date: date,
    end_date: date,
    metric_type: str = "daily",
) -> list[MetricsDailyRecord]:
    """Прочитать метрики за период."""
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metrics_daily
            WHERE report_date >= ? AND report_date <= ? AND metric_type = ?
            ORDER BY report_date DESC
            """,
            (_date_str(start_date), _date_str(end_date), metric_type),
        ).fetchall()
    return [_row_to_metrics(row) for row in rows]


def get_metrics_for_date(
    report_date: date,
    metric_type: str = "daily",
) -> MetricsDailyRecord | None:
    """Метрики за одну дату."""
    rows = get_metrics_daily(report_date, report_date, metric_type)
    return rows[0] if rows else None


def compare_metrics_to_date(
    reference_date: date,
    compare_date: date,
    metric_type: str = "daily",
) -> PeriodComparison:
    """Сравнить метрики reference_date vs compare_date."""
    return PeriodComparison(
        reference_date=reference_date,
        compare_date=compare_date,
        reference_metrics=get_metrics_for_date(reference_date, metric_type),
        metrics=get_metrics_for_date(compare_date, metric_type),
    )


def compare_metrics_yesterday(
    reference_date: date,
    metric_type: str = "daily",
) -> PeriodComparison:
    """Сравнение метрик «к вчера»."""
    return compare_metrics_to_date(
        reference_date,
        reference_date - timedelta(days=1),
        metric_type,
    )


def compare_metrics_last_week(
    reference_date: date,
    metric_type: str = "daily",
) -> PeriodComparison:
    """Сравнение метрик «к прошлой неделе»."""
    return compare_metrics_to_date(
        reference_date,
        reference_date - timedelta(days=7),
        metric_type,
    )


def save_booking_daily(
    record: BookingDailyRecord,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Записать бронирование."""
    sql = """
        INSERT INTO bookings_daily (
            created_date, source, channel, amount, guest_id
        ) VALUES (?, ?, ?, ?, ?)
    """
    params = (
        _date_str(record.created_date),
        record.source,
        record.channel,
        record.amount,
        record.guest_id,
    )

    if conn is not None:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid)

    with db_session() as connection:
        cur = connection.execute(sql, params)
        return int(cur.lastrowid)


def get_bookings_daily(
    start_date: date,
    end_date: date,
) -> list[BookingDailyRecord]:
    """Бронирования за период."""
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bookings_daily
            WHERE created_date >= ? AND created_date <= ?
            ORDER BY created_date DESC, id DESC
            """,
            (_date_str(start_date), _date_str(end_date)),
        ).fetchall()
    return [
        BookingDailyRecord(
            id=row["id"],
            created_date=_parse_date(row["created_date"]),
            source=row["source"],
            channel=row["channel"],
            amount=row["amount"],
            guest_id=row["guest_id"],
        )
        for row in rows
    ]


def upsert_guest(record: GuestRecord, conn: sqlite3.Connection | None = None) -> None:
    """Создать или обновить гостя (только хеши)."""
    sql = """
        INSERT INTO guests (
            guest_id, phone_hash, email_hash, fio_hash,
            first_seen, last_seen, visits_count, is_returning
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guest_id) DO UPDATE SET
            phone_hash = COALESCE(excluded.phone_hash, guests.phone_hash),
            email_hash = COALESCE(excluded.email_hash, guests.email_hash),
            fio_hash = COALESCE(excluded.fio_hash, guests.fio_hash),
            last_seen = excluded.last_seen,
            visits_count = guests.visits_count + 1,
            is_returning = excluded.is_returning
    """
    params = (
        record.guest_id,
        record.phone_hash,
        record.email_hash,
        record.fio_hash,
        _date_str(record.first_seen),
        _date_str(record.last_seen),
        record.visits_count,
        int(record.is_returning),
    )

    if conn is not None:
        conn.execute(sql, params)
        return

    with db_session() as connection:
        connection.execute(sql, params)


def get_guest(guest_id: str) -> GuestRecord | None:
    """Получить гостя по guest_id."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM guests WHERE guest_id = ?",
            (guest_id,),
        ).fetchone()
    if row is None:
        return None
    return GuestRecord(
        guest_id=row["guest_id"],
        phone_hash=row["phone_hash"],
        email_hash=row["email_hash"],
        fio_hash=row["fio_hash"],
        first_seen=_parse_date(row["first_seen"]),
        last_seen=_parse_date(row["last_seen"]),
        visits_count=row["visits_count"],
        is_returning=bool(row["is_returning"]),
    )


def save_report_log(
    record: ReportLogRecord,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Записать журнал отчёта."""
    sql = """
        INSERT INTO reports_log (
            report_type, report_date, run_date, period_start, period_end,
            status, dry_run, preview, message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        record.report_type,
        _date_str(record.report_date),
        _date_str(record.run_date),
        _date_str(record.period_start) if record.period_start else None,
        _date_str(record.period_end) if record.period_end else None,
        record.status,
        int(record.dry_run),
        record.preview,
        record.message,
    )

    if conn is not None:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid)

    with db_session() as connection:
        cur = connection.execute(sql, params)
        return int(cur.lastrowid)


def save_error_log(
    record: ErrorLogRecord,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Записать ошибку."""
    sql = """
        INSERT INTO errors_log (
            error_date, source, error_type, message, details, resolved
        ) VALUES (?, ?, ?, ?, ?, ?)
    """
    params = (
        _date_str(record.error_date),
        record.source,
        record.error_type,
        record.message,
        record.details,
        int(record.resolved),
    )

    if conn is not None:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid)

    with db_session() as connection:
        cur = connection.execute(sql, params)
        return int(cur.lastrowid)


def get_errors_log(
    start_date: date | None = None,
    end_date: date | None = None,
    resolved: bool | None = None,
    limit: int = 100,
) -> list[ErrorLogRecord]:
    """Прочитать ошибки за период."""
    sql = "SELECT * FROM errors_log WHERE 1=1"
    params: list[object] = []

    if start_date:
        sql += " AND error_date >= ?"
        params.append(_date_str(start_date))
    if end_date:
        sql += " AND error_date <= ?"
        params.append(_date_str(end_date))
    if resolved is not None:
        sql += " AND resolved = ?"
        params.append(int(resolved))

    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        ErrorLogRecord(
            id=row["id"],
            error_date=_parse_date(row["error_date"] or row["created_at"][:10]),
            source=row["source"],
            error_type=row["error_type"],
            message=row["message"],
            details=row["details"],
            resolved=bool(row["resolved"]),
        )
        for row in rows
    ]


def cleanup_old_records() -> int:
    """Удалить записи старше retention_days из config."""
    cfg = get_config()
    cutoff = (datetime.now() - timedelta(days=cfg.storage.retention_days)).strftime(
        "%Y-%m-%d"
    )
    deleted = 0
    retention_tables = (
        ("price_snapshots", "snapshot_date"),
        ("metrics_daily", "report_date"),
        ("bookings_daily", "created_date"),
        ("reports_log", "report_date"),
        ("errors_log", "error_date"),
    )
    with db_session() as conn:
        for table, date_col in retention_tables:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE {date_col} < ?",
                (cutoff,),
            )
            deleted += cur.rowcount
    logger.info("Удалено %s записей старше %s", deleted, cutoff)
    return deleted
