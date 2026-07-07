"""Метрики дохода: ADR, RevPAR, ALS."""

from __future__ import annotations


def calc_adr(revenue: float, sold_unit_nights: int) -> float | None:
    """ADR = доход за проживание / продано unit-nights."""
    if sold_unit_nights <= 0:
        return None
    return round(revenue / sold_unit_nights, 2)


def calc_revpar(revenue: float, available_unit_nights: int) -> float | None:
    """RevPAR = доход / доступно unit-nights."""
    if available_unit_nights <= 0:
        return None
    return round(revenue / available_unit_nights, 2)


def calc_revpar_from_adr_occupancy(adr: float, occupancy_pct: float) -> float:
    """RevPAR = ADR × Occupancy (доля, не %)."""
    return round(adr * occupancy_pct / 100, 2)


def calc_als(total_stay_days: int, bookings_count: int) -> float | None:
    """ALS = дней пребывания / кол-во броней."""
    if bookings_count <= 0:
        return None
    return round(total_stay_days / bookings_count, 2)
