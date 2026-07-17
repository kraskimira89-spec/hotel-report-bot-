"""Оркестрация расчёта прогноза и сохранения в БД."""

from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import get_config
from src.forecast.engine import DayForecast, forecast_horizon
from src.forecast.metrics_history import category_metric_type
from src.forecast.quality import calc_forecast_errors, should_warn_quality
from src.forecast.recommendations import build_price_recommendation
from src.storage.db import (
    delete_forecast_daily_for_run,
    get_bookings_daily,
    get_competitor_prices_latest,
    get_forecast_daily_id_map,
    get_metrics_daily,
    get_price_snapshots_by_date,
    save_forecast_daily_batch,
    save_price_recommendations,
    upsert_forecast_run,
)
from src.storage.models import ForecastDailyRecord, ForecastRunRecord, PriceRecommendationRecord

logger = logging.getLogger(__name__)
MODEL_VERSION = "v1"


def _msk_now() -> datetime:
    cfg = get_config()
    return datetime.now(tz=ZoneInfo(cfg.property.timezone))


def _history_start(as_of: date, retention_days: int) -> date:
    return as_of - timedelta(days=retention_days)


def _room_types() -> list[str]:
    cfg = get_config()
    slugs = list(cfg.site_prices.category_urls or [])
    if not slugs and cfg.category_slug_map:
        slugs = list(cfg.category_slug_map.keys())
    return slugs


def _load_category_history(
    as_of: date,
    retention: int,
    room_types: list[str],
) -> tuple[dict[str, list], dict[str, int]]:
    """История и unit-count по категориям."""
    start = _history_start(as_of, retention)
    category_metrics: dict[str, list] = {}
    category_units: dict[str, int] = {}
    for slug in room_types:
        rows = get_metrics_daily(start, as_of, metric_type=category_metric_type(slug))
        if rows:
            category_metrics[slug] = rows
    # Оценка units из последних метрик: revenue ≈ adr * sold, sold = occ * units
    for slug, rows in category_metrics.items():
        latest = rows[-1]
        if latest.occupancy_pct and latest.revenue and latest.adr and latest.adr > 0:
            sold = latest.revenue / latest.adr
            if latest.occupancy_pct > 0:
                category_units[slug] = max(1, int(round(sold * 100 / latest.occupancy_pct)))
    return category_metrics, category_units


def _market_median() -> float | None:
    cfg = get_config()
    if not cfg.forecast.use_competitors:
        return None
    prices = get_competitor_prices_latest()
    vals = [p.price_from for p in prices if p.price_from and p.price_from > 0]
    if not vals:
        return None
    return round(statistics.median(vals), 2)


def _market_adj_pct(our_price: float | None, market_median: float | None) -> float:
    if not our_price or not market_median or market_median <= 0:
        return 0.0
    gap = (our_price - market_median) / market_median * 100
    if gap < -10:
        return 2.0
    if gap > 10:
        return -2.0
    return 0.0


def _pickup_counts(as_of: date) -> dict[str, int]:
    """Новые бронирования за 1/3/7 дней."""
    counts = {"1d": 0, "3d": 0, "7d": 0}
    bookings = get_bookings_daily(as_of - timedelta(days=7), as_of)
    for b in bookings:
        delta = (as_of - b.created_date).days
        if delta <= 1:
            counts["1d"] += 1
        if delta <= 3:
            counts["3d"] += 1
        if delta <= 7:
            counts["7d"] += 1
    return counts


def _load_city_events(as_of: date, horizon: int) -> list:
    from src.events.service import events_for_forecast

    end = as_of + timedelta(days=horizon)
    return events_for_forecast(as_of, end)


def _data_quality_label(history_days: int, min_history: int) -> str:
    if history_days >= min_history:
        return "good"
    if history_days >= min_history // 2:
        return "limited"
    return "poor"


def _day_to_record(run_id: int, day: DayForecast) -> ForecastDailyRecord:
    return ForecastDailyRecord(
        run_id=run_id,
        forecast_date=day.forecast_date,
        room_type=day.room_type,
        scenario=day.scenario,
        occupancy_pct=day.occupancy_pct,
        adr=day.adr,
        revpar=day.revpar,
        revenue=day.revenue,
        sold_unit_nights=day.sold_unit_nights,
        available_unit_nights=day.available_unit_nights,
        lower_bound=day.lower_bound,
        upper_bound=day.upper_bound,
        confidence=day.confidence,
        factors_json=day.factors.to_dict(),
        actual_occupancy_pct=day.actual_occupancy_pct,
    )


def run_forecast_refresh(
    horizons: list[int] | None = None,
    as_of: date | None = None,
) -> dict[str, int]:
    """Пересчитать прогнозы для указанных горизонтов."""
    cfg = get_config()
    fc = cfg.forecast
    if not fc.enabled:
        logger.info("Прогноз отключён в конфиге")
        return {}

    as_of = as_of or _msk_now().date()
    horizons = horizons or fc.horizons
    retention = cfg.storage.retention_days
    history = get_metrics_daily(_history_start(as_of, retention), as_of)
    history_days = len({m.report_date for m in history})
    quality = _data_quality_label(history_days, fc.min_history_days)
    total_units = cfg.property.total_units
    room_types = _room_types()
    category_metrics, category_units = _load_category_history(as_of, retention, room_types)
    market_median = _market_median()
    snapshots = {s.category: s.price for s in get_price_snapshots_by_date(as_of)}
    if not snapshots:
        yesterday = as_of - timedelta(days=1)
        snapshots = {s.category: s.price for s in get_price_snapshots_by_date(yesterday)}
    our_avg_price = statistics.mean(snapshots.values()) if snapshots else None
    market_adj = _market_adj_pct(our_avg_price, market_median)
    pickup_7d = _pickup_counts(as_of)["7d"]
    pickup_3d = _pickup_counts(as_of)["3d"]
    max_uplift = cfg.events.max_forecast_uplift * 100 if cfg.events.enabled else 15.0
    city_events = _load_city_events(as_of, max(horizons) if horizons else 30)

    errors = calc_forecast_errors(30)
    quality_warn = should_warn_quality(errors, fc.max_mae_occupancy, fc.max_mape_revenue)

    stats: dict[str, int] = {}
    for horizon in horizons:
        days = forecast_horizon(
            as_of=as_of,
            horizon_days=horizon,
            metrics=history,
            total_units=total_units,
            min_history_days=fc.min_history_days,
            market_adj_pct=market_adj,
            room_types=[""] + room_types,
            category_metrics=category_metrics,
            category_units=category_units,
            manual_events=fc.manual_events,
            city_events=city_events,
            max_event_uplift_pct=max_uplift,
        )
        run = upsert_forecast_run(
            ForecastRunRecord(
                calculated_at=_msk_now(),
                horizon_days=horizon,
                model_version=MODEL_VERSION,
                data_quality=quality,
                status="completed",
            )
        )
        assert run.id is not None
        delete_forecast_daily_for_run(run.id)
        records = [_day_to_record(run.id, d) for d in days]
        saved = save_forecast_daily_batch(records)
        id_map = get_forecast_daily_id_map(run.id)

        recs: list[PriceRecommendationRecord] = []
        base_days = [d for d in days if d.scenario == "base" and d.room_type]
        for day in base_days:
            if horizon > 14 and day.forecast_date.day not in (1, 7, 14, 21, 28):
                if day.forecast_date.weekday() != 0:
                    continue
            price = snapshots.get(day.room_type)
            rec = build_price_recommendation(
                forecast=day,
                current_price=price,
                market_median=market_median,
                pickup_7d=pickup_7d,
                pickup_3d=pickup_3d,
                min_price=fc.min_price,
                max_price=fc.max_price,
                max_change_pct=fc.max_price_change_pct,
                use_competitors=fc.use_competitors,
                approved_events=city_events,
            )
            if rec:
                key = (day.forecast_date.isoformat(), day.room_type, "base")
                rec.forecast_id = id_map.get(key)
                rec.horizon_days = horizon
                recs.append(rec)
        rec_saved = save_price_recommendations(recs, horizon_days=horizon, as_of=as_of)
        stats[f"h{horizon}"] = saved
        stats[f"rec_h{horizon}"] = rec_saved
        logger.info(
            "Прогноз h=%s: %s строк, %s рекомендаций, quality=%s warn=%s history=%s",
            horizon,
            saved,
            rec_saved,
            quality,
            quality_warn,
            history_days,
        )
    return stats
