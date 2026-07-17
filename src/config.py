"""Загрузка конфигурации из settings.yaml и переменных окружения (.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _env_file() -> str | None:
    """Путь к .env относительно корня проекта (не CWD)."""
    path = _project_root() / "config" / ".env"
    return str(path) if path.exists() else None


class PropertyConfig(BaseModel):
    """Параметры объекта размещения."""

    total_units: int = 44
    categories: int = 6
    timezone: str = "Europe/Moscow"


class SchedulerConfig(BaseModel):
    """Расписание задач (cron, Europe/Moscow)."""

    price_snapshot_cron: str = "0 9 * * *"
    daily_summary_cron: str = "5 9 * * *"
    weekly_email_cron: str = "0 8 * * 1"
    weekly_trends_cron: str = "0 7 * * 1"
    competitor_prices_cron: str = "30 9 * * 1"  # пн 09:30 — автосбор цен (Playwright)
    mail_inbox_cron: str = "45 9 * * *"  # ежедневно после snapshot / аналитики


class DeployConfig(BaseModel):
    """Автодеплой на VPS после задач планировщика / агента."""

    enabled: bool = False
    after_jobs: bool = True
    min_interval_minutes: int = 15
    ssh_host: str = ""
    ssh_user: str = "root"
    app_dir: str = "/opt/1apart/hotel-report-bot"
    compose_file: str = "docker/docker-compose.yml"
    job_ids: list[str] = Field(
        default_factory=lambda: [
            "price_snapshot",
            "daily_summary",
            "weekly_email",
            "weekly_trends",
            "competitor_prices",
        ]
    )


class StorageConfig(BaseModel):
    """Настройки SQLite-хранилища."""

    db_path: str = "data/hotel_report.db"
    retention_days: int = 730


class TrafficLightThresholds(BaseModel):
    """Пороги светофора для ежедневной сводки."""

    occupancy_green_min: float = 70.0
    occupancy_yellow_min: float = 50.0
    price_change_yellow_pct: float = 5.0
    price_change_red_pct: float = 10.0
    new_bookings_green_min: int = 3
    new_bookings_yellow_min: int = 1


class ChannelsMap(BaseModel):
    """Классификация каналов: direct / aggregator."""

    direct: list[str] = Field(default_factory=list)
    aggregator: list[str] = Field(default_factory=list)


class SitePricesSelectors(BaseModel):
    """CSS-селекторы и паттерн для парсинга цен."""

    data_price: str = "[data-price]"
    price_value: str = ".price-value"
    price_from_regex: str = r"от\s*([\d\s\u00a0]+)\s*(?:руб|₽|Р|р\.?)"


class SitePricesConfig(BaseModel):
    """Анти-блок и URL для сбора статических цен с 1apart.ru."""

    base_url: str = "https://1apart.ru"
    category_urls: list[str] = Field(default_factory=list)
    request_delay_min_sec: float = 2.0
    request_delay_max_sec: float = 3.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    backoff_initial_sec: float = 5.0
    backoff_max_sec: float = 60.0
    max_retries: int = 3
    selectors: SitePricesSelectors = Field(default_factory=SitePricesSelectors)
    robots_disallow_paths: list[str] = Field(default_factory=lambda: ["/manager/"])
    snapshot_cache_path: str = "data/last_price_snapshots.json"


class CompetitorConfig(BaseModel):
    """Конкурент для сбора цен в еженедельный email-отчёт (справочно)."""

    name: str
    type: str = "direct"  # direct | indirect
    url: str
    parser: str = "widget"  # static | tl_widget | wubook_widget | widget(fallback)
    selectors: dict[str, str] = Field(default_factory=dict)
    # Страница с iframe booking2 (если отличается от url)
    booking_url: str | None = None
    # Публичный каталог категорий (fallback public_from)
    catalog_url: str | None = None


class MarketNewsConfig(BaseModel):
    """Сбор новостей/трендов рынка для email-отчёта и раздела «Тренды»."""

    enabled: bool = True
    max_items: int = 5
    sources: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=lambda: ["ru", "world"])
    # Основная категория для «Идеи недели» (обратная совместимость).
    idea_category_priority: str = "Технологии и ИИ"
    # Резервный список приоритетов: если в первой категории нет
    # трендов — берётся следующая по списку, и т.д. Пустой — используется только
    # idea_category_priority. Финальный фолбэк (любой свежий тренд) — в коде.
    idea_category_priorities: list[str] = Field(
        default_factory=lambda: [
            "Технологии и ИИ",
            "Динамическое ценообразование / RMS",
            "Прямые бронирования",
            "Бесконтактный сервис",
            "Длительное проживание / корпоративные гости",
            "Гость-опыт и допуслуги",
            "Рынок и регулирование",
        ]
    )

    @property
    def idea_priority_order(self) -> list[str]:
        """Итоговый порядок категорий для выбора «Идеи недели».

        Начинается с idea_category_priority, затем добавляются
        idea_category_priorities (без дубликатов, с сохранением порядка).
        """
        order: list[str] = []
        for cat in [self.idea_category_priority, *self.idea_category_priorities]:
            cat = (cat or "").strip()
            if cat and cat not in order:
                order.append(cat)
        return order


class TravelLineConfig(BaseModel):
    """Параметры TravelLine API."""

    partner_base_url: str = "https://partner.tlintegration.com"
    auth_url: str = "https://partner.tlintegration.com/auth/token"
    webpms_base_url: str = "https://partner.tlintegration.com/api/webpms"
    reservation_base_url: str = "https://partner.tlintegration.com/api/read-reservation"
    search_base_url: str = "https://partner.tlintegration.com/api/search"
    property_id: str = ""
    max_date_window_days: int = 31
    max_retries: int = 3
    backoff_initial_sec: float = 1.0
    backoff_max_sec: float = 60.0
    sheets_reconcile_threshold_pct: float = 10.0
    reservation_page_size: int = 100
    # WebPMS roomTypeId → русская подпись категории
    room_type_id_map: dict[str, str] = Field(default_factory=dict)


class MaxBotConfig(BaseModel):
    """Параметры Max Bot API (https://dev.max.ru/docs-api)."""

    api_url: str = "https://platform-api2.max.ru"
    chat_id: str = ""
    test_chat_id: str = ""
    max_message_length: int = 4000
    max_retries: int = 3
    backoff_initial_sec: float = 1.0
    backoff_max_sec: float = 60.0
    webhook_url: str = ""
    webhook_update_types: list[str] = Field(
        default_factory=lambda: ["bot_started", "message_created", "bot_added"]
    )


class EmailConfig(BaseModel):
    """Параметры email-отчёта."""

    from_address: str = ""
    to_addresses: list[str] = Field(default_factory=list)
    test_addresses: list[str] = Field(default_factory=list)
    subject_prefix: str = "[1apart] Еженедельный отчёт"


class SheetsConfig(BaseModel):
    """Параметры Google Sheets."""

    spreadsheet_id: str = ""
    spreadsheet_title: str = "Апарт отель для Сергея"
    occupancy_sheet: str = "Заселяемость"
    occupancy_sheet_gid: int = 343939684
    bookings_sheet: str = "Брони статистика"
    bookings_sheet_gid: int = 1469944608


class WebConfig(BaseModel):
    """Параметры веб-админки."""

    host: str = "0.0.0.0"
    port: int = 8000
    admin_username: str = "admin"


class AnalyticsConfig(BaseModel):
    """Параметры ИИ-ленты аналитики."""

    enabled: bool = True
    period_days: int = 14
    refresh_cron: str = "15 9 * * *"
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"


class ImapMailboxConfig(BaseModel):
    """Один IMAP-ящик (Яндекс / Gmail)."""

    enabled: bool = False
    host: str = ""
    port: int = 993
    use_ssl: bool = True
    folders: list[str] = Field(default_factory=lambda: ["INBOX"])
    # Ключ секретов в EnvSettings: yandex | gmail
    account: str = "yandex"


class MailInboxConfig(BaseModel):
    """Чтение входящей почты (Issue #13)."""

    enabled: bool = False
    lookback_days: int = 7
    report_senders: list[str] = Field(
        default_factory=lambda: [
            "noreply@travelline.ru",
            "reports@travelline.ru",
            "@travelline.ru",
        ]
    )
    mailboxes: list[ImapMailboxConfig] = Field(default_factory=list)


class ForecastManualEvent(BaseModel):
    """Ручное событие, влияющее на спрос."""

    name: str
    date_from: str
    date_to: str
    impact_pct: float = 5.0


class ForecastConfig(BaseModel):
    """Раздел «Прогноз»: горизонты, пороги, рекомендации по ценам."""

    enabled: bool = True
    horizons: list[int] = Field(default_factory=lambda: [7, 14, 30, 180])
    min_history_days: int = 365
    max_mae_occupancy: float = 15.0
    max_mape_revenue: float = 20.0
    max_price_change_pct: float = 15.0
    min_price: float = 2000.0
    max_price: float = 25000.0
    use_competitors: bool = True
    refresh_cron: str = "30 9 * * *"
    manual_events: list[ForecastManualEvent] = Field(default_factory=list)


class AppConfig(BaseModel):
    """Полная конфигурация приложения из settings.yaml."""

    dry_run: bool = True
    property: PropertyConfig = Field(default_factory=PropertyConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    deploy: DeployConfig = Field(default_factory=DeployConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    traffic_light: TrafficLightThresholds = Field(default_factory=TrafficLightThresholds)
    channels_map: ChannelsMap = Field(default_factory=ChannelsMap)
    site_prices: SitePricesConfig = Field(default_factory=SitePricesConfig)
    competitors: list[CompetitorConfig] = Field(default_factory=list)
    competitor_category_map: dict[str, str] = Field(default_factory=dict)
    category_slug_map: dict[str, str] = Field(default_factory=dict)
    room_type_aliases: dict[str, str] = Field(default_factory=dict)
    market_news: MarketNewsConfig = Field(default_factory=MarketNewsConfig)
    travelline: TravelLineConfig = Field(default_factory=TravelLineConfig)
    max_bot: MaxBotConfig = Field(default_factory=MaxBotConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    sheets: SheetsConfig = Field(default_factory=SheetsConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    mail_inbox: MailInboxConfig = Field(default_factory=MailInboxConfig)
    forecast: ForecastConfig = Field(default_factory=ForecastConfig)


class EnvSettings(BaseSettings):
    """Секреты и пути из .env."""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    settings_path: str = Field(default="config/settings.yaml", alias="SETTINGS_PATH")
    max_token: str = ""
    max_webhook_secret: str = ""
    max_webhook_url: str = ""
    google_sa_json_path: str = ""
    tl_api_key: str = ""
    tl_client_id: str = ""
    tl_client_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    admin_password: str = "admin"
    admin_token: str = ""
    secret_key: str = ""
    web_force_https: bool = False
    deploy_enabled: bool = Field(default=False, alias="DEPLOY_ENABLED")
    vps_host: str = Field(default="", alias="VPS_HOST")
    vps_user: str = Field(default="root", alias="VPS_USER")
    vps_app_dir: str = Field(default="/opt/1apart/hotel-report-bot", alias="VPS_APP_DIR")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    # YandexGPT (Issue #9) — предпочтительнее OPENAI_* при заполнении
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_folder_id: str = Field(default="", alias="LLM_FOLDER_ID")
    llm_base_url: str = Field(
        default="https://ai.api.cloud.yandex.net/v1",
        alias="LLM_BASE_URL",
    )
    llm_model: str = Field(default="", alias="LLM_MODEL")
    # IMAP входящая почта (Issue #13)
    imap_yandex_user: str = Field(default="", alias="IMAP_YANDEX_USER")
    imap_yandex_password: str = Field(default="", alias="IMAP_YANDEX_PASSWORD")
    imap_gmail_user: str = Field(default="", alias="IMAP_GMAIL_USER")
    imap_gmail_password: str = Field(default="", alias="IMAP_GMAIL_PASSWORD")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        example = path.parent / "settings.example.yaml"
        if example.exists():
            path = example
        else:
            return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def get_env_settings() -> EnvSettings:
    """Загрузить переменные окружения (кэшируется)."""
    return EnvSettings()


@lru_cache
def get_config() -> AppConfig:
    """Загрузить полную конфигурацию: YAML + runtime overrides (кэш)."""
    from src.config_runtime import build_config_from_sources

    return build_config_from_sources()


def get_db_path() -> Path:
    """Абсолютный путь к файлу SQLite (без get_config — избегаем рекурсии)."""
    env = get_env_settings()
    yaml_path = _project_root() / env.settings_path
    data = _load_yaml(yaml_path)
    storage = data.get("storage") or {}
    db_rel = storage.get("db_path", "data/hotel_report.db")
    path = Path(db_rel)
    if not path.is_absolute():
        path = _project_root() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reload_config() -> AppConfig:
    """Сбросить кэш и перечитать конфигурацию."""
    get_env_settings.cache_clear()
    get_config.cache_clear()
    return get_config()
