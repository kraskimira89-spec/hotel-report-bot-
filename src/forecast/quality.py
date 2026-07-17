"""Оценка качества прогнозов (MAE, MAPE)."""

from __future__ import annotations

from datetime import date, timedelta

from src.storage.db import get_forecast_accuracy_rows, get_metrics_for_date


def calc_forecast_errors(lookback_days: int = 30) -> dict[str, float | int]:
    """Сравнить прошлые прогнозы с фактом за lookback_days."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    rows = get_forecast_accuracy_rows(start, end)
    if not rows:
        return {"samples": 0, "mae_occupancy": 0.0, "mape_revenue": 0.0}

    occ_errors: list[float] = []
    rev_errors: list[float] = []
    for row in rows:
        actual = get_metrics_for_date(row["forecast_date"])
        if actual is None or actual.occupancy_pct is None:
            continue
        if row["occupancy_pct"] is not None:
            occ_errors.append(abs(row["occupancy_pct"] - actual.occupancy_pct))
        if row["revenue"] and actual.revenue and actual.revenue > 0:
            rev_errors.append(abs(row["revenue"] - actual.revenue) / actual.revenue * 100)

    mae = round(sum(occ_errors) / len(occ_errors), 2) if occ_errors else 0.0
    mape = round(sum(rev_errors) / len(rev_errors), 2) if rev_errors else 0.0
    return {
        "samples": len(occ_errors),
        "mae_occupancy": mae,
        "mape_revenue": mape,
    }


def should_warn_quality(errors: dict[str, float | int], max_mae: float, max_mape: float) -> bool:
    if int(errors.get("samples", 0)) < 5:
        return False
    return float(errors.get("mae_occupancy", 0)) > max_mae or float(errors.get("mape_revenue", 0)) > max_mape
