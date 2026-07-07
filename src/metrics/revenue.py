"""Метрики дохода: ADR, RevPAR, ALS, определение дохода."""

from __future__ import annotations

from pydantic import BaseModel


class RevenueResult(BaseModel):
    """Результат расчёта дохода."""

    revenue: float
    is_estimated: bool


class DailyMetrics(BaseModel):
    """Сводка дневных метрик (чистый расчёт без I/O)."""

    occupancy_pct: float
    adr: float | None
    revpar: float | None
    als: float | None
    revenue: float
    is_estimated: bool


def resolve_revenue(
    actual_revenue: float | None,
    snapshot_price: float | None,
    occupied_unit_nights: int,
) -> RevenueResult:
    """Определить доход: факт приоритетен, иначе оценка по snapshot.

    Fallback: snapshot_price × occupied_unit_nights, is_estimated=True.
    """
    if actual_revenue is not None and actual_revenue >= 0:
        return RevenueResult(revenue=round(actual_revenue, 2), is_estimated=False)

    if (
        snapshot_price is not None
        and snapshot_price >= 0
        and occupied_unit_nights > 0
    ):
        return RevenueResult(
            revenue=round(snapshot_price * occupied_unit_nights, 2),
            is_estimated=True,
        )

    return RevenueResult(revenue=0.0, is_estimated=True)


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


def compute_daily_metrics(
    sold_unit_nights: int,
    available_unit_nights: int,
    total_stay_days: int,
    bookings_count: int,
    actual_revenue: float | None = None,
    snapshot_price: float | None = None,
) -> DailyMetrics:
    """Рассчитать полный набор дневных метрик."""
    from src.metrics.occupancy import calc_occupancy

    occupancy_pct = calc_occupancy(sold_unit_nights, available_unit_nights)
    revenue_result = resolve_revenue(
        actual_revenue,
        snapshot_price,
        sold_unit_nights,
    )
    adr = calc_adr(revenue_result.revenue, sold_unit_nights)
    revpar = calc_revpar(revenue_result.revenue, available_unit_nights)
    als = calc_als(total_stay_days, bookings_count)

    return DailyMetrics(
        occupancy_pct=occupancy_pct,
        adr=adr,
        revpar=revpar,
        als=als,
        revenue=revenue_result.revenue,
        is_estimated=revenue_result.is_estimated,
    )
