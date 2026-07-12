"""Smoke-тесты загрузки конфигурации (этап 0)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from src.config import (
    AppConfig,
    EnvSettings,
    _load_yaml,
    _project_root,
    get_config,
    get_env_settings,
    reload_config,
)
from src.storage import db as storage_db
from src.storage.db import init_db


def _isolated_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Чистый config: копия example YAML + БД без runtime overrides."""
    yaml_copy = tmp_path / "settings.yaml"
    yaml_copy.write_text(
        Path("config/settings.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setenv("SETTINGS_PATH", str(yaml_copy))
    monkeypatch.setattr("src.config_runtime.load_runtime_overrides", lambda: {})
    db_file = tmp_path / "config_test.db"

    def _patched_db_path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()
    reload_config()


def test_get_config_loads_defaults() -> None:
    """Проверка дефолтов example YAML (без runtime overrides и кэша get_config)."""
    data = _load_yaml(_project_root() / "config" / "settings.example.yaml")
    cfg = AppConfig.model_validate(data)
    assert cfg.property.total_units == 44
    assert cfg.property.timezone == "Europe/Moscow"
    assert cfg.dry_run is True


def test_get_config_scheduler_cron(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    cfg = get_config()
    assert cfg.scheduler.price_snapshot_cron == "0 9 * * *"
    assert cfg.scheduler.daily_summary_cron == "5 9 * * *"
    assert cfg.scheduler.weekly_email_cron == "0 8 * * 1"


def test_get_config_traffic_light_thresholds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    cfg = get_config()
    assert cfg.traffic_light.occupancy_green_min == 70.0
    assert cfg.traffic_light.price_change_red_pct == 10.0


def test_get_config_channels_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    cfg = get_config()
    assert "1apart.ru" in cfg.channels_map.direct
    assert "Островок" in cfg.channels_map.aggregator


def test_get_config_site_prices_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    cfg = get_config()
    assert cfg.site_prices.request_delay_min_sec == 2.0
    assert cfg.site_prices.max_retries == 3
    assert len(cfg.site_prices.category_urls) == 6


def test_get_env_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SETTINGS_PATH", raising=False)
    get_env_settings.cache_clear()
    env = get_env_settings()
    assert isinstance(env, EnvSettings)
    assert env.settings_path == "config/settings.yaml"


def test_config_cached_singleton(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    a = get_config()
    b = get_config()
    assert a is b


def test_reload_config_returns_fresh_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_config(monkeypatch, tmp_path)
    a = get_config()
    b = reload_config()
    assert isinstance(b, AppConfig)
    c = get_config()
    assert c is b
    assert c is not a


def test_max_webhook_url_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(
        "dry_run: true\nmax_bot:\n  webhook_url: ''\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SETTINGS_PATH", str(yaml_path))
    monkeypatch.setenv("MAX_WEBHOOK_URL", "https://example.com/api/max/webhook")
    reload_config()
    cfg = get_config()
    assert cfg.max_bot.webhook_url == "https://example.com/api/max/webhook"


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
