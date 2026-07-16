"""Тесты деградации при сбоях источников."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.config import AppConfig, StorageConfig, get_config
from src.notifiers.email_sender import WeeklyReportData, send_weekly_report
from src.notifiers.max_bot import DailySummaryData, RoomStatusSummary, send_daily_summary
from src.storage import db as storage_db
from src.storage.db import init_db


def _prepare_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _patched_db_path() -> Path:
        return db_file

    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()


def test_daily_summary_critical_sheets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _prepare_db(tmp_path, monkeypatch)

    called: dict[str, str] = {}

    def _fake_incident(title: str, details: str, **_: object) -> None:
        called["title"] = title
        called["details"] = details

    monkeypatch.setattr("src.notifiers.incidents.send_incident", _fake_incident)

    data = DailySummaryData(
        report_date=date(2026, 7, 7),
        room_types=[RoomStatusSummary(label="1room", free=1, occupied=1, booked=1)],
        totals=RoomStatusSummary(label="Итого", free=1, occupied=1, booked=1),
        warnings=["ГуглТабл недоступен: лист «Заселяемость»."],
        critical_error=True,
    )

    result = send_daily_summary(
        report_date=date(2026, 7, 7),
        summary_data=data,
        config=AppConfig(dry_run=True),
    )
    assert result["status"] == "skipped"
    assert "Критическая ошибка" in called["title"]


def test_weekly_report_critical_sheets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _prepare_db(tmp_path, monkeypatch)

    called: dict[str, str] = {}

    def _fake_incident(title: str, details: str, **_: object) -> None:
        called["title"] = title
        called["details"] = details

    monkeypatch.setattr("src.notifiers.incidents.send_incident", _fake_incident)

    report_data = WeeklyReportData(
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 7),
        occupancy_by_type=[],
        warnings=["ГуглТабл недоступен: лист «Заселяемость»."],
        critical_error=True,
    )

    result = send_weekly_report(
        report_date=date(2026, 7, 7),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 7),
        report_data=report_data,
        config=AppConfig(dry_run=True),
    )
    assert result["status"] == "skipped"
    assert "Критическая ошибка" in called["title"]
