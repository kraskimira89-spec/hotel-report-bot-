"""Тесты сверки сводки с TravelLine."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.data_sources.summary_reconcile import (
    _compare_float,
    _compare_int,
    build_summary_travelline_reconcile,
    prune_reconcile_reports,
    reconcile_output_dir,
    run_summary_travelline_reconcile,
    save_reconcile_report,
)
from src.data_sources.travelline import StayOccupancyResult
from src.notifiers.max_bot import DailySummaryData
from src.storage import db as storage_db
from src.storage.db import init_db


@pytest.fixture
def reconcile_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_file = tmp_path / "reconcile_test.db"
    out_dir = tmp_path / "reconcile"

    def _patched_db_path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    monkeypatch.setattr(
        "src.data_sources.summary_reconcile.reconcile_output_dir",
        lambda config=None: out_dir,
    )
    init_db()
    return out_dir


def test_compare_helpers() -> None:
    ok = _compare_float("x", 50.0, 50.2, unit="%", tol_pct=1.0, tol_abs=0.5)
    assert ok.ok is True
    bad = _compare_int("y", 8, 10)
    assert bad.ok is False
    assert "Δ=-2" in bad.note


def test_build_summary_travelline_reconcile_ok(
    reconcile_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_date = date(2026, 7, 21)
    summary = DailySummaryData(
        report_date=report_date,
        occupancy_pct=47.73,
        occupancy_source="travelline",
        new_bookings_total=11,
        bookings_source="travelline",
        revenue=72508.0,
    )
    monkeypatch.setattr(
        "src.data_sources.summary_reconcile.prepare_daily_summary_data",
        lambda *_a, **_k: summary,
    )
    monkeypatch.setattr(
        "src.data_sources.summary_reconcile.run_daily_reconciliation",
        lambda *_a, **_k: [],
    )

    client = MagicMock()
    client.get_stay_occupancy.return_value = StayOccupancyResult(
        stay_date=report_date,
        sold=21,
        available=44,
        occupancy_pct=47.73,
    )
    client.get_channels.return_value = [{"count": 6}, {"count": 5}]
    client.get_reservations.return_value = [{}] * 11
    client.get_revenue_metrics.return_value = {
        "revenue": 72508.0,
        "adr": 3452.76,
        "revpar": 1647.91,
    }

    data = build_summary_travelline_reconcile(
        report_date, client=client, config=MagicMock(dry_run=True, property=MagicMock(total_units=44))
    )

    assert data["all_ok"] is True
    assert data["dry_run"] is True
    assert data["summary_sources"]["occupancy"] == "travelline"
    assert len(data["comparisons"]) == 5


def test_run_summary_travelline_reconcile_logs_mismatch(
    reconcile_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_date = date(2026, 7, 22)
    data = {
        "report_date": report_date.isoformat(),
        "all_ok": False,
        "comparisons": [{"ok": False, "name": "Загрузка, %"}],
        "sheets_reconcile_warnings": [],
    }
    monkeypatch.setattr(
        "src.data_sources.summary_reconcile.build_summary_travelline_reconcile",
        lambda *_a, **_k: data,
    )
    saved: list[Path] = []

    def _save(payload: dict, *, output_dir: Path | None = None) -> Path:
        path = reconcile_output_dir() / f"reconcile_{payload['report_date']}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        saved.append(path)
        return path

    monkeypatch.setattr("src.data_sources.summary_reconcile.save_reconcile_report", _save)
    monkeypatch.setattr("src.data_sources.summary_reconcile.prune_reconcile_reports", lambda **_k: 0)

    logged: list = []
    monkeypatch.setattr(
        "src.data_sources.summary_reconcile.save_error_log",
        lambda rec: logged.append(rec),
    )

    run_summary_travelline_reconcile(report_date)
    assert saved
    assert len(logged) == 1
    assert logged[0].error_type == "summary_travelline_reconcile"


def test_save_and_prune_reconcile_reports(
    reconcile_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = reconcile_db
    old_day = date.today() - timedelta(days=100)
    new_day = date.today()
    save_reconcile_report(
        {"report_date": old_day.isoformat(), "all_ok": True},
        output_dir=out_dir,
    )
    save_reconcile_report(
        {"report_date": new_day.isoformat(), "all_ok": True},
        output_dir=out_dir,
    )
    removed = prune_reconcile_reports(output_dir=out_dir, keep_days=90)
    assert removed == 1
    assert (out_dir / f"reconcile_{new_day.isoformat()}.json").exists()
    assert not (out_dir / f"reconcile_{old_day.isoformat()}.json").exists()
