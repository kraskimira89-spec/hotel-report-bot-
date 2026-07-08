"""SQL-схемы и модели записей SQLite."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

SCHEMA_VERSION = 3

TABLES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS price_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_at TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        category TEXT NOT NULL,
        price REAL NOT NULL,
        source TEXT NOT NULL DEFAULT 'site',
        is_estimated INTEGER NOT NULL DEFAULT 0,
        is_fallback INTEGER NOT NULL DEFAULT 0,
        url TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(snapshot_date, category, source)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metrics_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT NOT NULL,
        metric_type TEXT NOT NULL DEFAULT 'daily',
        occupancy_pct REAL,
        adr REAL,
        revpar REAL,
        als REAL,
        revenue REAL,
        bookings_count INTEGER,
        is_estimated INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(report_date, metric_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bookings_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_date TEXT NOT NULL,
        source TEXT NOT NULL,
        channel TEXT NOT NULL,
        amount REAL,
        guest_id TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guests (
        guest_id TEXT PRIMARY KEY,
        phone_hash TEXT,
        email_hash TEXT,
        fio_hash TEXT,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        visits_count INTEGER NOT NULL DEFAULT 1,
        is_returning INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reports_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_type TEXT NOT NULL,
        report_date TEXT NOT NULL,
        run_date TEXT NOT NULL,
        period_start TEXT,
        period_end TEXT,
        status TEXT NOT NULL,
        dry_run INTEGER NOT NULL DEFAULT 0,
        preview TEXT,
        message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS errors_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_date TEXT NOT NULL,
        source TEXT NOT NULL,
        error_type TEXT NOT NULL,
        message TEXT NOT NULL,
        details TEXT,
        resolved INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    )
    """,
]

INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_price_snapshots_date ON price_snapshots(snapshot_date)",
    "CREATE INDEX IF NOT EXISTS idx_price_snapshots_at ON price_snapshots(snapshot_at)",
    "CREATE INDEX IF NOT EXISTS idx_metrics_daily_date ON metrics_daily(report_date)",
    "CREATE INDEX IF NOT EXISTS idx_bookings_daily_created ON bookings_daily(created_date)",
    "CREATE INDEX IF NOT EXISTS idx_guests_phone ON guests(phone_hash)",
    "CREATE INDEX IF NOT EXISTS idx_guests_email ON guests(email_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_guests_guest_id ON guests(guest_id)",
    "CREATE INDEX IF NOT EXISTS idx_errors_log_created ON errors_log(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_errors_log_resolved ON errors_log(resolved)",
]

MIGRATIONS_V2: list[str] = [
    "ALTER TABLE price_snapshots ADD COLUMN snapshot_at TEXT",
    "ALTER TABLE price_snapshots ADD COLUMN is_fallback INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE price_snapshots ADD COLUMN url TEXT",
    "ALTER TABLE metrics_daily ADD COLUMN metric_type TEXT NOT NULL DEFAULT 'daily'",
    "ALTER TABLE metrics_daily ADD COLUMN bookings_count INTEGER",
    "ALTER TABLE bookings_daily ADD COLUMN created_date TEXT",
    "ALTER TABLE bookings_daily ADD COLUMN source TEXT",
    "ALTER TABLE bookings_daily ADD COLUMN amount REAL",
    "ALTER TABLE bookings_daily ADD COLUMN guest_id TEXT",
    "ALTER TABLE guests ADD COLUMN guest_id TEXT",
    "ALTER TABLE guests ADD COLUMN is_returning INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE reports_log ADD COLUMN dry_run INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE reports_log ADD COLUMN preview TEXT",
    "ALTER TABLE errors_log ADD COLUMN error_date TEXT",
    "ALTER TABLE errors_log ADD COLUMN resolved INTEGER NOT NULL DEFAULT 0",
]

MIGRATIONS_V3: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS runtime_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]


class PriceSnapshotRecord(BaseModel):
    """Запись snapshot цены."""

    snapshot_at: datetime
    category: str
    price: float
    source: str = "site"
    is_estimated: bool = False
    is_fallback: bool = False
    url: str | None = None
    id: int | None = None


class MetricsDailyRecord(BaseModel):
    """Ежедневные метрики."""

    report_date: date
    metric_type: str = "daily"
    occupancy_pct: float | None = None
    adr: float | None = None
    revpar: float | None = None
    als: float | None = None
    revenue: float | None = None
    bookings_count: int | None = None
    is_estimated: bool = False
    id: int | None = None


class BookingDailyRecord(BaseModel):
    """Бронирование за день."""

    created_date: date
    source: str
    channel: str
    amount: float | None = None
    guest_id: str | None = None
    id: int | None = None


class GuestRecord(BaseModel):
    """Гость (только хеши идентификаторов)."""

    guest_id: str
    phone_hash: str | None = None
    email_hash: str | None = None
    fio_hash: str | None = None
    first_seen: date
    last_seen: date
    visits_count: int = 1
    is_returning: bool = False


class ReportLogRecord(BaseModel):
    """Журнал отправленных отчётов."""

    report_type: str
    report_date: date
    run_date: date
    status: str
    dry_run: bool = False
    preview: str | None = None
    message: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    id: int | None = None


class ErrorLogRecord(BaseModel):
    """Журнал ошибок."""

    error_date: date
    source: str
    error_type: str
    message: str
    details: str | None = None
    resolved: bool = False
    id: int | None = None


class PeriodComparison(BaseModel):
    """Сравнение показателей за две даты."""

    reference_date: date
    compare_date: date
    metrics: MetricsDailyRecord | None = None
    reference_metrics: MetricsDailyRecord | None = None


class PricePeriodComparison(BaseModel):
    """Сравнение цен категории между датами."""

    category: str
    reference_date: date
    compare_date: date
    reference_price: float | None = None
    compare_price: float | None = None

    @property
    def change_pct(self) -> float | None:
        if self.reference_price is None or self.compare_price is None:
            return None
        if self.compare_price == 0:
            return None
        return round(
            (self.reference_price - self.compare_price) / self.compare_price * 100,
            2,
        )
