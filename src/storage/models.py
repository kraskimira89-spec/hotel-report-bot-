"""SQL-схемы и модели записей SQLite."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

SCHEMA_VERSION = 13

TRENDS_RETENTION_DAYS = 180
INSIGHTS_RETENTION_DAYS = 90

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
    """
    CREATE TABLE IF NOT EXISTS competitor_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_name TEXT NOT NULL,
        date TEXT NOT NULL,
        price_from REAL,
        currency TEXT NOT NULL DEFAULT 'RUB',
        source TEXT NOT NULL DEFAULT 'dom',
        screenshot_path TEXT,
        available INTEGER NOT NULL DEFAULT 0,
        category TEXT NOT NULL DEFAULT '',
        check_in TEXT,
        check_out TEXT,
        price_kind TEXT NOT NULL DEFAULT 'dynamic',
        booking_engine TEXT,
        is_breakfast_included INTEGER,
        cancellation_policy TEXT,
        captured_at TEXT,
        raw_url TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        category TEXT NOT NULL,
        region TEXT NOT NULL,
        source_url TEXT NOT NULL,
        published_at TEXT,
        takeaway TEXT NOT NULL,
        is_idea_of_week INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        recommendations TEXT NOT NULL DEFAULT '[]',
        severity TEXT NOT NULL DEFAULT 'info',
        source TEXT NOT NULL DEFAULT 'travelline',
        period TEXT NOT NULL DEFAULT '',
        detail_payload TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mail_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL,
        mailbox TEXT NOT NULL,
        folder TEXT NOT NULL DEFAULT 'INBOX',
        from_addr TEXT NOT NULL DEFAULT '',
        subject TEXT NOT NULL DEFAULT '',
        received_at TEXT,
        body_excerpt TEXT NOT NULL DEFAULT '',
        mail_class TEXT NOT NULL DEFAULT 'other',
        for_reviews INTEGER NOT NULL DEFAULT 0,
        parsed_json TEXT NOT NULL DEFAULT '{}',
        headers_hash TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(message_id, mailbox)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        calculated_at TEXT NOT NULL,
        run_date TEXT NOT NULL,
        horizon_days INTEGER NOT NULL,
        model_version TEXT NOT NULL DEFAULT 'v1',
        data_quality TEXT NOT NULL DEFAULT 'unknown',
        status TEXT NOT NULL DEFAULT 'completed',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(run_date, horizon_days, model_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        forecast_date TEXT NOT NULL,
        room_type TEXT NOT NULL DEFAULT '',
        scenario TEXT NOT NULL DEFAULT 'base',
        occupancy_pct REAL,
        adr REAL,
        revpar REAL,
        revenue REAL,
        sold_unit_nights REAL,
        available_unit_nights INTEGER,
        lower_bound REAL,
        upper_bound REAL,
        confidence TEXT NOT NULL DEFAULT 'medium',
        factors_json TEXT NOT NULL DEFAULT '{}',
        actual_occupancy_pct REAL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (run_id) REFERENCES forecast_runs(id) ON DELETE CASCADE,
        UNIQUE(run_id, forecast_date, room_type, scenario)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forecast_id INTEGER,
        room_type TEXT NOT NULL,
        target_date TEXT NOT NULL,
        current_price REAL,
        recommended_price_min REAL,
        recommended_price_max REAL,
        recommendation_type TEXT NOT NULL DEFAULT 'hold',
        reason TEXT NOT NULL DEFAULT '',
        confidence TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'new',
        decided_at TEXT,
        horizon_days INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (forecast_id) REFERENCES forecast_daily(id) ON DELETE SET NULL
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
    "CREATE INDEX IF NOT EXISTS idx_competitor_prices_name_date "
    "ON competitor_prices(competitor_name, date)",
    "CREATE INDEX IF NOT EXISTS idx_competitor_prices_date ON competitor_prices(date)",
    "CREATE INDEX IF NOT EXISTS idx_trends_region ON trends(region)",
    "CREATE INDEX IF NOT EXISTS idx_trends_category ON trends(category)",
    "CREATE INDEX IF NOT EXISTS idx_trends_published ON trends(published_at)",
    "CREATE INDEX IF NOT EXISTS idx_insights_topic ON insights(topic)",
    "CREATE INDEX IF NOT EXISTS idx_insights_severity ON insights(severity)",
    "CREATE INDEX IF NOT EXISTS idx_insights_updated ON insights(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_mail_messages_received ON mail_messages(received_at)",
    "CREATE INDEX IF NOT EXISTS idx_mail_messages_class ON mail_messages(mail_class)",
    "CREATE INDEX IF NOT EXISTS idx_mail_messages_for_reviews ON mail_messages(for_reviews)",
    "CREATE INDEX IF NOT EXISTS idx_forecast_daily_run ON forecast_daily(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_forecast_daily_date ON forecast_daily(forecast_date)",
    "CREATE INDEX IF NOT EXISTS idx_price_reco_status ON price_recommendations(status)",
    "CREATE INDEX IF NOT EXISTS idx_price_reco_date ON price_recommendations(target_date)",
    "CREATE INDEX IF NOT EXISTS idx_price_reco_horizon ON price_recommendations(horizon_days)",
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

MIGRATIONS_V4: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS competitor_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competitor_name TEXT NOT NULL,
        date TEXT NOT NULL,
        price_from REAL,
        currency TEXT NOT NULL DEFAULT 'RUB',
        source TEXT NOT NULL DEFAULT 'dom',
        screenshot_path TEXT,
        available INTEGER NOT NULL DEFAULT 0,
        category TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        category TEXT NOT NULL,
        region TEXT NOT NULL,
        source_url TEXT NOT NULL,
        published_at TEXT,
        takeaway TEXT NOT NULL,
        is_idea_of_week INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_competitor_prices_name_date "
    "ON competitor_prices(competitor_name, date)",
    "CREATE INDEX IF NOT EXISTS idx_competitor_prices_date ON competitor_prices(date)",
    "CREATE INDEX IF NOT EXISTS idx_trends_region ON trends(region)",
    "CREATE INDEX IF NOT EXISTS idx_trends_category ON trends(category)",
    "CREATE INDEX IF NOT EXISTS idx_trends_published ON trends(published_at)",
]

MIGRATIONS_V5: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        recommendations TEXT NOT NULL DEFAULT '[]',
        severity TEXT NOT NULL DEFAULT 'info',
        source TEXT NOT NULL DEFAULT 'travelline',
        period TEXT NOT NULL DEFAULT '',
        detail_payload TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_insights_topic ON insights(topic)",
    "CREATE INDEX IF NOT EXISTS idx_insights_severity ON insights(severity)",
    "CREATE INDEX IF NOT EXISTS idx_insights_updated ON insights(updated_at)",
]

MIGRATIONS_V6: list[str] = [
    "ALTER TABLE competitor_prices ADD COLUMN category TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_competitor_prices_name_cat_date "
    "ON competitor_prices(competitor_name, category, date)",
]

FORECAST_RETENTION_DAYS = 730

MIGRATIONS_V7: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS mail_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL,
        mailbox TEXT NOT NULL,
        folder TEXT NOT NULL DEFAULT 'INBOX',
        from_addr TEXT NOT NULL DEFAULT '',
        subject TEXT NOT NULL DEFAULT '',
        received_at TEXT,
        body_excerpt TEXT NOT NULL DEFAULT '',
        mail_class TEXT NOT NULL DEFAULT 'other',
        for_reviews INTEGER NOT NULL DEFAULT 0,
        parsed_json TEXT NOT NULL DEFAULT '{}',
        headers_hash TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(message_id, mailbox)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mail_messages_received ON mail_messages(received_at)",
    "CREATE INDEX IF NOT EXISTS idx_mail_messages_class ON mail_messages(mail_class)",
    "CREATE INDEX IF NOT EXISTS idx_mail_messages_for_reviews "
    "ON mail_messages(for_reviews)",
]

MIGRATIONS_V8: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS forecast_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        calculated_at TEXT NOT NULL,
        run_date TEXT NOT NULL,
        horizon_days INTEGER NOT NULL,
        model_version TEXT NOT NULL DEFAULT 'v1',
        data_quality TEXT NOT NULL DEFAULT 'unknown',
        status TEXT NOT NULL DEFAULT 'completed',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(run_date, horizon_days, model_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS forecast_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        forecast_date TEXT NOT NULL,
        room_type TEXT NOT NULL DEFAULT '',
        scenario TEXT NOT NULL DEFAULT 'base',
        occupancy_pct REAL,
        adr REAL,
        revpar REAL,
        revenue REAL,
        sold_unit_nights REAL,
        available_unit_nights INTEGER,
        lower_bound REAL,
        upper_bound REAL,
        confidence TEXT NOT NULL DEFAULT 'medium',
        factors_json TEXT NOT NULL DEFAULT '{}',
        actual_occupancy_pct REAL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (run_id) REFERENCES forecast_runs(id) ON DELETE CASCADE,
        UNIQUE(run_id, forecast_date, room_type, scenario)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forecast_id INTEGER,
        room_type TEXT NOT NULL,
        target_date TEXT NOT NULL,
        current_price REAL,
        recommended_price_min REAL,
        recommended_price_max REAL,
        recommendation_type TEXT NOT NULL DEFAULT 'hold',
        reason TEXT NOT NULL DEFAULT '',
        confidence TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'new',
        decided_at TEXT,
        horizon_days INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (forecast_id) REFERENCES forecast_daily(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_forecast_daily_run ON forecast_daily(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_forecast_daily_date ON forecast_daily(forecast_date)",
    "CREATE INDEX IF NOT EXISTS idx_price_reco_status ON price_recommendations(status)",
    "CREATE INDEX IF NOT EXISTS idx_price_reco_date ON price_recommendations(target_date)",
]

MIGRATIONS_V9: list[str] = [
    "ALTER TABLE price_recommendations ADD COLUMN horizon_days INTEGER",
    "CREATE INDEX IF NOT EXISTS idx_price_reco_horizon ON price_recommendations(horizon_days)",
]

MIGRATIONS_V10: list[str] = [
    "ALTER TABLE competitor_prices ADD COLUMN check_in TEXT",
    "ALTER TABLE competitor_prices ADD COLUMN check_out TEXT",
    "ALTER TABLE competitor_prices ADD COLUMN price_kind TEXT NOT NULL DEFAULT 'dynamic'",
    "ALTER TABLE competitor_prices ADD COLUMN booking_engine TEXT",
    "ALTER TABLE competitor_prices ADD COLUMN is_breakfast_included INTEGER",
    "ALTER TABLE competitor_prices ADD COLUMN cancellation_policy TEXT",
    "ALTER TABLE competitor_prices ADD COLUMN captured_at TEXT",
    "ALTER TABLE competitor_prices ADD COLUMN raw_url TEXT",
    "ALTER TABLE competitor_prices ADD COLUMN error_message TEXT",
    "CREATE INDEX IF NOT EXISTS idx_competitor_prices_kind "
    "ON competitor_prices(competitor_name, price_kind, date)",
]

MIGRATIONS_V11: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS city_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'other',
        start_at TEXT NOT NULL,
        end_at TEXT,
        city TEXT NOT NULL DEFAULT 'Томск',
        venue_name TEXT,
        venue_address TEXT,
        estimated_capacity INTEGER,
        audience_scope TEXT NOT NULL DEFAULT 'unknown',
        source_url TEXT,
        source_name TEXT,
        source_priority INTEGER NOT NULL DEFAULT 3,
        status TEXT NOT NULL DEFAULT 'candidate',
        impact_score REAL NOT NULL DEFAULT 0,
        confidence TEXT NOT NULL DEFAULT 'low',
        expected_guest_nights_min INTEGER,
        expected_guest_nights_max INTEGER,
        forecast_coefficient REAL NOT NULL DEFAULT 0.05,
        description TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        source_event_id TEXT,
        captured_at TEXT NOT NULL DEFAULT (datetime('now')),
        raw_title TEXT,
        raw_date TEXT,
        raw_venue TEXT,
        is_primary INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (event_id) REFERENCES city_events(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_review_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        comment TEXT,
        actor TEXT NOT NULL DEFAULT 'admin',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (event_id) REFERENCES city_events(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_source_state (
        source_name TEXT PRIMARY KEY,
        last_success_at TEXT,
        etag TEXT,
        last_modified TEXT,
        last_error TEXT,
        last_error_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_city_events_dates ON city_events(start_at, end_at)",
    "CREATE INDEX IF NOT EXISTS idx_city_events_status ON city_events(status, impact_score)",
    "CREATE INDEX IF NOT EXISTS idx_event_sources_event ON event_sources(event_id)",
]

MIGRATIONS_V12: list[str] = [
    "ALTER TABLE city_events ADD COLUMN is_online INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE city_events ADD COLUMN registration_required INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE city_events ADD COLUMN expected_attendance INTEGER",
    "ALTER TABLE city_events ADD COLUMN attendance_source TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE city_events ADD COLUMN tourism_relevance TEXT NOT NULL DEFAULT 'none'",
    "ALTER TABLE city_events ADD COLUMN overnight_likelihood REAL NOT NULL DEFAULT 0.1",
    "ALTER TABLE city_events ADD COLUMN is_public_holiday INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE city_events ADD COLUMN location_confirmed INTEGER NOT NULL DEFAULT 0",
]

MIGRATIONS_V13: list[str] = [
    "ALTER TABLE city_events ADD COLUMN category_manual INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE city_events ADD COLUMN category_source TEXT NOT NULL DEFAULT 'rules'",
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


class CompetitorPriceRecord(BaseModel):
    """Снимок цены конкурента.

    ``category`` пустой — агрегат «цена от» по объекту;
    иначе — имя объекта/категории конкурента.
    """

    competitor_name: str
    date: date
    price_from: float | None = None
    currency: str = "RUB"
    source: str = "dom"
    screenshot_path: str | None = None
    available: bool = False
    category: str = ""
    check_in: date | None = None
    check_out: date | None = None
    price_kind: str = "dynamic"  # dynamic | public_from | cached
    booking_engine: str | None = None
    is_breakfast_included: bool | None = None
    cancellation_policy: str | None = None
    captured_at: datetime | None = None
    raw_url: str | None = None
    error_message: str | None = None
    id: int | None = None


class TrendRecord(BaseModel):
    """Тренд рынка апарт-отелей."""

    title: str
    summary: str
    category: str
    region: str
    source_url: str
    takeaway: str
    published_at: date | None = None
    is_idea_of_week: bool = False
    id: int | None = None


class InsightRecord(BaseModel):
    """Кешированная карточка ИИ-аналитики."""

    topic: str
    title: str
    summary: str
    recommendations: list[str] = []
    severity: str = "info"
    source: str = "travelline"
    period: str = ""
    detail_payload: dict = {}
    updated_at: datetime | None = None
    id: int | None = None


class MailMessageRecord(BaseModel):
    """Письмо из IMAP (Issue #13)."""

    message_id: str
    mailbox: str
    folder: str = "INBOX"
    from_addr: str = ""
    subject: str = ""
    received_at: datetime | None = None
    body_excerpt: str = ""
    mail_class: str = "other"
    for_reviews: bool = False
    parsed_json: dict = {}
    headers_hash: str = ""
    created_at: datetime | None = None
    id: int | None = None


class ForecastRunRecord(BaseModel):
    """Запуск расчёта прогноза."""

    calculated_at: datetime
    run_date: date | None = None
    horizon_days: int
    model_version: str = "v1"
    data_quality: str = "unknown"
    status: str = "completed"
    id: int | None = None


class ForecastDailyRecord(BaseModel):
    """Прогноз на дату и тип номера."""

    run_id: int
    forecast_date: date
    room_type: str = ""
    scenario: str = "base"
    occupancy_pct: float | None = None
    adr: float | None = None
    revpar: float | None = None
    revenue: float | None = None
    sold_unit_nights: float | None = None
    available_unit_nights: int | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    confidence: str = "medium"
    factors_json: dict = {}
    actual_occupancy_pct: float | None = None
    id: int | None = None


class PriceRecommendationRecord(BaseModel):
    """Рекомендация по цене."""

    room_type: str
    target_date: date
    current_price: float | None = None
    recommended_price_min: float | None = None
    recommended_price_max: float | None = None
    recommendation_type: str = "hold"
    reason: str = ""
    confidence: str = "medium"
    status: str = "new"
    decided_at: datetime | None = None
    forecast_id: int | None = None
    horizon_days: int | None = None
    id: int | None = None


class CityEventRecord(BaseModel):
    """Событие города, влияющее на спрос."""

    title: str
    normalized_title: str = ""
    category: str = "other"
    start_at: date
    end_at: date | None = None
    city: str = "Томск"
    venue_name: str | None = None
    venue_address: str | None = None
    estimated_capacity: int | None = None
    audience_scope: str = "unknown"
    source_url: str | None = None
    source_name: str | None = None
    source_priority: int = 3
    status: str = "candidate"
    impact_score: float = 0.0
    confidence: str = "low"
    expected_guest_nights_min: int | None = None
    expected_guest_nights_max: int | None = None
    forecast_coefficient: float = 0.05
    description: str | None = None
    is_online: bool = False
    registration_required: bool = False
    expected_attendance: int | None = None
    attendance_source: str = "unknown"
    tourism_relevance: str = "none"
    overnight_likelihood: float = 0.1
    is_public_holiday: bool = False
    location_confirmed: bool = False
    category_manual: bool = False
    category_source: str = "rules"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    id: int | None = None


class EventSourceRecord(BaseModel):
    """Ссылка на источник, где найдено событие."""

    event_id: int
    source_name: str
    source_url: str
    source_event_id: str | None = None
    captured_at: datetime | None = None
    raw_title: str | None = None
    raw_date: str | None = None
    raw_venue: str | None = None
    is_primary: bool = False
    id: int | None = None


class EventReviewLogRecord(BaseModel):
    """Журнал ручных действий по событию."""

    event_id: int
    action: str
    old_value: str | None = None
    new_value: str | None = None
    comment: str | None = None
    actor: str = "admin"
    created_at: datetime | None = None
    id: int | None = None


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
