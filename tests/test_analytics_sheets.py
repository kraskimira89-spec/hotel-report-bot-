"""Тесты подмешивания Google Sheets в контекст аналитики."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.analytics import ai_insights
from src.analytics.ai_insights import _collect_context, _occ_day_pct
from src.config import StorageConfig, reload_config
from src.data_sources.sheets import OccupancyDay, RoomTypeOccupancy
from src.storage import db as storage_db
from src.storage.db import init_db


@pytest.fixture
def empty_metrics_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "empty.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")
    reload_config()

    def _path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _path)
    monkeypatch.setattr("src.config.get_db_path", _path)
    init_db()
    cfg = reload_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    return db_file


def test_occ_day_pct_prefers_travelline() -> None:
    day = OccupancyDay(
        date=date(2026, 7, 10),
        total_pct=40.0,
        travelline_pct=55.5,
        by_type=[RoomTypeOccupancy(room_type="1к", occupancy_pct=10.0)],
    )
    assert _occ_day_pct(day) == 55.5


def test_occ_day_pct_skips_empty_zero_day() -> None:
    day = OccupancyDay(
        date=date(2026, 7, 10),
        total_pct=0.0,
        travelline_pct=None,
        by_type=[RoomTypeOccupancy(room_type="1к", occupancy_pct=None)],
    )
    assert _occ_day_pct(day) is None


def test_collect_context_uses_sheets_when_sqlite_empty(
    empty_metrics_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = empty_metrics_db

    def fake_overlay(
        start: date,
        end: date,
        prev_start: date,
        prev_end: date,
    ) -> dict:
        _ = (start, end, prev_start, prev_end)
        return {
            "occupancy_series": [
                {"date": "2026-07-10", "occupancy_pct": 62.0},
                {"date": "2026-07-11", "occupancy_pct": 58.0},
            ],
            "occupancy_current": 60.0,
            "occupancy_previous": 70.0,
            "by_type": [{"room_type": "1-комн.", "occupancy_pct": 65.0, "units": 10}],
            "channels": {
                "direct_pct": 40.0,
                "aggregator_pct": 60.0,
                "total": 20,
                "source": "sheets",
            },
            "available": True,
        }

    monkeypatch.setattr(ai_insights, "_collect_sheets_overlay", fake_overlay)
    ctx = _collect_context(period_days=14)
    assert ctx["occupancy"]["source"] == "sheets"
    assert ctx["occupancy"]["current"] == 60.0
    assert len(ctx["occupancy"]["series"]) == 2
    assert ctx["channels"]["source"] == "sheets"
    assert ctx["channels"]["total"] == 20
    assert ctx["data_sources"]["sheets_available"] is True
