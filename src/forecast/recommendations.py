"""Рекомендации по ценам на основе прогноза и рынка."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.forecast.engine import DayForecast
from src.storage.models import PriceRecommendationRecord


def _clamp_price(price: float, min_price: float, max_price: float, max_change_pct: float, current: float) -> float:
    bounded = max(min_price, min(max_price, price))
    if current > 0:
        max_up = current * (1 + max_change_pct / 100)
        max_down = current * (1 - max_change_pct / 100)
        bounded = max(max_down, min(max_up, bounded))
    return round(bounded, 0)


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
) -> PriceRecommendationRecord | None:
    """Сформировать рекомендацию для даты и типа номера."""
    from src.events.impact import impact_level
    if current_price is None or current_price <= 0:
        return PriceRecommendationRecord(
            room_type=forecast.room_type or "all",
            target_date=forecast.forecast_date,
            current_price=current_price,
            recommendation_type="manual_review",
            reason="Нет текущей цены — требуется ручная проверка",
            confidence="low",
            status="new",
            forecast_id=forecast.id if hasattr(forecast, "id") else None,
        )

    if forecast.confidence == "low" and forecast.factors.history_days < 30:
        return PriceRecommendationRecord(
            room_type=forecast.room_type or "all",
            target_date=forecast.forecast_date,
            current_price=current_price,
            recommended_price_min=current_price,
            recommended_price_max=current_price,
            recommendation_type="manual_review",
            reason="Данных недостаточно — не менять автоматически",
            confidence="low",
            status="new",
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

    # События города: только подтверждённые с высоким impact
    event_note: str | None = None
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

    return PriceRecommendationRecord(
        room_type=forecast.room_type or "all",
        target_date=forecast.forecast_date,
        current_price=current_price,
        recommended_price_min=rec_min,
        recommended_price_max=rec_max,
        recommendation_type=rec_type,
        reason="; ".join(reason_parts),
        confidence=forecast.confidence,
        status="new",
    )
