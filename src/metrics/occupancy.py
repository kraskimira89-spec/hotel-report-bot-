"""Метрики загрузки (Occupancy) и светофор."""

from __future__ import annotations

from src.config import TrafficLightThresholds


def calc_occupancy(sold_unit_nights: int, available_unit_nights: int) -> float:
    """Occupancy = продано unit-nights / доступно unit-nights × 100%.

    При available_unit_nights == 0 возвращает 0.0.
    """
    if available_unit_nights <= 0:
        return 0.0
    return round(sold_unit_nights / available_unit_nights * 100, 2)


def traffic_light_status(
    value: float,
    thresholds: TrafficLightThresholds,
    metric: str = "occupancy",
) -> str:
    """Вернуть статус светофора: green / yellow / red.

    metric: occupancy | price_change | new_bookings
    """
    if metric == "occupancy":
        if value >= thresholds.occupancy_green_min:
            return "green"
        if value >= thresholds.occupancy_yellow_min:
            return "yellow"
        return "red"

    if metric == "price_change":
        abs_val = abs(value)
        if abs_val < thresholds.price_change_yellow_pct:
            return "green"
        if abs_val < thresholds.price_change_red_pct:
            return "yellow"
        return "red"

    if metric == "new_bookings":
        if value >= thresholds.new_bookings_green_min:
            return "green"
        if value >= thresholds.new_bookings_yellow_min:
            return "yellow"
        return "red"

    return "yellow"


def traffic_light_emoji(status: str) -> str:
    """Эмодзи для статуса светофора."""
    return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(status, "🟡")
