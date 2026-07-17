"""Расчёт impact score и коэффициента прогноза."""

from __future__ import annotations

from datetime import date

from src.events.normalize import infer_audience_scope, infer_category, infer_city, is_online_event
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
    "business": 0.95,
    "festival": 0.9,
    "sport": 0.85,
    "concert": 0.7,
    "holiday": 0.75,
    "city_holiday": 0.7,
    "fair": 0.65,
    "exhibition": 0.6,
    "other": 0.4,
}

DEFAULT_FORECAST_COEFFICIENTS = {
    "conference": 0.12,
    "business": 0.11,
    "festival": 0.10,
    "sport": 0.10,
    "concert": 0.08,
    "holiday": 0.08,
    "city_holiday": 0.07,
    "fair": 0.07,
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

# Стартовые overnight_likelihood (калибруются по pickup)
OVERNIGHT_BY_PROFILE = {
    "local_holiday": 0.05,
    "city_concert": 0.10,
    "regional_sport": 0.35,
    "intermunicipal_business": 0.45,
    "national_conference": 0.65,
    "international_multiday": 0.80,
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


def _duration_days(start: date, end: date | None) -> int:
    return max(1, ((end or start) - start).days + 1)


def _duration_score(start: date, end: date | None) -> float:
    days = _duration_days(start, end)
    if days >= 5:
        return 1.0
    if days >= 3:
        return 0.75
    if days == 2:
        return 0.5
    return 0.25


def duration_factor(start: date, end: date | None) -> float:
    """Множитель длительности для event_demand_score."""
    days = _duration_days(start, end)
    if days >= 3:
        return 1.2
    if days == 2:
        return 1.0
    return 0.7


def audience_scope_factor(audience_scope: str) -> float:
    return {
        "international": 1.3,
        "national": 1.15,
        "regional": 1.0,
        "local": 0.5,
        "unknown": 0.8,
    }.get(audience_scope, 0.8)


def estimate_overnight_likelihood(
    *,
    category: str,
    audience_scope: str,
    start_at: date,
    end_at: date | None,
    is_online: bool,
    title: str = "",
    description: str | None = None,
) -> float:
    """Стартовая вероятность ночёвки по типу события."""
    if is_online:
        return 0.0
    text = f"{title} {description or ''}".lower()
    days = _duration_days(start_at, end_at)
    if audience_scope == "international" or (
        days >= 3 and audience_scope in ("national", "international")
    ):
        return OVERNIGHT_BY_PROFILE["international_multiday"]
    if audience_scope == "national" and category in ("conference", "business", "exhibition"):
        return OVERNIGHT_BY_PROFILE["national_conference"]
    if any(w in text for w in ("межмуницип", "межрегион")) or (
        audience_scope == "regional" and category in ("conference", "business")
    ):
        return OVERNIGHT_BY_PROFILE["intermunicipal_business"]
    if category == "sport" and audience_scope in ("regional", "national", "international"):
        return OVERNIGHT_BY_PROFILE["regional_sport"]
    if category in ("concert", "festival", "fair") and audience_scope == "local":
        return OVERNIGHT_BY_PROFILE["city_concert"]
    if category in ("holiday", "city_holiday", "family") or audience_scope == "local":
        return OVERNIGHT_BY_PROFILE["local_holiday"]
    if days >= 2 and audience_scope in ("regional", "national"):
        return 0.40
    return 0.10


def calc_impact_score(
    *,
    audience_scope: str,
    category: str,
    start_at: date,
    end_at: date | None,
    estimated_capacity: int | None,
    source_count: int,
    is_online: bool = False,
) -> float:
    """Impact score 0–100 по формуле из ТЗ."""
    if is_online:
        return 0.0
    audience = AUDIENCE_SCORES.get(audience_scope, 0.3)
    capacity = _capacity_score(estimated_capacity)
    duration = _duration_score(start_at, end_at)
    cat = CATEGORY_SCORES.get(category, 0.4)
    confirm = min(1.0, source_count / 3.0)
    # Городские праздники без иногородней аудитории — не завышать
    if category in ("holiday", "city_holiday") and audience_scope == "local":
        cat *= 0.6
        audience = min(audience, 0.25)
    raw = (
        30 * audience
        + 25 * capacity
        + 20 * duration
        + 15 * cat
        + 10 * confirm
    )
    return round(min(100.0, max(0.0, raw)), 1)


def event_demand_score(
    impact: float,
    overnight: float,
    start_at: date,
    end_at: date | None,
    audience_scope: str,
) -> float:
    """Влияние на спрос с учётом вероятности ночёвки."""
    return round(
        impact
        * overnight
        * duration_factor(start_at, end_at)
        * audience_scope_factor(audience_scope),
        2,
    )


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
    text_blob = f"{parsed.title} {parsed.description or ''} {parsed.venue_name or ''}"
    if parsed.category == "other":
        parsed.category = infer_category(parsed.title, parsed.description)
    if parsed.audience_scope == "unknown":
        parsed.audience_scope = infer_audience_scope(parsed.title, parsed.description)
    if not parsed.is_online:
        parsed.is_online = is_online_event(text_blob)
    if parsed.city == "Томск":
        parsed.city = infer_city(text_blob, default="Томск")
    if parsed.overnight_likelihood is None:
        parsed.overnight_likelihood = estimate_overnight_likelihood(
            category=parsed.category,
            audience_scope=parsed.audience_scope,
            start_at=parsed.start_at,
            end_at=parsed.end_at,
            is_online=parsed.is_online,
            title=parsed.title,
            description=parsed.description,
        )
    if parsed.tourism_relevance == "none" and parsed.overnight_likelihood:
        if parsed.overnight_likelihood >= 0.45:
            parsed.tourism_relevance = "high"
        elif parsed.overnight_likelihood >= 0.25:
            parsed.tourism_relevance = "medium"
        elif parsed.overnight_likelihood >= 0.08:
            parsed.tourism_relevance = "low"
    return parsed


def event_location_ok_for_forecast(event: CityEventRecord) -> bool:
    """Томск автоматически; вне Томска — только после ручного location_confirmed."""
    city = (event.city or "").strip().lower()
    if city in ("томск", "tomsk", ""):
        return True
    return bool(event.location_confirmed)


def event_affects_forecast(status: str, impact_score: float, event: CityEventRecord | None = None) -> bool:
    """Событие учитывается в прогнозе: подтверждено, impact ≥ порога, не онлайн, локация ОК."""
    if status != "approved" or float(impact_score or 0) < MIN_FORECAST_IMPACT:
        return False
    if event is not None:
        if event.is_online:
            return False
        if not event_location_ok_for_forecast(event):
            return False
        if float(event.overnight_likelihood or 0) <= 0:
            return False
    return True


def estimate_guest_nights(
    *,
    estimated_capacity: int | None,
    start_at: date,
    end_at: date | None,
    audience_scope: str,
    overnight_likelihood: float = 0.1,
) -> tuple[int | None, int | None]:
    """Грубая оценка гостевых ночей (min/max) до калибровки по факту."""
    if not estimated_capacity or estimated_capacity <= 0:
        return None, None
    days = _duration_days(start_at, end_at)
    frac = GUEST_NIGHT_FRACTION.get(audience_scope, 0.05)
    mid = estimated_capacity * days * frac * max(0.0, overnight_likelihood)
    return max(0, int(mid * 0.6)), max(0, int(mid * 1.4))


def apply_impact_to_event(event: CityEventRecord, source_count: int) -> CityEventRecord:
    if event.is_online:
        event.overnight_likelihood = 0.0
        event.impact_score = 0.0
        event.expected_guest_nights_min = None
        event.expected_guest_nights_max = None
        event.confidence = CONFIDENCE_BY_SOURCES.get(min(source_count, 3), "low")
        return event

    event.overnight_likelihood = estimate_overnight_likelihood(
        category=event.category,
        audience_scope=event.audience_scope,
        start_at=event.start_at,
        end_at=event.end_at,
        is_online=False,
        title=event.title,
        description=event.description,
    )
    event.impact_score = calc_impact_score(
        audience_scope=event.audience_scope,
        category=event.category,
        start_at=event.start_at,
        end_at=event.end_at,
        estimated_capacity=event.estimated_capacity or event.expected_attendance,
        source_count=source_count,
        is_online=False,
    )
    event.confidence = CONFIDENCE_BY_SOURCES.get(min(source_count, 3), "low")
    gmin, gmax = estimate_guest_nights(
        estimated_capacity=event.estimated_capacity or event.expected_attendance,
        start_at=event.start_at,
        end_at=event.end_at,
        audience_scope=event.audience_scope,
        overnight_likelihood=event.overnight_likelihood,
    )
    event.expected_guest_nights_min = gmin
    event.expected_guest_nights_max = gmax
    if event.tourism_relevance == "none":
        if event.overnight_likelihood >= 0.45:
            event.tourism_relevance = "high"
        elif event.overnight_likelihood >= 0.25:
            event.tourism_relevance = "medium"
        elif event.overnight_likelihood >= 0.08:
            event.tourism_relevance = "low"
    return event
