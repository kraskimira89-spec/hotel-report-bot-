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
    MIGRATIONS_V3,
    MIGRATIONS_V4,
    MIGRATIONS_V5,
    SCHEMA_VERSION,
    TABLES,
    TRENDS_RETENTION_DAYS,
    BookingDailyRecord,
    CompetitorPriceRecord,
    ErrorLogRecord,
    GuestRecord,
    InsightRecord,
    MetricsDailyRecord,
    PeriodComparison,
    PricePeriodComparison,
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
        return int(cur.lastrowid)

    with db_session() as connection:
        cur = connection.execute(sql, params)
        return int(cur.lastrowid)


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
            return int(cur.lastrowid)

        with db_session() as connection:
            cur = connection.execute(sql, params)
            return int(cur.lastrowid)
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
        deleted += prune_old_trends(conn=conn)
    logger.info("Удалено %s записей старше %s", deleted, cutoff)
    return deleted


def save_competitor_prices(
    records: Iterable[CompetitorPriceRecord],
    conn: sqlite3.Connection | None = None,
) -> int:
    """Сохранить снимки цен конкурентов (по одной записи на конкурента и дату)."""
    items = list(records)
    if not items:
        return 0

    sql = """
        INSERT INTO competitor_prices (
            competitor_name, date, price_from, currency, source,
            screenshot_path, available
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """

    def _save(connection: sqlite3.Connection) -> int:
        count = 0
        for item in items:
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
                ),
            )
            count += 1
        return count

    if conn is not None:
        return _save(conn)

    with db_session() as connection:
        return _save(connection)


def _row_to_competitor_price(row: sqlite3.Row) -> CompetitorPriceRecord:
    return CompetitorPriceRecord(
        id=row["id"],
        competitor_name=row["competitor_name"],
        date=_parse_date(row["date"]),
        price_from=row["price_from"],
        currency=row["currency"] or "RUB",
        source=row["source"] or "dom",
        screenshot_path=row["screenshot_path"],
        available=bool(row["available"]),
    )


def get_competitor_prices_latest() -> list[CompetitorPriceRecord]:
    """Последняя запись по каждому конкуренту."""
    sql = """
        SELECT cp.* FROM competitor_prices cp
        INNER JOIN (
            SELECT competitor_name, MAX(date) AS max_date
            FROM competitor_prices
            GROUP BY competitor_name
        ) latest ON cp.competitor_name = latest.competitor_name
            AND cp.date = latest.max_date
        ORDER BY cp.competitor_name
    """
    with db_session() as conn:
        rows = conn.execute(sql).fetchall()
    return [_row_to_competitor_price(row) for row in rows]


def get_competitor_prices_history(
    competitor_name: str,
    days: int = 90,
) -> list[CompetitorPriceRecord]:
    """История цен конкурента за период."""
    start = date.today() - timedelta(days=days)
    sql = """
        SELECT * FROM competitor_prices
        WHERE competitor_name = ? AND date >= ?
        ORDER BY date DESC
    """
    with db_session() as conn:
        rows = conn.execute(sql, (competitor_name, _date_str(start))).fetchall()
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
