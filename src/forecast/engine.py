"""Детерминированная модель прогноза загрузки и выручки."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from src.metrics.revenue import calc_adr, calc_revpar, calc_revpar_from_adr_occupancy
from src.storage.models import MetricsDailyRecord

if False:  # pragma: no cover — только для type checkers
    pass

Scenario = Literal["conservative", "base", "optimistic"]
SCENARIOS: tuple[Scenario, ...] = ("conservative", "base", "optimistic")
Confidence = Literal["high", "medium", "low"]


@dataclass
class ForecastFactors:
    """Объяснение вклада факторов в прогноз."""

    seasonal_coef: float = 1.0
    dow_coef: float = 1.0
    pickup_expected_pct: float = 0.0
    known_booked_pct: float = 0.0
    market_adj_pct: float = 0.0
    event_boost_pct: float = 0.0
    history_days: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seasonal_coef": round(self.seasonal_coef, 4),
            "dow_coef": round(self.dow_coef, 4),
            "pickup_expected_pct": round(self.pickup_expected_pct, 2),
            "known_booked_pct": round(self.known_booked_pct, 2),
            "market_adj_pct": round(self.market_adj_pct, 2),
            "event_boost_pct": round(self.event_boost_pct, 2),
            "history_days": self.history_days,
            "notes": self.notes,
        }


@dataclass
class DayForecast:
    """Прогноз на одну дату."""

    forecast_date: date
    room_type: str
    scenario: Scenario
    occupancy_pct: float
    adr: float | None
    revpar: float | None
    revenue: float
    sold_unit_nights: float
    available_unit_nights: int
    lower_bound: float
    upper_bound: float
    confidence: Confidence
    factors: ForecastFactors
    actual_occupancy_pct: float | None = None


def _metrics_by_date(metrics: list[MetricsDailyRecord]) -> dict[date, MetricsDailyRecord]:
    return {m.report_date: m for m in metrics if m.occupancy_pct is not None}


def calc_dow_coefficients(metrics: list[MetricsDailyRecord]) -> dict[int, float]:
    """Коэффициент дня недели (0=пн) относительно средней загрузки."""
    by_dow: dict[int, list[float]] = {i: [] for i in range(7)}
    for m in metrics:
        if m.occupancy_pct is not None:
            by_dow[m.report_date.weekday()].append(m.occupancy_pct)
    overall = [m.occupancy_pct for m in metrics if m.occupancy_pct is not None]
    if not overall:
        return {i: 1.0 for i in range(7)}
    mean_all = statistics.mean(overall)
    if mean_all <= 0:
        return {i: 1.0 for i in range(7)}
    result: dict[int, float] = {}
    for dow in range(7):
        vals = by_dow[dow]
        if vals:
            result[dow] = statistics.mean(vals) / mean_all
        else:
            result[dow] = 1.0
    return result


def calc_seasonal_coefficients(metrics: list[MetricsDailyRecord]) -> dict[int, float]:
    """Коэффициент месяца (1–12) относительно средней загрузки."""
    by_month: dict[int, list[float]] = {i: [] for i in range(1, 13)}
    for m in metrics:
        if m.occupancy_pct is not None:
            by_month[m.report_date.month].append(m.occupancy_pct)
    overall = [m.occupancy_pct for m in metrics if m.occupancy_pct is not None]
    if not overall:
        return {i: 1.0 for i in range(1, 13)}
    mean_all = statistics.mean(overall)
    if mean_all <= 0:
        return {i: 1.0 for i in range(1, 13)}
    result: dict[int, float] = {}
    for month in range(1, 13):
        vals = by_month[month]
        if vals:
            result[month] = statistics.mean(vals) / mean_all
        else:
            result[month] = 1.0
    return result


def _pickup_samples(
    metrics: list[MetricsDailyRecord],
    lead_days: int,
) -> list[float]:
    """Остаточный pickup (финал − загрузка за lead_days до даты) для аналогичных дат."""
    by_date = _metrics_by_date(metrics)
    samples: list[float] = []
    for target, final_m in by_date.items():
        lead_date = target - timedelta(days=lead_days)
        lead_m = by_date.get(lead_date)
        if lead_m is None or final_m.occupancy_pct is None or lead_m.occupancy_pct is None:
            continue
        remaining = max(0.0, final_m.occupancy_pct - lead_m.occupancy_pct)
        samples.append(remaining)
    return samples


def _similar_pickup_samples(
    metrics: list[MetricsDailyRecord],
    target: date,
    lead_days: int,
) -> list[float]:
    """Pickup для дат с тем же месяцем и днём недели."""
    by_date = _metrics_by_date(metrics)
    samples: list[float] = []
    for hist_date, final_m in by_date.items():
        if hist_date.month != target.month or hist_date.weekday() != target.weekday():
            continue
        lead_date = hist_date - timedelta(days=lead_days)
        lead_m = by_date.get(lead_date)
        if lead_m is None or final_m.occupancy_pct is None or lead_m.occupancy_pct is None:
            continue
        samples.append(max(0.0, final_m.occupancy_pct - lead_m.occupancy_pct))
    return samples


def pickup_for_scenario(samples: list[float], scenario: Scenario) -> float:
    """Ожидаемый pickup по сценарию."""
    if not samples:
        return 0.0
    if scenario == "conservative":
        return min(samples) if len(samples) == 1 else _quantile(samples, 0.25)
    if scenario == "optimistic":
        return max(samples) if len(samples) == 1 else _quantile(samples, 0.75)
    return statistics.median(samples)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = q * (len(ordered) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def assess_confidence(
    history_days: int,
    horizon_days: int,
    min_history_days: int,
    has_similar_dates: bool,
) -> tuple[Confidence, str]:
    """Уровень достоверности и краткое объяснение."""
    if history_days < min_history_days // 4:
        return "low", f"Истории всего {history_days} дн. — недостаточно для сезонного прогноза"
    if horizon_days > 90:
        if history_days < min_history_days:
            return "low", "Горизонт 6 мес.: показан диапазон сценариев, не точная цифра"
        return "medium", "Длинный горизонт: повышена неопределённость, опора на сезонность"
    if history_days >= min_history_days and horizon_days <= 14 and has_similar_dates:
        return "high", "Достаточная история и близкий горизонт"
    if history_days >= min_history_days // 2:
        return "medium", "История ограничена — используется консервативный fallback"
    return "low", "Мало аналогичных дат — fallback по среднему"


def _uncertainty_band(
    occupancy: float,
    confidence: Confidence,
    horizon_days: int,
    lead_days: int,
) -> tuple[float, float]:
    """Нижняя и верхняя граница загрузки, %."""
    if horizon_days >= 180:
        spread = 18.0 if confidence == "low" else 12.0 if confidence == "medium" else 8.0
    elif horizon_days >= 30:
        spread = 12.0 if confidence == "low" else 8.0 if confidence == "medium" else 5.0
    else:
        spread = 8.0 if confidence == "low" else 5.0 if confidence == "medium" else 3.0
    if lead_days <= 3:
        spread *= 0.7
    lower = max(0.0, occupancy - spread)
    upper = min(100.0, occupancy + spread)
    return round(lower, 2), round(upper, 2)


def manual_event_boost(
    target: date,
    events: list[Any],
) -> tuple[float, str | None]:
    """Суммарный boost загрузки от ручных событий, %."""
    total = 0.0
    names: list[str] = []
    for ev in events:
        try:
            d_from = date.fromisoformat(str(ev.date_from))
            d_to = date.fromisoformat(str(ev.date_to))
        except (TypeError, ValueError):
            continue
        if d_from <= target <= d_to:
            total += float(ev.impact_pct)
            names.append(str(ev.name))
    if not names:
        return 0.0, None
    return total, ", ".join(names)


def _ev_field(ev: Any, name: str, default: Any = None) -> Any:
    if isinstance(ev, dict):
        return ev.get(name, default)
    return getattr(ev, name, default)


def city_events_boost(
    target: date,
    events: list[Any],
    *,
    max_uplift_pct: float = 15.0,
) -> tuple[float, list[str]]:
    """Консервативный uplift от подтверждённых событий города, %."""
    from src.events.impact import confidence_factor, event_affects_forecast

    total = 0.0
    notes: list[str] = []
    for ev in events:
        status = _ev_field(ev, "status")
        impact = float(_ev_field(ev, "impact_score", 0) or 0)
        # Полная проверка для CityEventRecord; для dict — базовые поля
        if hasattr(ev, "is_online"):
            if not event_affects_forecast(str(status), impact, ev):
                continue
        elif status != "approved":
            continue
        start = _ev_field(ev, "start_at")
        end = _ev_field(ev, "end_at")
        if isinstance(start, str):
            start = date.fromisoformat(start[:10])
        if isinstance(end, str):
            end = date.fromisoformat(end[:10]) if end else None
        if not start:
            continue
        end_d = end or start
        if not (start <= target <= end_d):
            continue
        from src.events.impact import MIN_FORECAST_IMPACT

        if impact < MIN_FORECAST_IMPACT:
            continue
        if bool(_ev_field(ev, "is_online", False)):
            continue
        overnight = float(_ev_field(ev, "overnight_likelihood", 0.1) or 0.1)
        if overnight <= 0:
            continue
        coef = float(_ev_field(ev, "forecast_coefficient", 0.05) or 0.05)
        conf = str(_ev_field(ev, "confidence", "low") or "low")
        uplift = coef * (impact / 100.0) * confidence_factor(conf) * overnight * 100.0
        total += uplift
        title = _ev_field(ev, "title", "?")
        notes.append(f"{title} (+{uplift:.1f}%)")
    capped = min(max_uplift_pct, total)
    return round(capped, 2), notes


def _baseline_occupancy(metrics: list[MetricsDailyRecord]) -> float:
    vals = [m.occupancy_pct for m in metrics if m.occupancy_pct is not None]
    if not vals:
        return 0.0
    return statistics.mean(vals)


def _median_adr(metrics: list[MetricsDailyRecord]) -> float | None:
    vals = [m.adr for m in metrics if m.adr is not None and m.adr > 0]
    if not vals:
        return None
    return round(statistics.median(vals), 2)


def forecast_day(
    target: date,
    as_of: date,
    scenario: Scenario,
    metrics: list[MetricsDailyRecord],
    total_units: int,
    horizon_days: int,
    min_history_days: int,
    market_adj_pct: float = 0.0,
    room_type: str = "",
    known_occupancy: float | None = None,
    manual_events: list[Any] | None = None,
    city_events: list[Any] | None = None,
    max_event_uplift_pct: float = 15.0,
) -> DayForecast:
    """Прогноз загрузки и выручки на одну дату."""
    by_date = _metrics_by_date(metrics)
    history_days = len(by_date)
    dow_coefs = calc_dow_coefficients(metrics)
    seasonal_coefs = calc_seasonal_coefficients(metrics)
    baseline = _baseline_occupancy(metrics)
    dow_coef = dow_coefs.get(target.weekday(), 1.0)
    seasonal_coef = seasonal_coefs.get(target.month, 1.0)
    lead_days = max(0, (target - as_of).days)

    actual = known_occupancy
    if actual is None and target <= as_of:
        actual_m = by_date.get(target)
        if actual_m and actual_m.occupancy_pct is not None:
            actual = actual_m.occupancy_pct

    factors = ForecastFactors(
        seasonal_coef=seasonal_coef,
        dow_coef=dow_coef,
        market_adj_pct=market_adj_pct,
        history_days=history_days,
    )

    similar = _similar_pickup_samples(metrics, target, max(lead_days, 1))
    has_similar = len(similar) >= 2
    confidence, conf_note = assess_confidence(
        history_days, horizon_days, min_history_days, has_similar
    )
    factors.notes.append(conf_note)

    if actual is not None and target <= as_of:
        occ = actual
        factors.known_booked_pct = actual
        factors.pickup_expected_pct = 0.0
        factors.notes.append("Использован факт за дату")
    else:
        known = known_occupancy or 0.0
        pickup_samples = similar if similar else _pickup_samples(metrics, max(lead_days, 7))
        if not pickup_samples and not has_similar:
            factors.notes.append("Fallback: средняя загрузка по доступной истории")
        pickup = pickup_for_scenario(pickup_samples, scenario)
        factors.pickup_expected_pct = round(pickup, 2)
        factors.known_booked_pct = round(known, 2)

        seasonal_weight = 0.25 if horizon_days <= 14 else 0.45 if horizon_days <= 30 else 0.65
        pickup_weight = 1.0 - seasonal_weight

        model_base = baseline * (
            seasonal_weight * seasonal_coef * dow_coef
            + pickup_weight * (1.0 + (pickup / 100.0))
        )
        occ = min(100.0, max(0.0, known + pickup * pickup_weight + model_base * seasonal_weight * 0.3))
        if market_adj_pct:
            occ = min(100.0, max(0.0, occ * (1 + market_adj_pct / 100.0)))
            factors.notes.append(f"Корректировка по рынку: {market_adj_pct:+.1f}%")
        event_boost, event_name = manual_event_boost(target, manual_events or [])
        city_boost, city_notes = city_events_boost(
            target, city_events or [], max_uplift_pct=max_event_uplift_pct
        )
        combined_boost = event_boost + city_boost
        if combined_boost:
            occ = min(100.0, max(0.0, occ * (1 + combined_boost / 100.0)))
            factors.event_boost_pct = round(combined_boost, 2)
            if event_name:
                factors.notes.append(f"Событие «{event_name}»: {event_boost:+.1f}%")
            for note in city_notes:
                factors.notes.append(f"Событие города: {note}")

    lower, upper = _uncertainty_band(occ, confidence, horizon_days, lead_days)
    adr = _median_adr(metrics)
    if adr is None and metrics:
        rev_vals = [m.revenue for m in metrics if m.revenue and m.revenue > 0]
        if rev_vals:
            adr = round(statistics.median(rev_vals) / max(total_units * 0.5, 1), 2)

    available = total_units
    sold = round(available * occ / 100.0, 2)
    revenue = round((adr or 0.0) * sold, 2)
    revpar = calc_revpar(revenue, available) if available else None
    if adr is None and sold > 0:
        adr = calc_adr(revenue, int(sold))
    elif adr and revpar is None:
        revpar = calc_revpar_from_adr_occupancy(adr, occ)

    return DayForecast(
        forecast_date=target,
        room_type=room_type,
        scenario=scenario,
        occupancy_pct=round(occ, 2),
        adr=adr,
        revpar=revpar,
        revenue=revenue,
        sold_unit_nights=sold,
        available_unit_nights=available,
        lower_bound=lower,
        upper_bound=upper,
        confidence=confidence,
        factors=factors,
        actual_occupancy_pct=actual,
    )


def forecast_horizon(
    as_of: date,
    horizon_days: int,
    metrics: list[MetricsDailyRecord],
    total_units: int,
    min_history_days: int,
    market_adj_pct: float = 0.0,
    room_types: list[str] | None = None,
    category_metrics: dict[str, list[MetricsDailyRecord]] | None = None,
    category_units: dict[str, int] | None = None,
    manual_events: list[Any] | None = None,
    city_events: list[Any] | None = None,
    max_event_uplift_pct: float = 15.0,
) -> list[DayForecast]:
    """Прогноз на горизонт для всех сценариев и типов номеров."""
    room_types = room_types if room_types is not None else [""]
    category_metrics = category_metrics or {}
    category_units = category_units or {}
    # Пока по категории мало дней — не блокируем цены: берём базу объекта
    min_category_days = max(30, min_history_days // 4)
    results: list[DayForecast] = []
    for offset in range(horizon_days):
        target = as_of + timedelta(days=offset)
        for scenario in SCENARIOS:
            for room_type in room_types:
                fallback_note = ""
                if room_type and room_type in category_metrics:
                    cat_rows = category_metrics[room_type]
                    cat_days = len({m.report_date for m in cat_rows})
                    if cat_days >= min_category_days:
                        mset = cat_rows
                        units = category_units.get(room_type) or max(
                            1, total_units // max(len(room_types) - 1, 1)
                        )
                    else:
                        mset = metrics
                        units = category_units.get(room_type) or max(
                            1, total_units // max(len(room_types) - 1, 1)
                        )
                        fallback_note = (
                            f"Категория «{room_type}»: истории {cat_days} дн. "
                            f"(нужно ≥{min_category_days}) — использована база объекта"
                        )
                else:
                    mset = metrics
                    units = total_units
                day = forecast_day(
                    target=target,
                    as_of=as_of,
                    scenario=scenario,
                    metrics=mset,
                    total_units=units,
                    horizon_days=horizon_days,
                    min_history_days=min_history_days,
                    market_adj_pct=market_adj_pct,
                    room_type=room_type,
                    manual_events=manual_events,
                    city_events=city_events,
                    max_event_uplift_pct=max_event_uplift_pct,
                )
                if fallback_note:
                    day.factors.notes.insert(0, fallback_note)
                results.append(day)
    return results


def factors_json_dumps(factors: ForecastFactors) -> str:
    return json.dumps(factors.to_dict(), ensure_ascii=False)
