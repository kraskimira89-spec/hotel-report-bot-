"""Тесты runtime-конфигурации."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import StorageConfig, get_config, reload_config
from src.config_runtime import deep_merge, load_runtime_overrides, save_runtime_overrides
from src.storage import db as storage_db
from src.storage.db import get_runtime_setting, init_db


@pytest.fixture
def runtime_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _patched_db_path() -> Path:
        return db_file

    cfg = reload_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()
    reload_config()
    return db_file


def test_deep_merge_nested() -> None:
    base = {"traffic_light": {"occupancy_green_min": 70}, "dry_run": True}
    override = {"traffic_light": {"occupancy_green_min": 75}}
    merged = deep_merge(base, override)
    assert merged["dry_run"] is True
    assert merged["traffic_light"]["occupancy_green_min"] == 75


def test_save_runtime_overrides_applied(runtime_db: Path) -> None:
    save_runtime_overrides({"dry_run": False})
    reload_config()
    cfg = get_config()
    assert cfg.dry_run is False
    assert get_runtime_setting("config_overrides") is not None
    assert load_runtime_overrides()["dry_run"] is False
