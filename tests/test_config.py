"""Smoke-тесты загрузки конфигурации (этап 0)."""

import importlib

import pytest

from src.config import (
    AppConfig,
    EnvSettings,
    get_config,
    get_env_settings,
    reload_config,
)


def test_get_config_loads_defaults() -> None:
    cfg = get_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.property.total_units == 44
    assert cfg.property.timezone == "Europe/Moscow"
    assert cfg.dry_run is True


def test_get_config_scheduler_cron() -> None:
    cfg = get_config()
    assert cfg.scheduler.price_snapshot_cron == "0 9 * * *"
    assert cfg.scheduler.daily_summary_cron == "5 9 * * *"
    assert cfg.scheduler.weekly_email_cron == "0 8 * * 1"


def test_get_config_traffic_light_thresholds() -> None:
    cfg = get_config()
    assert cfg.traffic_light.occupancy_green_min == 70.0
    assert cfg.traffic_light.price_change_red_pct == 10.0


def test_get_config_channels_map() -> None:
    cfg = get_config()
    assert "1apart.ru" in cfg.channels_map.direct
    assert "Островок" in cfg.channels_map.aggregator


def test_get_config_site_prices_limits() -> None:
    cfg = get_config()
    assert cfg.site_prices.request_delay_min_sec == 2.0
    assert cfg.site_prices.max_retries == 3
    assert len(cfg.site_prices.category_urls) == 6


def test_get_env_settings() -> None:
    env = get_env_settings()
    assert isinstance(env, EnvSettings)
    assert env.settings_path == "config/settings.yaml"


def test_config_cached_singleton() -> None:
    reload_config()
    a = get_config()
    b = get_config()
    assert a is b


def test_reload_config_returns_fresh_instance() -> None:
    a = get_config()
    b = reload_config()
    assert isinstance(b, AppConfig)
    c = get_config()
    assert c is b
    assert c is not a


@pytest.mark.parametrize(
    "package",
    [
        "gspread",
        "google.auth",
        "httpx",
        "bs4",
        "lxml",
        "fastapi",
        "uvicorn",
        "jinja2",
        "apscheduler",
        "pydantic_settings",
        "dotenv",
        "yaml",
        "pytest",
        "ruff",
    ],
)
def test_requirements_importable(package: str) -> None:
    importlib.import_module(package)
