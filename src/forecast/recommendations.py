"""Рекомендации по ценам на основе прогноза и рынка."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.forecast.engine import DayForecast
from src.storage.models import PriceRecommendationRecord

WEEKDAY_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def _is_public_holiday_on(target: date, events: list[Any]) -> bool:
    for ev in events:
        if not getattr(ev, "is_public_holiday", False):
            continue
        start = getattr(ev, "start_at", None)
        if start is None:
            continue
        end = getattr(ev, "end_at", None) or start
        if start <= target <= end:
            return True
    return False


def _clamp_price(
    price: float,
    min_price: float,
    max_price: float,
    max_change_pct: float,
    current: float,
) -> float:
    bounded = max(min_price, min(max_price, price))
    if current > 0:
        max_up = current * (1 + max_change_pct / 100)
        max_down = current * (1 - max_change_pct / 100)
        bounded = max(max_down, min(max_up, bounded))
    return round(bounded, 0)


def default_selected_price(
    rec_min: float | None,
    rec_max: float | None,
    current_price: float | None,
    recommendation_type: str,
) -> float | None:
    """Цена к применению по умолчанию: середина диапазона."""
    if recommendation_type == "manual_review" and (
        rec_min is None or rec_max is None or rec_min == rec_max == current_price
    ):
        return None
    if rec_min is not None and rec_max is not None:
        return round((rec_min + rec_max) / 2, 0)
    return current_price


def build_recommendation_snapshot(
    *,
    forecast: DayForecast,
    current_price: float | None,
    market_median: float | None,
    market_gap_pct: float | None,
    pickup_3d: int,
    pickup_7d: int,
    free_units: int | None,
    total_units: int | None,
    min_price: float,
    max_price: float,
    max_change_pct: float,
    approved_events: list[Any] | None,
    recommendation_type: str,
    reason: str,
    rec_min: float | None,
    rec_max: float | None,
    model_version: str,
    as_of: date,
    horizon_days: int | None,
) -> dict[str, Any]:
    """Снимок оснований рекомендации на момент создания."""
    events_out: list[dict[str, Any]] = []
    for ev in approved_events or []:
        if getattr(ev, "status", None) != "approved":
            continue
        end_d = getattr(ev, "end_at", None) or ev.start_at
        if not (ev.start_at <= forecast.forecast_date <= end_d):
            continue
        events_out.append(
            {
                "title": ev.title,
                "start_at": ev.start_at.isoformat(),
                "end_at": end_d.isoformat() if end_d else None,
                "impact_score": getattr(ev, "impact_score", None),
                "category": getattr(ev, "category", None),
            }
        )
    factors = forecast.factors
    return {
        "as_of": as_of.isoformat(),
        "model_version": model_version,
        "horizon_days": horizon_days,
        "target_date": forecast.forecast_date.isoformat(),
        "room_type": forecast.room_type or "all",
        "occupancy_pct": round(forecast.occupancy_pct, 1),
        "confidence": forecast.confidence,
        "history_days": factors.history_days,
        "pickup_3d": pickup_3d,
        "pickup_7d": pickup_7d,
        "free_units": free_units,
        "total_units": total_units,
        "current_price": current_price,
        "market_median": market_median,
        "market_gap_pct": market_gap_pct,
        "events": events_out,
        "seasonal_coef": factors.seasonal_coef,
        "dow_coef": factors.dow_coef,
        "weekday": WEEKDAY_RU[forecast.forecast_date.weekday()],
        "event_boost_pct": factors.event_boost_pct,
        "is_public_holiday": _is_public_holiday_on(
            forecast.forecast_date, approved_events or []
        ),
        "min_price": min_price,
        "max_price": max_price,
        "max_price_change_pct": max_change_pct,
        "recommendation_type": recommendation_type,
        "reason": reason,
        "recommended_price_min": rec_min,
        "recommended_price_max": rec_max,
        "notes": list(factors.notes or []),
    }


def build_price_recommendation(
    forecast: DayForecast,
    current_price: float | None,
    market_median: float | None,
    pickup_7d: int,
    min_price: float,
    max_price: float,
    max_change_pct: float,
    use_competitors: bool,
    pickup_3d: int = 0,
    approved_events: list[Any] | None = None,
    *,
    free_units: int | None = None,
    total_units: int | None = None,
    model_version: str = "v1",
    as_of: date | None = None,
    horizon_days: int | None = None,
) -> PriceRecommendationRecord | None:
    """Сформировать рекомендацию для даты и типа номера."""
    from src.events.impact import impact_level

    as_of = as_of or date.today()

    def _with_snapshot(
        rec: PriceRecommendationRecord,
        market_gap: float | None,
    ) -> PriceRecommendationRecord:
        rec.recommendation_snapshot_json = build_recommendation_snapshot(
            forecast=forecast,
            current_price=current_price,
            market_median=market_median if use_competitors else None,
            market_gap_pct=market_gap,
            pickup_3d=pickup_3d,
            pickup_7d=pickup_7d,
            free_units=free_units,
            total_units=total_units,
            min_price=min_price,
            max_price=max_price,
            max_change_pct=max_change_pct,
            approved_events=approved_events,
            recommendation_type=rec.recommendation_type,
            reason=rec.reason,
            rec_min=rec.recommended_price_min,
            rec_max=rec.recommended_price_max,
            model_version=model_version,
            as_of=as_of,
            horizon_days=horizon_days,
        )
        rec.selected_price = default_selected_price(
            rec.recommended_price_min,
            rec.recommended_price_max,
            rec.current_price,
            rec.recommendation_type,
        )
        return rec

    if current_price is None or current_price <= 0:
        return _with_snapshot(
            PriceRecommendationRecord(
                room_type=forecast.room_type or "all",
                target_date=forecast.forecast_date,
                current_price=current_price,
                recommendation_type="manual_review",
                reason="Нет текущей цены — требуется ручная проверка",
                confidence="low",
                status="new",
                forecast_id=forecast.id if hasattr(forecast, "id") else None,
            ),
            None,
        )

    if forecast.confidence == "low" and forecast.factors.history_days < 30:
        return _with_snapshot(
            PriceRecommendationRecord(
                room_type=forecast.room_type or "all",
                target_date=forecast.forecast_date,
                current_price=current_price,
                recommended_price_min=current_price,
                recommended_price_max=current_price,
                recommendation_type="manual_review",
                reason="Данных недостаточно — не менять автоматически",
                confidence="low",
                status="new",
            ),
            None,
        )

    occ = forecast.occupancy_pct
    lead_days = (forecast.forecast_date - date.today()).days
    market_gap_pct: float | None = None
    if use_competitors and market_median and market_median > 0:
        market_gap_pct = round((current_price - market_median) / market_median * 100, 1)

    rec_type = "hold"
    reason_parts: list[str] = [f"прогноз загрузки {occ:.0f}%"]
    delta_pct = 0.0

    if occ >= 80 and pickup_7d >= 3 and market_gap_pct is not None and market_gap_pct < -5:
        rec_type = "increase"
        delta_pct = min(max_change_pct, max(3.0, abs(market_gap_pct) * 0.5))
        reason_parts.append(f"цена на {abs(market_gap_pct):.0f}% ниже рынка")
        reason_parts.append("сильный pickup")
    elif occ >= 85 and pickup_7d >= 2 and lead_days <= 14:
        rec_type = "restrict_discounts"
        delta_pct = min(max_change_pct, 5.0)
        reason_parts.append("высокий спрос, мало свободных номеров")
    elif occ < 45 and pickup_7d <= 1 and lead_days <= 7:
        rec_type = "decrease"
        delta_pct = -min(max_change_pct, 10.0)
        reason_parts.append(f"до заезда осталось {lead_days} дн.")
        reason_parts.append("слабый pickup")
    elif market_gap_pct is not None and abs(market_gap_pct) <= 8 and 50 <= occ <= 75:
        rec_type = "hold"
        reason_parts.append("загрузка в плане, цена около рынка")
    elif occ < 40 and lead_days <= 14:
        rec_type = "decrease"
        delta_pct = -min(max_change_pct, 8.0)
        reason_parts.append("низкая прогнозная загрузка")

    for ev in approved_events or []:
        if getattr(ev, "status", None) != "approved":
            continue
        if ev.impact_score < 60:
            continue
        end_d = ev.end_at or ev.start_at
        if not (ev.start_at <= forecast.forecast_date <= end_d):
            continue
        pickup_median_3d = max(2, pickup_7d * 3 / 7)
        pickup_elevated = pickup_3d >= pickup_median_3d * 1.2
        price_ok = market_gap_pct is None or market_gap_pct <= 10
        if occ >= 65 and pickup_elevated and price_ok:
            if rec_type == "hold" and delta_pct == 0:
                rec_type = "increase"
                delta_pct = min(max_change_pct, 8.0)
            date_range = ev.start_at.strftime("%d.%m")
            if end_d != ev.start_at:
                date_range += f"–{end_d.strftime('%d.%m')}"
            event_note = (
                f"На {date_range} подтверждено «{ev.title}» "
                f"(impact {ev.impact_score:.0f}, {impact_level(ev.impact_score)}). "
                f"Прогноз загрузки {occ:.0f}%, pickup 3д выше медианы"
            )
            if market_gap_pct is not None:
                event_note += f", цена vs рынок {market_gap_pct:+.0f}%"
            reason_parts.append(event_note)
            break

    target = current_price * (1 + delta_pct / 100)
    rec_min = _clamp_price(target * 0.98, min_price, max_price, max_change_pct, current_price)
    rec_max = _clamp_price(target * 1.02, min_price, max_price, max_change_pct, current_price)
    if rec_type == "hold":
        rec_min = rec_max = current_price

    change_rub = rec_min - current_price
    change_pct = round(change_rub / current_price * 100, 1) if current_price else 0.0
    if change_rub != 0:
        reason_parts.append(f"изменение {change_rub:+.0f} ₽ ({change_pct:+.1f}%)")

    if free_units is None and total_units is not None:
        known = forecast.factors.known_booked_pct
        free_units = max(0, int(round(total_units * (1 - known / 100))))

    return _with_snapshot(
        PriceRecommendationRecord(
            room_type=forecast.room_type or "all",
            target_date=forecast.forecast_date,
            current_price=current_price,
            recommended_price_min=rec_min,
            recommended_price_max=rec_max,
            recommendation_type=rec_type,
            reason="; ".join(reason_parts),
            confidence=forecast.confidence,
            status="new",
        ),
        market_gap_pct,
    )
