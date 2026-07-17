"""Расчёт impact score и коэффициента прогноза."""

from __future__ import annotations

from datetime import date

from src.events.normalize import infer_audience_scope, infer_category
from src.events.types import ParsedEvent
from src.storage.models import CityEventRecord

AUDIENCE_SCORES = {
    "local": 0.2,
    "regional": 0.5,
    "national": 0.8,
    "international": 1.0,
    "unknown": 0.3,
}

CATEGORY_SCORES = {
    "conference": 1.0,
    "festival": 0.9,
    "sport": 0.85,
    "concert": 0.7,
    "holiday": 0.75,
    "exhibition": 0.6,
    "other": 0.4,
}

DEFAULT_FORECAST_COEFFICIENTS = {
    "conference": 0.12,
    "festival": 0.10,
    "sport": 0.10,
    "concert": 0.08,
    "holiday": 0.08,
    "exhibition": 0.06,
    "other": 0.05,
}

CONFIDENCE_BY_SOURCES = {1: "low", 2: "medium", 3: "high"}

# Минимальный impact для влияния на прогноз и метки «учтено в прогнозе»
MIN_FORECAST_IMPACT = 30.0

GUEST_NIGHT_FRACTION = {
    "international": 0.35,
    "national": 0.22,
    "regional": 0.08,
    "local": 0.02,
    "unknown": 0.05,
}


def _capacity_score(capacity: int | None) -> float:
    if not capacity or capacity <= 0:
        return 0.2
    if capacity >= 2000:
        return 1.0
    if capacity >= 1000:
        return 0.85
    if capacity >= 500:
        return 0.65
    if capacity >= 200:
        return 0.45
    if capacity >= 80:
        return 0.3
    return 0.15


def _duration_score(start: date, end: date | None) -> float:
    days = max(1, ((end or start) - start).days + 1)
    if days >= 5:
        return 1.0
    if days >= 3:
        return 0.75
    if days == 2:
        return 0.5
    return 0.25


def calc_impact_score(
    *,
    audience_scope: str,
    category: str,
    start_at: date,
    end_at: date | None,
    estimated_capacity: int | None,
    source_count: int,
) -> float:
    """Impact score 0–100 по формуле из ТЗ."""
    audience = AUDIENCE_SCORES.get(audience_scope, 0.3)
    capacity = _capacity_score(estimated_capacity)
    duration = _duration_score(start_at, end_at)
    cat = CATEGORY_SCORES.get(category, 0.4)
    confirm = min(1.0, source_count / 3.0)
    raw = (
        30 * audience
        + 25 * capacity
        + 20 * duration
        + 15 * cat
        + 10 * confirm
    )
    return round(min(100.0, max(0.0, raw)), 1)


def impact_level(score: float) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def forecast_coefficient_for_category(category: str, max_uplift: float) -> float:
    coef = DEFAULT_FORECAST_COEFFICIENTS.get(category, 0.05)
    return min(max_uplift, coef)


def confidence_factor(confidence: str) -> float:
    return {"high": 1.0, "medium": 0.75, "low": 0.5}.get(confidence, 0.5)


def enrich_parsed_event(parsed: ParsedEvent) -> ParsedEvent:
    if parsed.category == "other":
        parsed.category = infer_category(parsed.title, parsed.description)
    if parsed.audience_scope == "unknown":
        parsed.audience_scope = infer_audience_scope(parsed.title, parsed.description)
    return parsed


def event_affects_forecast(status: str, impact_score: float) -> bool:
    """Событие учитывается в прогнозе: подтверждено и impact ≥ порога."""
    return status == "approved" and float(impact_score or 0) >= MIN_FORECAST_IMPACT


def estimate_guest_nights(
    *,
    estimated_capacity: int | None,
    start_at: date,
    end_at: date | None,
    audience_scope: str,
) -> tuple[int | None, int | None]:
    """Грубая оценка гостевых ночей (min/max) до калибровки по факту."""
    if not estimated_capacity or estimated_capacity <= 0:
        return None, None
    days = max(1, ((end_at or start_at) - start_at).days + 1)
    frac = GUEST_NIGHT_FRACTION.get(audience_scope, 0.05)
    mid = estimated_capacity * days * frac
    return max(0, int(mid * 0.6)), max(0, int(mid * 1.4))


def apply_impact_to_event(event: CityEventRecord, source_count: int) -> CityEventRecord:
    event.impact_score = calc_impact_score(
        audience_scope=event.audience_scope,
        category=event.category,
        start_at=event.start_at,
        end_at=event.end_at,
        estimated_capacity=event.estimated_capacity,
        source_count=source_count,
    )
    event.confidence = CONFIDENCE_BY_SOURCES.get(min(source_count, 3), "low")
    gmin, gmax = estimate_guest_nights(
        estimated_capacity=event.estimated_capacity,
        start_at=event.start_at,
        end_at=event.end_at,
        audience_scope=event.audience_scope,
    )
    event.expected_guest_nights_min = gmin
    event.expected_guest_nights_max = gmax
    return event
