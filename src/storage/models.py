"""SQL-схемы таблиц SQLite."""

SCHEMA_VERSION = 1

TABLES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS price_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date TEXT NOT NULL,
        category TEXT NOT NULL,
        price REAL NOT NULL,
        source TEXT NOT NULL DEFAULT 'site',
        is_estimated INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(snapshot_date, category, source)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metrics_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT NOT NULL UNIQUE,
        occupancy_pct REAL,
        adr REAL,
        revpar REAL,
        als REAL,
        revenue REAL,
        is_estimated INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bookings_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT NOT NULL,
        channel TEXT NOT NULL,
        channel_type TEXT NOT NULL,
        bookings_count INTEGER NOT NULL DEFAULT 0,
        new_bookings_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(report_date, channel)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone_hash TEXT,
        email_hash TEXT,
        fio_hash TEXT,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        visits_count INTEGER NOT NULL DEFAULT 1
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
        message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS errors_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        error_type TEXT NOT NULL,
        message TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
    "CREATE INDEX IF NOT EXISTS idx_metrics_daily_date ON metrics_daily(report_date)",
    "CREATE INDEX IF NOT EXISTS idx_bookings_daily_date ON bookings_daily(report_date)",
    "CREATE INDEX IF NOT EXISTS idx_guests_phone ON guests(phone_hash)",
    "CREATE INDEX IF NOT EXISTS idx_guests_email ON guests(email_hash)",
    "CREATE INDEX IF NOT EXISTS idx_errors_log_created ON errors_log(created_at)",
]
