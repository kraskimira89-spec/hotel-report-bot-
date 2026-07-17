"""Тесты прогноза: pickup, сезонность, границы, рекомендации, fallback."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.config import ForecastConfig, ForecastManualEvent, StorageConfig, get_config
from src.forecast.engine import (
    SCENARIOS,
    assess_confidence,
    calc_dow_coefficients,
    calc_seasonal_coefficients,
    forecast_day,
    manual_event_boost,
    pickup_for_scenario,
)
from src.forecast.recommendations import build_price_recommendation
from src.forecast.service import run_forecast_refresh
from src.storage import db as storage_db
from src.storage.db import (
    get_forecast_daily,
    get_latest_forecast_run,
    get_price_recommendations,
    init_db,
    save_metrics_daily,
    update_price_recommendation_status,
)
from src.storage.models import SCHEMA_VERSION, MetricsDailyRecord


@pytest.fixture
def test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "forecast_test.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _patched_db_path() -> Path:
        return db_file

    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file), retention_days=730)
    cfg.forecast = ForecastConfig(enabled=True, min_history_days=30)
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()
    return db_file


def _seed_metrics(start: date, days: int, base_occ: float = 60.0) -> None:
    for i in range(days):
        d = start + timedelta(days=i)
        occ = base_occ + (d.weekday() * 2) + (3 if d.month in (6, 7, 12) else 0)
        save_metrics_daily(
            MetricsDailyRecord(
                report_date=d,
                occupancy_pct=min(95.0, occ),
                adr=5000.0,
                revpar=round(5000.0 * occ / 100, 2),
                revenue=round(44 * 5000.0 * occ / 100, 2),
                bookings_count=5,
            )
        )


def test_schema_v8_tables(test_db: Path) -> None:
    with storage_db.db_session() as conn:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == SCHEMA_VERSION
        for table in ("forecast_runs", "forecast_daily", "price_recommendations"):
            conn.execute(f"SELECT 1 FROM {table} LIMIT 1")


def test_dow_coefficients() -> None:
    metrics = []
    for i in range(14):
        d = date(2026, 1, 5) + timedelta(days=i)
        metrics.append(
            MetricsDailyRecord(
                report_date=d,
                occupancy_pct=50.0 if d.weekday() < 5 else 80.0,
            )
        )
    coefs = calc_dow_coefficients(metrics)
    assert coefs[5] > coefs[0]
    assert all(v > 0 for v in coefs.values())


def test_seasonal_coefficients() -> None:
    metrics = [
        MetricsDailyRecord(report_date=date(2025, 7, 1), occupancy_pct=90.0),
        MetricsDailyRecord(report_date=date(2025, 1, 1), occupancy_pct=40.0),
    ]
    coefs = calc_seasonal_coefficients(metrics)
    assert coefs[7] > coefs[1]


def test_pickup_scenarios() -> None:
    samples = [5.0, 10.0, 15.0, 20.0]
    assert pickup_for_scenario(samples, "conservative") <= pickup_for_scenario(samples, "base")
    assert pickup_for_scenario(samples, "base") <= pickup_for_scenario(samples, "optimistic")


def test_assess_confidence_low_history() -> None:
    conf, note = assess_confidence(20, 180, 365, False)
    assert conf == "low"
    assert "истор" in note.lower() or "6 мес" in note.lower() or "диапазон" in note.lower()


def test_forecast_bounds_wider_for_long_horizon() -> None:
    metrics = []
    for i in range(90):
        d = date(2025, 10, 1) + timedelta(days=i)
        metrics.append(
            MetricsDailyRecord(report_date=d, occupancy_pct=55.0, adr=4500.0, revenue=100000.0)
        )
    as_of = date(2026, 1, 1)
    short = forecast_day(
        target=as_of + timedelta(days=5),
        as_of=as_of,
        scenario="base",
        metrics=metrics,
        total_units=44,
        horizon_days=7,
        min_history_days=30,
    )
    long_h = forecast_day(
        target=as_of + timedelta(days=120),
        as_of=as_of,
        scenario="base",
        metrics=metrics,
        total_units=44,
        horizon_days=180,
        min_history_days=30,
    )
    short_spread = short.upper_bound - short.lower_bound
    long_spread = long_h.upper_bound - long_h.lower_bound
    assert long_spread >= short_spread


def test_forecast_uses_actual_for_past_date() -> None:
    metrics = [
        MetricsDailyRecord(report_date=date(2026, 1, 10), occupancy_pct=72.0, adr=5000.0),
    ]
    result = forecast_day(
        target=date(2026, 1, 10),
        as_of=date(2026, 1, 15),
        scenario="base",
        metrics=metrics,
        total_units=44,
        horizon_days=7,
        min_history_days=30,
    )
    assert result.actual_occupancy_pct == 72.0
    assert result.occupancy_pct == 72.0


def test_recommendation_increase_when_high_occ_and_below_market() -> None:
    from src.forecast.engine import DayForecast, ForecastFactors

    day = DayForecast(
        forecast_date=date.today() + timedelta(days=5),
        room_type="1room",
        scenario="base",
        occupancy_pct=85.0,
        adr=5000.0,
        revpar=4250.0,
        revenue=100000.0,
        sold_unit_nights=20.0,
        available_unit_nights=44,
        lower_bound=75.0,
        upper_bound=95.0,
        confidence="high",
        factors=ForecastFactors(history_days=200),
    )
    rec = build_price_recommendation(
        forecast=day,
        current_price=4000.0,
        market_median=5000.0,
        pickup_7d=5,
        min_price=2000.0,
        max_price=20000.0,
        max_change_pct=15.0,
        use_competitors=True,
    )
    assert rec is not None
    assert rec.recommendation_type == "increase"


def test_recommendation_manual_when_no_price() -> None:
    from src.forecast.engine import DayForecast, ForecastFactors

    day = DayForecast(
        forecast_date=date.today() + timedelta(days=3),
        room_type="1room",
        scenario="base",
        occupancy_pct=50.0,
        adr=None,
        revpar=None,
        revenue=0.0,
        sold_unit_nights=10.0,
        available_unit_nights=44,
        lower_bound=40.0,
        upper_bound=60.0,
        confidence="low",
        factors=ForecastFactors(history_days=10),
    )
    rec = build_price_recommendation(
        forecast=day,
        current_price=None,
        market_median=None,
        pickup_7d=0,
        min_price=2000.0,
        max_price=20000.0,
        max_change_pct=15.0,
        use_competitors=False,
    )
    assert rec is not None
    assert rec.recommendation_type == "manual_review"


def test_manual_event_boost() -> None:
    events = [
        ForecastManualEvent(
            name="Концерт",
            date_from="2026-07-20",
            date_to="2026-07-22",
            impact_pct=10.0,
        )
    ]
    boost, name = manual_event_boost(date(2026, 7, 21), events)
    assert boost == 10.0
    assert name == "Концерт"
    assert manual_event_boost(date(2026, 7, 1), events)[0] == 0.0


def test_forecast_day_applies_manual_event() -> None:
    metrics = [
        MetricsDailyRecord(report_date=date(2026, 1, 10), occupancy_pct=50.0, adr=5000.0),
    ]
    events = [
        ForecastManualEvent(
            name="Выставка",
            date_from="2026-07-20",
            date_to="2026-07-20",
            impact_pct=20.0,
        )
    ]
    base = forecast_day(
        target=date(2026, 7, 20),
        as_of=date(2026, 7, 10),
        scenario="base",
        metrics=metrics,
        total_units=44,
        horizon_days=7,
        min_history_days=30,
        manual_events=events,
    )
    plain = forecast_day(
        target=date(2026, 7, 20),
        as_of=date(2026, 7, 10),
        scenario="base",
        metrics=metrics,
        total_units=44,
        horizon_days=7,
        min_history_days=30,
    )
    assert base.occupancy_pct >= plain.occupancy_pct
    assert base.factors.event_boost_pct == 20.0


def test_recommendations_filtered_by_horizon(test_db: Path) -> None:
    start = date.today() - timedelta(days=45)
    _seed_metrics(start, 45)
    run_forecast_refresh(horizons=[7, 180])
    recs_7 = get_price_recommendations(status="new", horizon_days=7)
    recs_180 = get_price_recommendations(status="new", horizon_days=180)
    if recs_7 and recs_180:
        assert all(r.horizon_days == 7 for r in recs_7)
        assert all(r.horizon_days == 180 for r in recs_180)


def test_forecast_id_linked(test_db: Path) -> None:
    start = date.today() - timedelta(days=45)
    _seed_metrics(start, 45)
    run_forecast_refresh(horizons=[7])
    recs = get_price_recommendations(status="new", horizon_days=7)
    if not recs:
        pytest.skip("нет рекомендаций")
    assert any(r.forecast_id is not None for r in recs)


def test_quality_errors_empty_db(test_db: Path) -> None:
    from src.forecast.quality import calc_forecast_errors, should_warn_quality

    err = calc_forecast_errors(30)
    assert err["samples"] == 0
    assert should_warn_quality(err, 15.0, 20.0) is False


def test_run_forecast_refresh_persists(test_db: Path) -> None:
    start = date.today() - timedelta(days=60)
    _seed_metrics(start, 60)
    stats = run_forecast_refresh(horizons=[7])
    assert stats.get("h7", 0) > 0
    run = get_latest_forecast_run(7)
    assert run is not None
    rows = get_forecast_daily(run.id, scenario="base", room_type="")
    assert len(rows) == 7
    for scenario in SCENARIOS:
        scenario_rows = get_forecast_daily(run.id, scenario=scenario, room_type="")
        assert len(scenario_rows) == 7


def test_recommendation_status_update(test_db: Path) -> None:
    start = date.today() - timedelta(days=45)
    _seed_metrics(start, 45)
    run_forecast_refresh(horizons=[7])
    recs = get_price_recommendations(status="new")
    if not recs:
        pytest.skip("нет рекомендаций в тестовых данных")
    rec_id = recs[0].id
    assert rec_id is not None
    assert update_price_recommendation_status(rec_id, "accepted")
    updated = get_price_recommendations(status="accepted")
    assert any(r.id == rec_id for r in updated)
