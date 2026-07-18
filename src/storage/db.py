"""Инициализация SQLite, миграции, запись и чтение истории."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Generator, Iterable

from src.config import get_config, get_db_path
from src.storage.models import (
    FORECAST_RETENTION_DAYS,
    INDEXES,
    MIGRATIONS_V2,
    MIGRATIONS_V3,
    MIGRATIONS_V4,
    MIGRATIONS_V5,
    MIGRATIONS_V6,
    MIGRATIONS_V7,
    MIGRATIONS_V8,
    MIGRATIONS_V9,
    MIGRATIONS_V10,
    MIGRATIONS_V11,
    MIGRATIONS_V12,
    MIGRATIONS_V13,
    MIGRATIONS_V14,
    MIGRATIONS_V15,
    MIGRATIONS_V16,
    SCHEMA_VERSION,
    TABLES,
    TRENDS_RETENTION_DAYS,
    BookingDailyRecord,
    CityEventRecord,
    CompetitorPriceRecord,
    ErrorLogRecord,
    EventReviewLogRecord,
    EventSourceRecord,
    ForecastDailyRecord,
    ForecastRunRecord,
    GuestRecord,
    InsightRecord,
    MailMessageRecord,
    MetricsDailyRecord,
    PeriodComparison,
    PricePeriodComparison,
    PriceRecommendationRecord,
    RecommendationRecord,
    PriceSnapshotRecord,
    ReportLogRecord,
    TrendRecord,
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
    if current < 3:
        for ddl in MIGRATIONS_V3:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 4:
        for ddl in MIGRATIONS_V4:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 5:
        for ddl in MIGRATIONS_V5:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 6:
        for ddl in MIGRATIONS_V6:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 7:
        for ddl in MIGRATIONS_V7:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 8:
        for ddl in MIGRATIONS_V8:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 9:
        for ddl in MIGRATIONS_V9:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 10:
        for ddl in MIGRATIONS_V10:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 11:
        for ddl in MIGRATIONS_V11:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 12:
        for ddl in MIGRATIONS_V12:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 13:
        for ddl in MIGRATIONS_V13:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 14:
        for ddl in MIGRATIONS_V14:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 15:
        for ddl in MIGRATIONS_V15:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower() and "already exists" not in str(exc).lower():
                    logger.debug("Миграция пропущена: %s (%s)", ddl, exc)
    if current < 16:
        for ddl in MIGRATIONS_V16:
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
                (0,),
            )
            _apply_migrations(conn, 0)
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
        return int(cur.lastrowid or 0)

    with db_session() as connection:
        cur = connection.execute(sql, params)
        return int(cur.lastrowid or 0)


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


def get_guests_in_period(
    start_date: date,
    end_date: date,
) -> list[GuestRecord]:
    """Гости с last_seen в указанном периоде."""
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM guests
            WHERE last_seen >= ? AND last_seen <= ?
            ORDER BY last_seen DESC
            """,
            (_date_str(start_date), _date_str(end_date)),
        ).fetchall()
    return [
        GuestRecord(
            guest_id=row["guest_id"],
            phone_hash=row["phone_hash"],
            email_hash=row["email_hash"],
            fio_hash=row["fio_hash"],
            first_seen=_parse_date(row["first_seen"]),
            last_seen=_parse_date(row["last_seen"]),
            visits_count=row["visits_count"],
            is_returning=bool(row["is_returning"]),
        )
        for row in rows
    ]


def get_guest_stats() -> dict[str, int]:
    """Агрегаты по гостям (без PII)."""
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_returning = 1 THEN 1 ELSE 0 END) AS returning_count
            FROM guests
            """
        ).fetchone()
    total = int(row["total"] or 0) if row else 0
    returning = int(row["returning_count"] or 0) if row else 0
    return {"total": total, "returning": returning}


def get_runtime_setting(key: str) -> str | None:
    """Прочитать runtime-настройку."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT value FROM runtime_settings WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else None


def set_runtime_setting(key: str, value: str) -> None:
    """Сохранить runtime-настройку."""
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO runtime_settings (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = datetime('now')
            """,
            (key, value),
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
        return int(cur.lastrowid or 0)

    with db_session() as connection:
        cur = connection.execute(sql, params)
        return int(cur.lastrowid or 0)


def get_report_log(report_id: int) -> ReportLogRecord | None:
    """Получить запись журнала отчётов по id."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM reports_log WHERE id = ?",
            (report_id,),
        ).fetchone()
    if row is None:
        return None
    return ReportLogRecord(
        id=row["id"],
        report_type=row["report_type"],
        report_date=_parse_date(row["report_date"]),
        run_date=_parse_date(row["run_date"]),
        period_start=_parse_date(row["period_start"]) if row["period_start"] else None,
        period_end=_parse_date(row["period_end"]) if row["period_end"] else None,
        status=row["status"],
        dry_run=bool(row["dry_run"]),
        preview=row["preview"],
        message=row["message"],
    )


def get_reports_log(limit: int = 50) -> list[ReportLogRecord]:
    """Список отправленных отчётов."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM reports_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        ReportLogRecord(
            id=row["id"],
            report_type=row["report_type"],
            report_date=_parse_date(row["report_date"]),
            run_date=_parse_date(row["run_date"]),
            period_start=_parse_date(row["period_start"]) if row["period_start"] else None,
            period_end=_parse_date(row["period_end"]) if row["period_end"] else None,
            status=row["status"],
            dry_run=bool(row["dry_run"]),
            preview=row["preview"],
            message=row["message"],
        )
        for row in rows
    ]


def report_log_exists(
    report_type: str,
    report_date: date,
    period_start: date | None = None,
    period_end: date | None = None,
) -> bool:
    """Проверить, есть ли отчёт за дату/период."""
    sql = """
        SELECT 1 FROM reports_log
        WHERE report_type = ? AND report_date = ?
    """
    params: list[object] = [report_type, _date_str(report_date)]
    if period_start is not None:
        sql += " AND period_start = ?"
        params.append(_date_str(period_start))
    if period_end is not None:
        sql += " AND period_end = ?"
        params.append(_date_str(period_end))
    sql += " LIMIT 1"
    with db_session() as conn:
        row = conn.execute(sql, params).fetchone()
    return row is not None


def price_snapshot_exists(snapshot_date: date) -> bool:
    """Есть ли snapshot цен за дату."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT 1 FROM price_snapshots WHERE snapshot_date = ? LIMIT 1",
            (_date_str(snapshot_date),),
        ).fetchone()
    return row is not None


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

    try:
        if conn is not None:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or 0)

        with db_session() as connection:
            cur = connection.execute(sql, params)
            return int(cur.lastrowid or 0)
    except sqlite3.OperationalError as exc:
        logger.debug("errors_log недоступен: %s", exc)
        return 0


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
    retention = cfg.storage.retention_days
    cutoff = (datetime.now() - timedelta(days=retention)).strftime("%Y-%m-%d")
    forecast_cutoff = (datetime.now() - timedelta(days=FORECAST_RETENTION_DAYS)).strftime(
        "%Y-%m-%d"
    )
    deleted = 0
    retention_tables = (
        ("price_snapshots", "snapshot_date"),
        ("metrics_daily", "report_date"),
        ("bookings_daily", "created_date"),
        ("reports_log", "report_date"),
        ("errors_log", "error_date"),
        ("competitor_prices", "date"),
    )
    with db_session() as conn:
        for table, date_col in retention_tables:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE {date_col} < ?",
                (cutoff,),
            )
            deleted += cur.rowcount
        cur = conn.execute(
            "DELETE FROM forecast_daily WHERE forecast_date < ?",
            (forecast_cutoff,),
        )
        deleted += cur.rowcount
        cur = conn.execute(
            "DELETE FROM forecast_runs WHERE run_date < ?",
            (forecast_cutoff,),
        )
        deleted += cur.rowcount
        deleted += prune_old_trends(conn=conn)
    logger.info("Удалено %s записей старше %s", deleted, cutoff)
    return deleted


def save_competitor_prices(
    records: Iterable[CompetitorPriceRecord],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Сохранить снимки цен конкурентов (агрегат + опционально категории)."""
    items = list(records)
    if not items:
        return 0

    sql = """
        INSERT INTO competitor_prices (
            competitor_name, date, price_from, currency, source,
            screenshot_path, available, category,
            check_in, check_out, price_kind, booking_engine,
            is_breakfast_included, cancellation_policy, captured_at,
            raw_url, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    def _save(connection: sqlite3.Connection) -> int:
        count = 0
        for item in items:
            breakfast: int | None = None
            if item.is_breakfast_included is not None:
                breakfast = int(item.is_breakfast_included)
            captured = (
                item.captured_at.isoformat(timespec="seconds")
                if item.captured_at is not None
                else None
            )
            connection.execute(
                sql,
                (
                    item.competitor_name,
                    _date_str(item.date),
                    item.price_from,
                    item.currency,
                    item.source,
                    item.screenshot_path,
                    int(item.available),
                    item.category or "",
                    _date_str(item.check_in) if item.check_in else None,
                    _date_str(item.check_out) if item.check_out else None,
                    item.price_kind or "dynamic",
                    item.booking_engine,
                    breakfast,
                    item.cancellation_policy,
                    captured,
                    item.raw_url,
                    item.error_message,
                ),
            )
            count += 1
        return count

    if conn is not None:
        return _save(conn)

    with db_session() as connection:
        return _save(connection)


def _row_to_competitor_price(row: sqlite3.Row) -> CompetitorPriceRecord:
    keys = row.keys()
    captured_at = None
    if "captured_at" in keys and row["captured_at"]:
        captured_at = datetime.fromisoformat(row["captured_at"])
    breakfast: bool | None = None
    if "is_breakfast_included" in keys and row["is_breakfast_included"] is not None:
        breakfast = bool(row["is_breakfast_included"])
    check_in = None
    if "check_in" in keys and row["check_in"]:
        check_in = _parse_date(row["check_in"])
    check_out = None
    if "check_out" in keys and row["check_out"]:
        check_out = _parse_date(row["check_out"])
    return CompetitorPriceRecord(
        id=row["id"],
        competitor_name=row["competitor_name"],
        date=_parse_date(row["date"]),
        price_from=row["price_from"],
        currency=row["currency"] or "RUB",
        source=row["source"] or "dom",
        screenshot_path=row["screenshot_path"],
        available=bool(row["available"]),
        category=(row["category"] if "category" in keys else "") or "",
        check_in=check_in,
        check_out=check_out,
        price_kind=(row["price_kind"] if "price_kind" in keys else "dynamic")
        or "dynamic",
        booking_engine=row["booking_engine"] if "booking_engine" in keys else None,
        is_breakfast_included=breakfast,
        cancellation_policy=row["cancellation_policy"]
        if "cancellation_policy" in keys
        else None,
        captured_at=captured_at,
        raw_url=row["raw_url"] if "raw_url" in keys else None,
        error_message=row["error_message"] if "error_message" in keys else None,
    )


def get_competitor_prices_latest() -> list[CompetitorPriceRecord]:
    """Последний агрегат («цена от») по каждому конкуренту.

    Приоритет: dynamic > public_from > cached.
    """
    sql = """
        SELECT cp.* FROM competitor_prices cp
        WHERE COALESCE(cp.category, '') = ''
          AND cp.id = (
            SELECT c2.id FROM competitor_prices c2
            WHERE c2.competitor_name = cp.competitor_name
              AND COALESCE(c2.category, '') = ''
            ORDER BY
              CASE COALESCE(c2.price_kind, 'dynamic')
                WHEN 'dynamic' THEN 0
                WHEN 'public_from' THEN 1
                ELSE 2
              END,
              c2.date DESC, c2.id DESC
            LIMIT 1
          )
        ORDER BY cp.competitor_name
    """
    with db_session() as conn:
        rows = conn.execute(sql).fetchall()
    return [_row_to_competitor_price(row) for row in rows]


def get_competitor_prices_history(
    competitor_name: str,
    days: int = 90,
) -> list[CompetitorPriceRecord]:
    """История агрегатных цен конкурента за период."""
    start = date.today() - timedelta(days=days)
    sql = """
        SELECT * FROM competitor_prices
        WHERE competitor_name = ? AND date >= ?
          AND COALESCE(category, '') = ''
        ORDER BY date DESC
    """
    with db_session() as conn:
        rows = conn.execute(sql, (competitor_name, _date_str(start))).fetchall()
    return [_row_to_competitor_price(row) for row in rows]


def get_competitor_category_prices(
    competitor_name: str,
    on_date: date | None = None,
) -> list[CompetitorPriceRecord]:
    """Цены по объектам/категориям конкурента на дату (последнюю, если не указана)."""
    if on_date is None:
        sql_date = """
            SELECT MAX(date) AS max_date FROM competitor_prices
            WHERE competitor_name = ? AND COALESCE(category, '') != ''
        """
        with db_session() as conn:
            row = conn.execute(sql_date, (competitor_name,)).fetchone()
        if row is None or row["max_date"] is None:
            return []
        on_date = _parse_date(row["max_date"])

    sql = """
        SELECT * FROM competitor_prices
        WHERE competitor_name = ? AND date = ?
          AND COALESCE(category, '') != ''
        ORDER BY price_from ASC
    """
    with db_session() as conn:
        rows = conn.execute(
            sql, (competitor_name, _date_str(on_date))
        ).fetchall()
    return [_row_to_competitor_price(row) for row in rows]


def _row_to_trend(row: sqlite3.Row) -> TrendRecord:
    published = row["published_at"]
    return TrendRecord(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        category=row["category"],
        region=row["region"],
        source_url=row["source_url"],
        takeaway=row["takeaway"],
        published_at=_parse_date(published) if published else None,
        is_idea_of_week=bool(row["is_idea_of_week"]),
    )


def save_trends(
    records: Iterable[TrendRecord],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Сохранить тренды в БД."""
    items = list(records)
    if not items:
        return 0

    sql = """
        INSERT INTO trends (
            title, summary, category, region, source_url,
            published_at, takeaway, is_idea_of_week
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """

    def _save(connection: sqlite3.Connection) -> int:
        count = 0
        for item in items:
            connection.execute(
                sql,
                (
                    item.title,
                    item.summary,
                    item.category,
                    item.region,
                    item.source_url,
                    _date_str(item.published_at) if item.published_at else None,
                    item.takeaway,
                    int(item.is_idea_of_week),
                ),
            )
            count += 1
        return count

    if conn is not None:
        return _save(conn)

    with db_session() as connection:
        return _save(connection)


def get_trends_records(
    region: str | None = None,
    category: str | None = None,
    days: int = 30,
) -> list[TrendRecord]:
    """Прочитать тренды с фильтрами."""
    start = date.today() - timedelta(days=days)
    sql = """
        SELECT * FROM trends
        WHERE COALESCE(published_at, date(created_at)) >= ?
    """
    params: list[object] = [_date_str(start)]
    if region:
        sql += " AND region = ?"
        params.append(region)
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY COALESCE(published_at, date(created_at)) DESC, id DESC"

    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_trend(row) for row in rows]


def get_trend_idea_of_week() -> TrendRecord | None:
    """Выделенная идея недели."""
    sql = """
        SELECT * FROM trends
        WHERE is_idea_of_week = 1
        ORDER BY COALESCE(published_at, date(created_at)) DESC, id DESC
        LIMIT 1
    """
    with db_session() as conn:
        row = conn.execute(sql).fetchone()
    if row is None:
        return None
    return _row_to_trend(row)


def trends_count() -> int:
    with db_session() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM trends").fetchone()
    return int(row["c"])


def prune_old_trends(
    days: int = TRENDS_RETENTION_DAYS,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Удалить тренды старше days дней."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    sql = """
        DELETE FROM trends
        WHERE COALESCE(published_at, date(created_at)) < ?
    """

    def _prune(connection: sqlite3.Connection) -> int:
        cur = connection.execute(sql, (cutoff,))
        return cur.rowcount

    if conn is not None:
        return _prune(conn)

    with db_session() as connection:
        return _prune(connection)


def clear_trends_idea_of_week(conn: sqlite3.Connection | None = None) -> None:
    """Сбросить флаг is_idea_of_week у всех записей."""

    def _clear(connection: sqlite3.Connection) -> None:
        connection.execute("UPDATE trends SET is_idea_of_week = 0")

    if conn is not None:
        _clear(conn)
        return

    with db_session() as connection:
        _clear(connection)


def _row_to_insight(row: sqlite3.Row) -> InsightRecord:
    import json

    updated = row["updated_at"]
    return InsightRecord(
        id=row["id"],
        topic=row["topic"],
        title=row["title"],
        summary=row["summary"],
        recommendations=json.loads(row["recommendations"] or "[]"),
        severity=row["severity"],
        source=row["source"],
        period=row["period"] or "",
        detail_payload=json.loads(row["detail_payload"] or "{}"),
        updated_at=_parse_dt(updated) if updated else None,
    )


def replace_insights(
    records: Iterable[InsightRecord],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Заменить кеш аналитики (удалить старые + вставить новые)."""
    import json

    items = list(records)

    def _replace(connection: sqlite3.Connection) -> int:
        connection.execute("DELETE FROM insights")
        count = 0
        sql = """
            INSERT INTO insights (
                topic, title, summary, recommendations, severity,
                source, period, detail_payload, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for item in items:
            connection.execute(
                sql,
                (
                    item.topic,
                    item.title,
                    item.summary,
                    json.dumps(item.recommendations, ensure_ascii=False),
                    item.severity,
                    item.source,
                    item.period,
                    json.dumps(item.detail_payload, ensure_ascii=False),
                    _dt_str(item.updated_at) if item.updated_at else _dt_str(datetime.utcnow()),
                ),
            )
            count += 1
        return count

    if conn is not None:
        return _replace(conn)
    with db_session() as connection:
        return _replace(connection)


def get_insights_records(
    source: str | None = None,
    topic: str | None = None,
) -> list[InsightRecord]:
    """Прочитать карточки аналитики."""
    sql = "SELECT * FROM insights WHERE 1=1"
    params: list[object] = []
    if source:
        sql += " AND source = ?"
        params.append(source)
    if topic:
        sql += " AND topic = ?"
        params.append(topic)
    sql += " ORDER BY id ASC"

    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_insight(row) for row in rows]


def insights_count() -> int:
    with db_session() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM insights").fetchone()
    return int(row["c"])


def save_mail_messages(
    records: Iterable[MailMessageRecord],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Upsert писем по (message_id, mailbox)."""
    import json

    sql = """
        INSERT INTO mail_messages (
            message_id, mailbox, folder, from_addr, subject, received_at,
            body_excerpt, mail_class, for_reviews, parsed_json, headers_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id, mailbox) DO UPDATE SET
            folder=excluded.folder,
            from_addr=excluded.from_addr,
            subject=excluded.subject,
            received_at=excluded.received_at,
            body_excerpt=excluded.body_excerpt,
            mail_class=excluded.mail_class,
            for_reviews=excluded.for_reviews,
            parsed_json=excluded.parsed_json,
            headers_hash=excluded.headers_hash
    """

    def _save(c: sqlite3.Connection) -> int:
        count = 0
        for item in records:
            c.execute(
                sql,
                (
                    item.message_id,
                    item.mailbox,
                    item.folder,
                    item.from_addr,
                    item.subject,
                    _dt_str(item.received_at) if item.received_at else None,
                    item.body_excerpt,
                    item.mail_class,
                    1 if item.for_reviews else 0,
                    json.dumps(item.parsed_json or {}, ensure_ascii=False),
                    item.headers_hash,
                ),
            )
            count += 1
        return count

    if conn is not None:
        return _save(conn)
    with db_session() as connection:
        return _save(connection)


def get_mail_messages(
    *,
    mail_class: str | None = None,
    for_reviews: bool | None = None,
    limit: int = 200,
) -> list[MailMessageRecord]:
    """Прочитать письма из inbox-хранилища."""
    import json

    sql = "SELECT * FROM mail_messages WHERE 1=1"
    params: list[object] = []
    if mail_class:
        sql += " AND mail_class = ?"
        params.append(mail_class)
    if for_reviews is not None:
        sql += " AND for_reviews = ?"
        params.append(1 if for_reviews else 0)
    sql += " ORDER BY received_at DESC, id DESC LIMIT ?"
    params.append(limit)

    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()

    out: list[MailMessageRecord] = []
    for row in rows:
        parsed: dict = {}
        try:
            parsed = json.loads(row["parsed_json"] or "{}")
        except json.JSONDecodeError:
            parsed = {}
        received = None
        if row["received_at"]:
            try:
                received = datetime.fromisoformat(str(row["received_at"]))
            except ValueError:
                received = None
        out.append(
            MailMessageRecord(
                id=row["id"],
                message_id=row["message_id"],
                mailbox=row["mailbox"],
                folder=row["folder"],
                from_addr=row["from_addr"],
                subject=row["subject"],
                received_at=received,
                body_excerpt=row["body_excerpt"],
                mail_class=row["mail_class"],
                for_reviews=bool(row["for_reviews"]),
                parsed_json=parsed,
                headers_hash=row["headers_hash"],
            )
        )
    return out


def _row_to_forecast_run(row: sqlite3.Row) -> ForecastRunRecord:
    calc = datetime.fromisoformat(str(row["calculated_at"]))
    run_d = _parse_date(row["run_date"]) if row["run_date"] else calc.date()
    return ForecastRunRecord(
        id=row["id"],
        calculated_at=calc,
        run_date=run_d,
        horizon_days=row["horizon_days"],
        model_version=row["model_version"] or "v1",
        data_quality=row["data_quality"] or "unknown",
        status=row["status"] or "completed",
    )


def upsert_forecast_run(record: ForecastRunRecord) -> ForecastRunRecord:
    """Идемпотентный запуск прогноза за дату и горизонт."""
    calc_at = record.calculated_at.isoformat()
    run_date = _date_str(record.run_date or record.calculated_at.date())
    sql = """
        INSERT INTO forecast_runs (
            calculated_at, run_date, horizon_days, model_version, data_quality, status
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_date, horizon_days, model_version) DO UPDATE SET
            calculated_at = excluded.calculated_at,
            data_quality = excluded.data_quality,
            status = excluded.status
    """
    with db_session() as conn:
        conn.execute(
            sql,
            (
                calc_at,
                run_date,
                record.horizon_days,
                record.model_version,
                record.data_quality,
                record.status,
            ),
        )
        row = conn.execute(
            """
            SELECT * FROM forecast_runs
            WHERE run_date = ? AND horizon_days = ? AND model_version = ?
            """,
            (run_date, record.horizon_days, record.model_version),
        ).fetchone()
    assert row is not None
    return _row_to_forecast_run(row)


def delete_forecast_daily_for_run(run_id: int) -> None:
    with db_session() as conn:
        conn.execute("DELETE FROM forecast_daily WHERE run_id = ?", (run_id,))


def save_forecast_daily_batch(records: list[ForecastDailyRecord]) -> int:
    """Сохранить строки прогноза."""
    import json

    if not records:
        return 0
    sql = """
        INSERT INTO forecast_daily (
            run_id, forecast_date, room_type, scenario, occupancy_pct, adr, revpar,
            revenue, sold_unit_nights, available_unit_nights, lower_bound, upper_bound,
            confidence, factors_json, actual_occupancy_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, forecast_date, room_type, scenario) DO UPDATE SET
            occupancy_pct = excluded.occupancy_pct,
            adr = excluded.adr,
            revpar = excluded.revpar,
            revenue = excluded.revenue,
            sold_unit_nights = excluded.sold_unit_nights,
            available_unit_nights = excluded.available_unit_nights,
            lower_bound = excluded.lower_bound,
            upper_bound = excluded.upper_bound,
            confidence = excluded.confidence,
            factors_json = excluded.factors_json,
            actual_occupancy_pct = excluded.actual_occupancy_pct
    """
    count = 0
    with db_session() as conn:
        for item in records:
            conn.execute(
                sql,
                (
                    item.run_id,
                    _date_str(item.forecast_date),
                    item.room_type,
                    item.scenario,
                    item.occupancy_pct,
                    item.adr,
                    item.revpar,
                    item.revenue,
                    item.sold_unit_nights,
                    item.available_unit_nights,
                    item.lower_bound,
                    item.upper_bound,
                    item.confidence,
                    json.dumps(item.factors_json, ensure_ascii=False),
                    item.actual_occupancy_pct,
                ),
            )
            count += 1
    return count


def get_latest_forecast_run(horizon_days: int) -> ForecastRunRecord | None:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT * FROM forecast_runs
            WHERE horizon_days = ?
            ORDER BY calculated_at DESC
            LIMIT 1
            """,
            (horizon_days,),
        ).fetchone()
    return _row_to_forecast_run(row) if row else None


def get_forecast_daily(
    run_id: int,
    scenario: str = "base",
    room_type: str | None = None,
) -> list[ForecastDailyRecord]:
    import json

    sql = """
        SELECT * FROM forecast_daily
        WHERE run_id = ? AND scenario = ?
    """
    params: list[object] = [run_id, scenario]
    if room_type is not None:
        sql += " AND room_type = ?"
        params.append(room_type)
    sql += " ORDER BY forecast_date ASC, room_type ASC"
    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()
    out: list[ForecastDailyRecord] = []
    for row in rows:
        factors: dict = {}
        try:
            factors = json.loads(row["factors_json"] or "{}")
        except json.JSONDecodeError:
            factors = {}
        out.append(
            ForecastDailyRecord(
                id=row["id"],
                run_id=row["run_id"],
                forecast_date=_parse_date(row["forecast_date"]),
                room_type=row["room_type"] or "",
                scenario=row["scenario"],
                occupancy_pct=row["occupancy_pct"],
                adr=row["adr"],
                revpar=row["revpar"],
                revenue=row["revenue"],
                sold_unit_nights=row["sold_unit_nights"],
                available_unit_nights=row["available_unit_nights"],
                lower_bound=row["lower_bound"],
                upper_bound=row["upper_bound"],
                confidence=row["confidence"],
                factors_json=factors,
                actual_occupancy_pct=row["actual_occupancy_pct"],
            )
        )
    return out


def get_forecast_daily_id_map(run_id: int) -> dict[tuple[str, str, str], int]:
    """Ключ (forecast_date, room_type, scenario) → id."""
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, forecast_date, room_type, scenario
            FROM forecast_daily WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
    return {
        (str(r["forecast_date"]), r["room_type"] or "", r["scenario"]): int(r["id"])
        for r in rows
    }


def _optional_dt_field(row: sqlite3.Row, key: str) -> datetime | None:
    if key not in row.keys() or not row[key]:
        return None
    try:
        return datetime.fromisoformat(str(row[key]))
    except ValueError:
        return None


def _row_to_price_recommendation(row: sqlite3.Row) -> PriceRecommendationRecord:
    import json

    snapshot: dict | None = None
    raw_snap = (
        row["recommendation_snapshot_json"]
        if "recommendation_snapshot_json" in row.keys()
        else None
    )
    if raw_snap:
        try:
            snapshot = json.loads(raw_snap) if isinstance(raw_snap, str) else raw_snap
        except (json.JSONDecodeError, TypeError):
            snapshot = None

    def _opt_float(key: str) -> float | None:
        if key not in row.keys() or row[key] is None:
            return None
        return float(row[key])

    def _opt_str(key: str) -> str | None:
        if key not in row.keys() or row[key] is None:
            return None
        return str(row[key])

    return PriceRecommendationRecord(
        id=row["id"],
        forecast_id=row["forecast_id"],
        room_type=row["room_type"],
        target_date=_parse_date(row["target_date"]),
        current_price=row["current_price"],
        recommended_price_min=row["recommended_price_min"],
        recommended_price_max=row["recommended_price_max"],
        recommendation_type=row["recommendation_type"],
        reason=row["reason"],
        confidence=row["confidence"],
        status=row["status"],
        decided_at=_optional_dt_field(row, "decided_at"),
        horizon_days=row["horizon_days"] if "horizon_days" in row.keys() else None,
        recommendation_snapshot_json=snapshot,
        selected_price=_opt_float("selected_price"),
        reviewed_at=_optional_dt_field(row, "reviewed_at"),
        reviewed_by=_opt_str("reviewed_by"),
        applied_at=_optional_dt_field(row, "applied_at"),
        applied_by=_opt_str("applied_by"),
        applied_price=_opt_float("applied_price"),
        applied_note=_opt_str("applied_note"),
        verified_at=_optional_dt_field(row, "verified_at"),
        verification_result=_opt_str("verification_result"),
        rollback_at=_optional_dt_field(row, "rollback_at"),
        rollback_reason=_opt_str("rollback_reason"),
        manager_comment=_opt_str("manager_comment"),
    )


def save_price_recommendations(
    records: list[PriceRecommendationRecord],
    horizon_days: int,
    as_of: date,
) -> int:
    """Сохранить рекомендации; старые new/reviewed за горизонт помечаем expired."""
    import json

    if not records:
        return 0
    with db_session() as conn:
        conn.execute(
            """
            UPDATE price_recommendations
            SET status = 'expired'
            WHERE status IN ('new', 'reviewed') AND horizon_days = ?
              AND target_date >= ? AND target_date <= ?
            """,
            (
                horizon_days,
                _date_str(as_of),
                _date_str(as_of + timedelta(days=horizon_days)),
            ),
        )
        sql = """
            INSERT INTO price_recommendations (
                forecast_id, room_type, target_date, current_price,
                recommended_price_min, recommended_price_max,
                recommendation_type, reason, confidence, status, horizon_days,
                recommendation_snapshot_json, selected_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        count = 0
        for item in records:
            snap_json = None
            if item.recommendation_snapshot_json is not None:
                snap_json = json.dumps(
                    item.recommendation_snapshot_json, ensure_ascii=False
                )
            conn.execute(
                sql,
                (
                    item.forecast_id,
                    item.room_type,
                    _date_str(item.target_date),
                    item.current_price,
                    item.recommended_price_min,
                    item.recommended_price_max,
                    item.recommendation_type,
                    item.reason,
                    item.confidence,
                    item.status,
                    item.horizon_days or horizon_days,
                    snap_json,
                    item.selected_price,
                ),
            )
            count += 1
    return count


def get_price_recommendation_by_id(rec_id: int) -> PriceRecommendationRecord | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM price_recommendations WHERE id = ?",
            (rec_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_price_recommendation(row)


def get_price_recommendations(
    status: str | None = None,
    room_type: str | None = None,
    horizon_days: int | None = None,
    limit: int = 200,
) -> list[PriceRecommendationRecord]:
    sql = "SELECT * FROM price_recommendations WHERE 1=1"
    params: list[object] = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if room_type:
        sql += " AND room_type = ?"
        params.append(room_type)
    if horizon_days is not None:
        sql += " AND horizon_days = ?"
        params.append(horizon_days)
    sql += " ORDER BY target_date ASC, id DESC LIMIT ?"
    params.append(limit)
    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_price_recommendation(row) for row in rows]


def update_price_recommendation_status(
    rec_id: int,
    status: str,
) -> bool:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE price_recommendations
            SET status = ?, decided_at = datetime('now')
            WHERE id = ?
            """,
            (status, rec_id),
        )
        return cur.rowcount > 0


def mark_recommendation_reviewed(rec_id: int, reviewed_by: str) -> bool:
    """Перевести new → reviewed при первом открытии карточки."""
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE price_recommendations
            SET status = 'reviewed',
                reviewed_at = datetime('now'),
                reviewed_by = ?
            WHERE id = ? AND status = 'new'
            """,
            (reviewed_by, rec_id),
        )
        return cur.rowcount > 0


def update_recommendation_manager_comment(rec_id: int, comment: str) -> bool:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE price_recommendations
            SET manager_comment = ?
            WHERE id = ?
            """,
            (comment, rec_id),
        )
        return cur.rowcount > 0


def apply_price_recommendation(
    rec_id: int,
    *,
    selected_price: float,
    applied_by: str,
    applied_note: str | None = None,
) -> bool:
    """Отметить рекомендацию как применённую вручную (без смены цены в TL)."""
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE price_recommendations
            SET status = 'applied',
                selected_price = ?,
                applied_price = ?,
                applied_at = datetime('now'),
                applied_by = ?,
                applied_note = ?,
                decided_at = datetime('now')
            WHERE id = ?
            """,
            (selected_price, selected_price, applied_by, applied_note, rec_id),
        )
        return cur.rowcount > 0


def verify_price_recommendation(
    rec_id: int,
    verification_result: str,
) -> bool:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE price_recommendations
            SET status = 'verified',
                verified_at = datetime('now'),
                verification_result = ?,
                decided_at = datetime('now')
            WHERE id = ?
            """,
            (verification_result, rec_id),
        )
        return cur.rowcount > 0


def rollback_price_recommendation(
    rec_id: int,
    rollback_reason: str,
) -> bool:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE price_recommendations
            SET status = 'rolled_back',
                rollback_at = datetime('now'),
                rollback_reason = ?,
                decided_at = datetime('now')
            WHERE id = ?
            """,
            (rollback_reason, rec_id),
        )
        return cur.rowcount > 0


def _row_to_recommendation(row: sqlite3.Row) -> RecommendationRecord:
    import json

    def _j(key: str) -> dict:
        raw = row[key] if key in row.keys() else None
        if not raw:
            return {}
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _odt(key: str) -> datetime | None:
        if key not in row.keys() or not row[key]:
            return None
        try:
            return datetime.fromisoformat(str(row[key]))
        except ValueError:
            return None

    target = None
    if row["target_date"]:
        try:
            target = _parse_date(row["target_date"])
        except ValueError:
            target = None

    return RecommendationRecord(
        id=row["id"],
        source_module=row["source_module"],
        recommendation_type=row["recommendation_type"],
        title=row["title"],
        summary=row["summary"] or "",
        priority=row["priority"] or "medium",
        status=row["status"] or "new",
        target_date=target,
        due_at=_odt("due_at"),
        owner=row["owner"] or "Менеджер объекта",
        instruction_template=row["instruction_template"],
        instruction_payload_json=_j("instruction_payload_json"),
        evidence_snapshot_json=_j("evidence_snapshot_json"),
        expected_result=row["expected_result"] or "",
        success_criteria_json=_j("success_criteria_json"),
        rollback_plan=row["rollback_plan"] or "",
        source_ref=row["source_ref"],
        created_at=_odt("created_at"),
        accepted_at=_odt("accepted_at"),
        completed_at=_odt("completed_at"),
        completed_by=row["completed_by"] if "completed_by" in row.keys() else None,
        completion_note=row["completion_note"] if "completion_note" in row.keys() else None,
    )


def get_recommendation_by_id(rec_id: int) -> RecommendationRecord | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM recommendations WHERE id = ?", (rec_id,)
        ).fetchone()
    return _row_to_recommendation(row) if row else None


def get_recommendation_by_source_ref(source_ref: str) -> RecommendationRecord | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM recommendations WHERE source_ref = ?",
            (source_ref,),
        ).fetchone()
    return _row_to_recommendation(row) if row else None


def list_recommendations(
    *,
    status: str | None = None,
    statuses: list[str] | None = None,
    priority: str | None = None,
    source_module: str | None = None,
    limit: int = 200,
) -> list[RecommendationRecord]:
    sql = "SELECT * FROM recommendations WHERE 1=1"
    params: list[object] = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        sql += f" AND status IN ({placeholders})"
        params.extend(statuses)
    if priority:
        sql += " AND priority = ?"
        params.append(priority)
    if source_module:
        sql += " AND source_module = ?"
        params.append(source_module)
    sql += """
        ORDER BY
            CASE priority
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                ELSE 3
            END,
            COALESCE(due_at, created_at) ASC,
            id DESC
        LIMIT ?
    """
    params.append(limit)
    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_recommendation(r) for r in rows]


def upsert_recommendation(rec: RecommendationRecord) -> int:
    """Вставить или обновить по source_ref.

    Если запись уже принята/в работе/выполнена — не затираем status и completion,
    обновляем только evidence/payload/title при статусе new (или вставляем новую).
    """
    import json

    payload = json.dumps(rec.instruction_payload_json or {}, ensure_ascii=False)
    evidence = json.dumps(rec.evidence_snapshot_json or {}, ensure_ascii=False)
    criteria = json.dumps(rec.success_criteria_json or {}, ensure_ascii=False)
    due = _dt_str(rec.due_at) if rec.due_at else None
    target = _date_str(rec.target_date) if rec.target_date else None

    with db_session() as conn:
        existing = None
        if rec.source_ref:
            existing = conn.execute(
                "SELECT * FROM recommendations WHERE source_ref = ?",
                (rec.source_ref,),
            ).fetchone()
        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO recommendations (
                    source_module, recommendation_type, title, summary, priority,
                    status, target_date, due_at, owner, instruction_template,
                    instruction_payload_json, evidence_snapshot_json,
                    expected_result, success_criteria_json, rollback_plan, source_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.source_module,
                    rec.recommendation_type,
                    rec.title,
                    rec.summary,
                    rec.priority,
                    rec.status,
                    target,
                    due,
                    rec.owner,
                    rec.instruction_template,
                    payload,
                    evidence,
                    rec.expected_result,
                    criteria,
                    rec.rollback_plan,
                    rec.source_ref,
                ),
            )
            return int(cur.lastrowid)

        ex_status = existing["status"]
        if ex_status in ("new", "expired"):
            conn.execute(
                """
                UPDATE recommendations SET
                    source_module = ?, recommendation_type = ?, title = ?, summary = ?,
                    priority = ?, status = ?, target_date = ?, due_at = ?, owner = ?,
                    instruction_template = ?, instruction_payload_json = ?,
                    evidence_snapshot_json = ?, expected_result = ?,
                    success_criteria_json = ?, rollback_plan = ?
                WHERE id = ?
                """,
                (
                    rec.source_module,
                    rec.recommendation_type,
                    rec.title,
                    rec.summary,
                    rec.priority,
                    rec.status,
                    target,
                    due,
                    rec.owner,
                    rec.instruction_template,
                    payload,
                    evidence,
                    rec.expected_result,
                    criteria,
                    rec.rollback_plan,
                    existing["id"],
                ),
            )
        else:
            # Сохраняем статус пользователя, обновляем только факты
            conn.execute(
                """
                UPDATE recommendations SET
                    title = ?, summary = ?, priority = ?, target_date = ?, due_at = ?,
                    instruction_payload_json = ?, evidence_snapshot_json = ?,
                    expected_result = ?, success_criteria_json = ?, rollback_plan = ?
                WHERE id = ?
                """,
                (
                    rec.title,
                    rec.summary,
                    rec.priority,
                    target,
                    due,
                    payload,
                    evidence,
                    rec.expected_result,
                    criteria,
                    rec.rollback_plan,
                    existing["id"],
                ),
            )
        return int(existing["id"])


def update_recommendation_status(
    rec_id: int,
    status: str,
    *,
    actor: str | None = None,
    note: str | None = None,
) -> bool:
    with db_session() as conn:
        if status == "accepted":
            cur = conn.execute(
                """
                UPDATE recommendations
                SET status = 'accepted', accepted_at = datetime('now')
                WHERE id = ?
                """,
                (rec_id,),
            )
        elif status == "done":
            cur = conn.execute(
                """
                UPDATE recommendations
                SET status = 'done',
                    completed_at = datetime('now'),
                    completed_by = ?,
                    completion_note = ?
                WHERE id = ?
                """,
                (actor, note, rec_id),
            )
        elif status == "in_progress":
            cur = conn.execute(
                """
                UPDATE recommendations SET status = 'in_progress' WHERE id = ?
                """,
                (rec_id,),
            )
        else:
            cur = conn.execute(
                """
                UPDATE recommendations
                SET status = ?, completion_note = COALESCE(?, completion_note)
                WHERE id = ?
                """,
                (status, note, rec_id),
            )
        return cur.rowcount > 0


def expire_overdue_recommendations() -> int:
    """Просроченные new/accepted/in_progress → expired."""
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE recommendations
            SET status = 'expired'
            WHERE status IN ('new', 'accepted', 'in_progress')
              AND due_at IS NOT NULL
              AND due_at < datetime('now')
            """
        )
        return cur.rowcount


def count_recommendations_summary() -> dict[str, int]:
    with db_session() as conn:
        critical = conn.execute(
            """
            SELECT COUNT(*) AS c FROM recommendations
            WHERE priority = 'critical'
              AND status IN ('new', 'accepted', 'in_progress')
            """
        ).fetchone()["c"]
        due_today = conn.execute(
            """
            SELECT COUNT(*) AS c FROM recommendations
            WHERE status IN ('new', 'accepted', 'in_progress')
              AND date(due_at) = date('now')
            """
        ).fetchone()["c"]
        done_week = conn.execute(
            """
            SELECT COUNT(*) AS c FROM recommendations
            WHERE status = 'done'
              AND completed_at >= datetime('now', '-7 days')
            """
        ).fetchone()["c"]
    return {
        "critical": int(critical),
        "due_today": int(due_today),
        "done_week": int(done_week),
    }


def get_forecast_accuracy_rows(start: date, end: date) -> list[dict]:
    """Строки base-прогноза (all) для оценки точности."""
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT fd.forecast_date, fd.occupancy_pct, fd.revenue
            FROM forecast_daily fd
            JOIN forecast_runs fr ON fr.id = fd.run_id
            WHERE fd.scenario = 'base' AND fd.room_type = ''
              AND fd.forecast_date >= ? AND fd.forecast_date <= ?
              AND fr.id = (
                  SELECT id FROM forecast_runs fr2
                  WHERE fr2.horizon_days = fr.horizon_days
                    AND date(fr2.calculated_at) <= fd.forecast_date
                  ORDER BY fr2.calculated_at DESC LIMIT 1
              )
            ORDER BY fd.forecast_date
            """,
            (_date_str(start), _date_str(end)),
        ).fetchall()
    return [
        {
            "forecast_date": _parse_date(r["forecast_date"]),
            "occupancy_pct": r["occupancy_pct"],
            "revenue": r["revenue"],
        }
        for r in rows
    ]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _row_keys(row: sqlite3.Row) -> set[str]:
    return set(row.keys())


def _row_to_city_event(row: sqlite3.Row) -> CityEventRecord:
    keys = _row_keys(row)
    return CityEventRecord(
        id=row["id"],
        title=row["title"],
        normalized_title=row["normalized_title"],
        category=row["category"],
        start_at=_parse_date(row["start_at"]),
        end_at=_parse_date(row["end_at"]) if row["end_at"] else None,
        city=row["city"],
        venue_name=row["venue_name"],
        venue_address=row["venue_address"],
        estimated_capacity=row["estimated_capacity"],
        audience_scope=row["audience_scope"],
        source_url=row["source_url"],
        source_name=row["source_name"],
        source_priority=row["source_priority"],
        status=row["status"],
        impact_score=row["impact_score"],
        confidence=row["confidence"],
        expected_guest_nights_min=row["expected_guest_nights_min"],
        expected_guest_nights_max=row["expected_guest_nights_max"],
        forecast_coefficient=row["forecast_coefficient"],
        description=row["description"],
        is_online=bool(row["is_online"]) if "is_online" in keys else False,
        registration_required=bool(row["registration_required"])
        if "registration_required" in keys
        else False,
        expected_attendance=row["expected_attendance"] if "expected_attendance" in keys else None,
        attendance_source=row["attendance_source"] if "attendance_source" in keys else "unknown",
        tourism_relevance=row["tourism_relevance"] if "tourism_relevance" in keys else "none",
        overnight_likelihood=float(row["overnight_likelihood"])
        if "overnight_likelihood" in keys and row["overnight_likelihood"] is not None
        else 0.1,
        is_public_holiday=bool(row["is_public_holiday"]) if "is_public_holiday" in keys else False,
        location_confirmed=bool(row["location_confirmed"]) if "location_confirmed" in keys else False,
        category_manual=bool(row["category_manual"]) if "category_manual" in keys else False,
        category_source=row["category_source"] if "category_source" in keys else "rules",
        start_time=row["start_time"] if "start_time" in keys else None,
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def _row_to_event_source(row: sqlite3.Row) -> EventSourceRecord:
    return EventSourceRecord(
        id=row["id"],
        event_id=row["event_id"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        source_event_id=row["source_event_id"],
        captured_at=_parse_dt(row["captured_at"]),
        raw_title=row["raw_title"],
        raw_date=row["raw_date"],
        raw_venue=row["raw_venue"],
        is_primary=bool(row["is_primary"]),
    )


def _row_to_event_review(row: sqlite3.Row) -> EventReviewLogRecord:
    return EventReviewLogRecord(
        id=row["id"],
        event_id=row["event_id"],
        action=row["action"],
        old_value=row["old_value"],
        new_value=row["new_value"],
        comment=row["comment"],
        actor=row["actor"],
        created_at=_parse_dt(row["created_at"]),
    )


def save_city_event(record: CityEventRecord) -> CityEventRecord:
    """Создать или обновить событие."""
    now = _dt_str(datetime.now())
    with db_session() as conn:
        if record.id:
            conn.execute(
                """
                UPDATE city_events SET
                    title=?, normalized_title=?, category=?, start_at=?, end_at=?,
                    start_time=?,
                    city=?, venue_name=?, venue_address=?, estimated_capacity=?,
                    audience_scope=?, source_url=?, source_name=?, source_priority=?,
                    status=?, impact_score=?, confidence=?,
                    expected_guest_nights_min=?, expected_guest_nights_max=?,
                    forecast_coefficient=?, description=?,
                    is_online=?, registration_required=?, expected_attendance=?,
                    attendance_source=?, tourism_relevance=?, overnight_likelihood=?,
                    is_public_holiday=?, location_confirmed=?,
                    category_manual=?, category_source=?, updated_at=?
                WHERE id=?
                """,
                (
                    record.title,
                    record.normalized_title or record.title.lower(),
                    record.category,
                    _date_str(record.start_at),
                    _date_str(record.end_at) if record.end_at else None,
                    record.start_time,
                    record.city,
                    record.venue_name,
                    record.venue_address,
                    record.estimated_capacity,
                    record.audience_scope,
                    record.source_url,
                    record.source_name,
                    record.source_priority,
                    record.status,
                    record.impact_score,
                    record.confidence,
                    record.expected_guest_nights_min,
                    record.expected_guest_nights_max,
                    record.forecast_coefficient,
                    record.description,
                    int(record.is_online),
                    int(record.registration_required),
                    record.expected_attendance,
                    record.attendance_source,
                    record.tourism_relevance,
                    record.overnight_likelihood,
                    int(record.is_public_holiday),
                    int(record.location_confirmed),
                    int(record.category_manual),
                    record.category_source,
                    now,
                    record.id,
                ),
            )
            record.updated_at = _parse_dt(now)
            return record
        cur = conn.execute(
            """
            INSERT INTO city_events (
                title, normalized_title, category, start_at, end_at, start_time, city,
                venue_name, venue_address, estimated_capacity, audience_scope,
                source_url, source_name, source_priority, status, impact_score,
                confidence, expected_guest_nights_min, expected_guest_nights_max,
                forecast_coefficient, description,
                is_online, registration_required, expected_attendance,
                attendance_source, tourism_relevance, overnight_likelihood,
                is_public_holiday, location_confirmed,
                category_manual, category_source, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record.title,
                record.normalized_title or record.title.lower(),
                record.category,
                _date_str(record.start_at),
                _date_str(record.end_at) if record.end_at else None,
                record.start_time,
                record.city,
                record.venue_name,
                record.venue_address,
                record.estimated_capacity,
                record.audience_scope,
                record.source_url,
                record.source_name,
                record.source_priority,
                record.status,
                record.impact_score,
                record.confidence,
                record.expected_guest_nights_min,
                record.expected_guest_nights_max,
                record.forecast_coefficient,
                record.description,
                int(record.is_online),
                int(record.registration_required),
                record.expected_attendance,
                record.attendance_source,
                record.tourism_relevance,
                record.overnight_likelihood,
                int(record.is_public_holiday),
                int(record.location_confirmed),
                int(record.category_manual),
                record.category_source,
                now,
                now,
            ),
        )
        record.id = cur.lastrowid
        record.created_at = _parse_dt(now)
        record.updated_at = _parse_dt(now)
        return record


def get_city_event(event_id: int) -> CityEventRecord | None:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM city_events WHERE id=?", (event_id,)).fetchone()
    return _row_to_city_event(row) if row else None


def get_city_events(
    start: date | None = None,
    end: date | None = None,
    status: str | None = None,
    category: str | None = None,
    min_impact: float | None = None,
    source_name: str | None = None,
    limit: int = 500,
) -> list[CityEventRecord]:
    """Список событий с фильтрами."""
    clauses: list[str] = []
    params: list[object] = []
    if start:
        clauses.append("(end_at IS NULL OR end_at >= ?) AND start_at <= ?")
        params.extend([_date_str(start), _date_str(end or start)])
    if end and not start:
        clauses.append("start_at <= ?")
        params.append(_date_str(end))
    if status:
        clauses.append("status = ?")
        params.append(status)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if min_impact is not None:
        clauses.append("impact_score >= ?")
        params.append(min_impact)
    if source_name:
        clauses.append("source_name = ?")
        params.append(source_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db_session() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM city_events {where}
            ORDER BY start_at ASC, impact_score DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    return [_row_to_city_event(r) for r in rows]


def get_city_events_for_dedup(start: date, end: date) -> list[CityEventRecord]:
    return get_city_events(start=start, end=end, limit=2000)


def get_approved_city_events(start: date, end: date) -> list[CityEventRecord]:
    return get_city_events(start=start, end=end, status="approved", limit=500)


def save_event_source(record: EventSourceRecord) -> EventSourceRecord:
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO event_sources (
                event_id, source_name, source_url, source_event_id,
                captured_at, raw_title, raw_date, raw_venue, is_primary
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                record.event_id,
                record.source_name,
                record.source_url,
                record.source_event_id,
                _dt_str(record.captured_at or datetime.now()),
                record.raw_title,
                record.raw_date,
                record.raw_venue,
                1 if record.is_primary else 0,
            ),
        )
        record.id = cur.lastrowid
        return record


def get_event_sources(event_id: int) -> list[EventSourceRecord]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM event_sources WHERE event_id=? ORDER BY is_primary DESC, captured_at DESC",
            (event_id,),
        ).fetchall()
    return [_row_to_event_source(r) for r in rows]


def count_event_sources(event_id: int) -> int:
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM event_sources WHERE event_id=?",
            (event_id,),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def save_event_review_log(record: EventReviewLogRecord) -> EventReviewLogRecord:
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO event_review_log (event_id, action, old_value, new_value, comment, actor)
            VALUES (?,?,?,?,?,?)
            """,
            (
                record.event_id,
                record.action,
                record.old_value,
                record.new_value,
                record.comment,
                record.actor,
            ),
        )
        record.id = cur.lastrowid
        return record


def get_event_review_log(event_id: int, limit: int = 50) -> list[EventReviewLogRecord]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM event_review_log WHERE event_id=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (event_id, limit),
        ).fetchall()
    return [_row_to_event_review(r) for r in rows]


def expire_city_events(before: date) -> int:
    with db_session() as conn:
        cur = conn.execute(
            """
            UPDATE city_events SET status='expired', updated_at=datetime('now')
            WHERE status IN ('candidate', 'approved')
              AND COALESCE(end_at, start_at) < ?
            """,
            (_date_str(before),),
        )
        return cur.rowcount


def get_event_source_state(source_name: str) -> dict[str, str | None]:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM event_source_state WHERE source_name=?",
            (source_name,),
        ).fetchone()
    if not row:
        return {}
    return dict(row)


def upsert_event_source_state(
    source_name: str,
    *,
    last_success_at: datetime | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    last_error: str | None = None,
) -> None:
    now = _dt_str(datetime.now())
    with db_session() as conn:
        existing = conn.execute(
            "SELECT source_name FROM event_source_state WHERE source_name=?",
            (source_name,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE event_source_state SET
                    last_success_at=COALESCE(?, last_success_at),
                    etag=COALESCE(?, etag),
                    last_modified=COALESCE(?, last_modified),
                    last_error=?,
                    last_error_at=CASE WHEN ? IS NOT NULL THEN ? ELSE last_error_at END
                WHERE source_name=?
                """,
                (
                    _dt_str(last_success_at) if last_success_at else None,
                    etag,
                    last_modified,
                    last_error,
                    last_error,
                    now if last_error else None,
                    source_name,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO event_source_state (
                    source_name, last_success_at, etag, last_modified, last_error, last_error_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    source_name,
                    _dt_str(last_success_at) if last_success_at else None,
                    etag,
                    last_modified,
                    last_error,
                    now if last_error else None,
                ),
            )

