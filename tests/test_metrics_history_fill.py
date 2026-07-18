"""Тесты добора категорий metrics_daily поверх существующего daily."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import ForecastConfig, StorageConfig, get_config, reload_config
from src.data_sources.travelline import RevenueReport, StayOccupancyResult
from src.forecast.metrics_history import (
    backfill_metrics_history,
    collect_metrics_for_date,
    needs_category_fill,
)
from src.storage import db as storage_db
from src.storage.db import (
    count_category_metrics_for_date,
    get_metrics_for_date,
    init_db,
    resolve_errors_log,
    save_error_log,
    save_metrics_daily,
)
from src.storage.models import ErrorLogRecord, MetricsDailyRecord


@pytest.fixture
def metrics_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "metrics_fill.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _path() -> Path:
        return db_file

    cfg = reload_config()
    cfg.storage = StorageConfig(db_path=str(db_file), retention_days=730)
    cfg.forecast = ForecastConfig(enabled=True, min_history_days=30)
    monkeypatch.setattr(storage_db, "get_db_path", _path)
    monkeypatch.setattr("src.config.get_db_path", _path)
    init_db()
    return db_file


def _fake_client(day: date) -> MagicMock:
    client = MagicMock()
    by_type = {
        "Однокомнатные квартиры 27 м²": 3,
        "Однокомнатные квартиры с диванчиком": 2,
    }
    free_by = {
        "Однокомнатные квартиры 27 м²": 5,
        "Однокомнатные квартиры с диванчиком": 4,
    }
    client.get_stay_occupancy.return_value = StayOccupancyResult(
        stay_date=day,
        sold=5,
        available=44,
        occupancy_pct=11.4,
        by_type=by_type,
        free_by_type=free_by,
        booked_by_type={},
    )
    client.get_stay_occupancy_summary.return_value = StayOccupancyResult(
        stay_date=day,
        sold=5,
        available=44,
        occupancy_pct=11.4,
    )
    client.get_revenue.return_value = RevenueReport(revenue=50000.0, is_estimated=False)
    client.get_channels.return_value = [{"count": 3}]
    return client


def test_fill_categories_when_daily_exists(metrics_db: Path) -> None:
    day = date(2026, 6, 1)
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=day,
            metric_type="daily",
            occupancy_pct=50.0,
            adr=5000.0,
            revenue=10000.0,
        )
    )
    assert needs_category_fill(day) is True
    with patch(
        "src.data_sources.travelline.TravelLineClient",
        return_value=_fake_client(day),
    ):
        outcome = collect_metrics_for_date(day, fill_categories=True)
    assert outcome.kind == "categories"
    assert outcome.saved >= 1
    assert count_category_metrics_for_date(day) >= 1
    daily = get_metrics_for_date(day, "daily")
    assert daily is not None
    assert daily.occupancy_pct == 50.0


def test_skip_when_categories_complete(metrics_db: Path) -> None:
    day = date(2026, 6, 2)
    cfg = get_config()
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=day, metric_type="daily", occupancy_pct=40.0, revenue=1.0
        )
    )
    for slug in cfg.category_slug_map:
        save_metrics_daily(
            MetricsDailyRecord(
                report_date=day,
                metric_type=f"category:{slug}",
                occupancy_pct=30.0,
                revenue=1.0,
            )
        )
    assert needs_category_fill(day) is False
    with patch(
        "src.data_sources.travelline.TravelLineClient",
        return_value=_fake_client(day),
    ):
        outcome = collect_metrics_for_date(day, fill_categories=True)
    assert outcome.kind == "skipped"
    assert outcome.saved == 0


def test_fast_daily_only_no_categories(metrics_db: Path) -> None:
    day = date(2026, 6, 3)
    with patch(
        "src.data_sources.travelline.TravelLineClient",
        return_value=_fake_client(day),
    ):
        outcome = collect_metrics_for_date(day, daily_only=True, fill_categories=True)
    assert outcome.kind == "daily_only"
    assert get_metrics_for_date(day, "daily") is not None
    assert count_category_metrics_for_date(day) == 0


def test_resolve_errors_after_successful_collect(metrics_db: Path) -> None:
    day = date(2026, 6, 4)
    save_error_log(
        ErrorLogRecord(
            error_date=day,
            source="travelline",
            error_type="http_error",
            message="timeout",
        )
    )
    with patch(
        "src.data_sources.travelline.TravelLineClient",
        return_value=_fake_client(day),
    ):
        collect_metrics_for_date(day)
    from src.storage.db import get_errors_log

    open_errs = get_errors_log(start_date=day, end_date=day, resolved=False, limit=10)
    assert not any(e.error_type == "http_error" for e in open_errs)


def test_backfill_counts_filled_categories(metrics_db: Path) -> None:
    day = date(2026, 6, 5)
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=day, metric_type="daily", occupancy_pct=10.0, revenue=1.0
        )
    )
    with patch(
        "src.data_sources.travelline.TravelLineClient",
        return_value=_fake_client(day),
    ):
        stats = backfill_metrics_history(
            days=1,
            end_date=day,
            fill_categories=True,
            delay_sec=0.0,
        )
    assert stats["filled_categories"] >= 1
    assert stats["skipped"] == 0


def test_resolve_errors_log_api(metrics_db: Path) -> None:
    day = date(2026, 6, 6)
    save_error_log(
        ErrorLogRecord(
            error_date=day,
            source="travelline",
            error_type="http_error",
            message="x",
        )
    )
    n = resolve_errors_log(
        source="travelline", error_type="http_error", error_date=day
    )
    assert n == 1
