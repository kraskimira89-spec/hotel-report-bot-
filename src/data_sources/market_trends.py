"""Сбор новостей/трендов и цен конкурентов для email-отчёта."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from statistics import mean

from pydantic import BaseModel, Field

from src.storage.db import get_price_snapshots

logger = logging.getLogger(__name__)

DEFAULT_MARKET_TRENDS: list[str] = [
    "Спрос на апарт-отели в Москве остаётся устойчивым в будний сезон.",
    "Гости чаще бронируют напрямую при длительном проживании (3+ ночей).",
    "Агрегаторы усиливают промо в выходные — следите за долей прямых каналов.",
]


class CompetitorPriceSeries(BaseModel):
    """Цены конкурента/источника за период (по дням)."""

    name: str
    category: str
    prices: dict[str, float] = Field(default_factory=dict)


def fetch_competitor_prices(
    period_start: date,
    period_end: date,
) -> list[CompetitorPriceSeries]:
    """Публичные цены за период (из snapshot БД, где доступно)."""
    snapshots = get_price_snapshots(period_start, period_end)
    if not snapshots:
        logger.info("fetch_competitor_prices: нет snapshot за период")
        return []

    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for item in snapshots:
        day = item.snapshot_at.date().isoformat()
        key = (item.source or "site", item.category)
        grouped[key][day] = item.price

    result: list[CompetitorPriceSeries] = []
    for (source, category), prices in sorted(grouped.items()):
        name = "1apart.ru" if source == "site" else source
        result.append(
            CompetitorPriceSeries(name=name, category=category, prices=prices)
        )
    return result


def build_market_trends(
    period_start: date,
    period_end: date,
    occupancy_pct: float | None = None,
    prev_occupancy_pct: float | None = None,
    direct_share_pct: float | None = None,
    returning_share_pct: float | None = None,
) -> list[str]:
    """Сформировать 3–5 пунктов трендов рынка на основе метрик периода."""
    trends: list[str] = []

    if occupancy_pct is not None and prev_occupancy_pct is not None:
        delta = occupancy_pct - prev_occupancy_pct
        trends.append(
            f"Средняя загрузка за неделю {occupancy_pct:.1f}% "
            f"({delta:+.1f} п.п. к прошлой неделе)."
        )
    elif occupancy_pct is not None:
        trends.append(f"Средняя загрузка за неделю: {occupancy_pct:.1f}%.")

    if direct_share_pct is not None:
        trends.append(f"Доля прямых бронирований: {direct_share_pct:.1f}%.")

    if returning_share_pct is not None:
        trends.append(f"Доля повторных гостей: {returning_share_pct:.1f}%.")

    snapshots = get_price_snapshots(period_start, period_end)
    by_category: dict[str, list[float]] = defaultdict(list)
    for item in snapshots:
        by_category[item.category].append(item.price)

    for category, prices in sorted(by_category.items()):
        if len(prices) < 2:
            continue
        first_week = mean(prices[: max(1, len(prices) // 2)])
        last_week = mean(prices[len(prices) // 2 :])
        if first_week > 0:
            change = (last_week - first_week) / first_week * 100
            trends.append(
                f"Публичная цена «{category}»: {change:+.1f}% за период."
            )
        if len(trends) >= 5:
            break

    for fallback in DEFAULT_MARKET_TRENDS:
        if len(trends) >= 3:
            break
        if fallback not in trends:
            trends.append(fallback)

    return trends[:5]


def fetch_market_news() -> list[dict[str, str]]:
    """Заглушка RSS/API — возвращает типовые тренды до подключения источника."""
    logger.info("fetch_market_news: используется встроенный список трендов")
    return [{"title": title} for title in DEFAULT_MARKET_TRENDS]
