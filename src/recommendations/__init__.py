"""Центр универсальных рекомендаций."""

from src.recommendations.service import (
    build_system_recommendations,
    build_trend_pilot_recommendations,
    refresh_recommendations_center,
    sync_price_recommendations,
)
from src.recommendations.render import render_instruction_card

__all__ = [
    "build_system_recommendations",
    "build_trend_pilot_recommendations",
    "refresh_recommendations_center",
    "render_instruction_card",
    "sync_price_recommendations",
]
