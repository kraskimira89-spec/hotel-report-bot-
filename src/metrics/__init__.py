"""Расчёт метрик загрузки и светофора."""

from src.metrics.guests import (
    GuestIdentifiers,
    classify_channel,
    classify_channels,
    hash_guest_identifiers,
    hash_identifier,
    is_returning_guest,
    match_returning_guest,
)
from src.metrics.occupancy import (
    calc_occupancy,
    traffic_light,
    traffic_light_emoji,
    traffic_light_status,
)
from src.metrics.revenue import (
    DailyMetrics,
    RevenueResult,
    calc_adr,
    calc_als,
    calc_revpar,
    calc_revpar_from_adr_occupancy,
    compute_daily_metrics,
    resolve_revenue,
)

__all__ = [
    "calc_occupancy",
    "traffic_light",
    "traffic_light_status",
    "traffic_light_emoji",
    "calc_adr",
    "calc_revpar",
    "calc_revpar_from_adr_occupancy",
    "calc_als",
    "resolve_revenue",
    "RevenueResult",
    "DailyMetrics",
    "compute_daily_metrics",
    "classify_channel",
    "classify_channels",
    "hash_identifier",
    "hash_guest_identifiers",
    "GuestIdentifiers",
    "match_returning_guest",
    "is_returning_guest",
]
