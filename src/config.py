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


class StorageConfig(BaseModel):
    """Настройки SQLite-хранилища."""

    db_path: str = "data/hotel_report.db"
    retention_days: int = 90


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


class MarketNewsConfig(BaseModel):
    """Сбор новостей/трендов рынка для email-отчёта."""

    enabled: bool = True
    max_items: int = 5


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


class MaxBotConfig(BaseModel):
    """Параметры Max Bot API."""

    api_url: str = "https://platform-api2.max.ru"
    chat_id: str = ""
    test_chat_id: str = ""
    max_message_length: int = 4000
    max_retries: int = 3
    backoff_initial_sec: float = 1.0
    backoff_max_sec: float = 60.0


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


class AppConfig(BaseModel):
    """Полная конфигурация приложения из settings.yaml."""

    dry_run: bool = True
    property: PropertyConfig = Field(default_factory=PropertyConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    traffic_light: TrafficLightThresholds = Field(default_factory=TrafficLightThresholds)
    channels_map: ChannelsMap = Field(default_factory=ChannelsMap)
    site_prices: SitePricesConfig = Field(default_factory=SitePricesConfig)
    competitors: list[CompetitorConfig] = Field(default_factory=list)
    market_news: MarketNewsConfig = Field(default_factory=MarketNewsConfig)
    travelline: TravelLineConfig = Field(default_factory=TravelLineConfig)
    max_bot: MaxBotConfig = Field(default_factory=MaxBotConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    sheets: SheetsConfig = Field(default_factory=SheetsConfig)
    web: WebConfig = Field(default_factory=WebConfig)


class EnvSettings(BaseSettings):
    """Секреты и пути из .env."""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    settings_path: str = Field(default="config/settings.yaml", alias="SETTINGS_PATH")
    max_token: str = ""
    google_sa_json_path: str = ""
    tl_api_key: str = ""
    tl_client_id: str = ""
    tl_client_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    admin_password: str = "admin"
    admin_token: str = ""
    secret_key: str = "change-me"


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
    """Загрузить полную конфигурацию: YAML + .env (кэш — один раз на процесс)."""
    env = get_env_settings()
    yaml_path = _project_root() / env.settings_path
    data = _load_yaml(yaml_path)
    return AppConfig(**data)


def get_db_path() -> Path:
    """Абсолютный путь к файлу SQLite."""
    cfg = get_config()
    path = Path(cfg.storage.db_path)
    if not path.is_absolute():
        path = _project_root() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reload_config() -> AppConfig:
    """Сбросить кэш и перечитать конфигурацию."""
    get_env_settings.cache_clear()
    get_config.cache_clear()
    return get_config()
