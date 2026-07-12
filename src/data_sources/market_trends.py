"""Сбор новостей/трендов и цен конкурентов для еженедельного email-отчёта.

Конкуренты и источники новостей задаются в config/settings.yaml:
- секция ``competitors`` — список объектов (name, type: direct|indirect, url);
- секция ``market_news`` — enabled, max_items.

Правила (ТЗ v2.2):
- Цены конкурентов идут ТОЛЬКО в еженедельный email-отчёт (справочно),
  в ежедневную Max-сводку они НЕ входят.
- При сборе с сайтов конкурентов соблюдаются те же анти-блок правила,
  что и в site_prices (задержки, случайные паузы, User-Agent, robots.txt,
  backoff при 403/429/503).
- Загрузку конкурентов из открытых источников надёжно получить нельзя —
  собираются только цены, где они доступны публично на сайте/виджете.
- Селекторы по каждому сайту уточняются на этапе 6/7 (у объектов разная
  верстка; часть цен может быть внутри виджетов бронирования — тогда
  цена берётся только если доступна в публичном HTML).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from statistics import mean

from pydantic import BaseModel

from src.config import get_config
from src.data_sources.competitor_prices import collect_competitor_prices
from src.storage.db import get_price_snapshots

logger = logging.getLogger(__name__)

DEFAULT_MARKET_TRENDS: list[str] = [
    "Спрос на апарт-отели в Томске остаётся устойчивым в будний сезон.",
    "Гости чаще бронируют напрямую при длительном проживании (3+ ночей).",
    "Агрегаторы усиливают промо в выходные — следите за долей прямых каналов.",
]


class CompetitorPriceInfo(BaseModel):
    """Публичные цены конкурента (если доступны)."""

    name: str
    kind: str
    url: str
    price_from: float | None = None
    available: bool = False


def fetch_competitor_prices(
    period_start: date,
    period_end: date,
) -> list[CompetitorPriceInfo]:
    """Список конкурентов и минимальные публичные цены (если доступны)."""
    _ = (period_start, period_end)
    cfg = get_config()
    if not cfg.competitors:
        logger.info("fetch_competitor_prices: список конкурентов пуст")
        return []

    prices_map = collect_competitor_prices(cfg.competitors, cfg.site_prices)
    return [
        CompetitorPriceInfo(
            name=item.name,
            kind=item.type,
            url=item.url,
            price_from=prices_map.get(item.name),
            available=prices_map.get(item.name) is not None,
        )
        for item in cfg.competitors
    ]


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
    """Тренды рынка для email и веб-раздела."""
    cfg = get_config()
    if not cfg.market_news.enabled:
        return []
    from src.web.market_intel import GLOBAL_TRENDS, MOSCOW_TRENDS

    source = (cfg.market_news.sources or ["1apart"])[0]
    items: list[dict[str, str]] = []
    for block in (*MOSCOW_TRENDS, *GLOBAL_TRENDS):
        items.append(
            {
                "title": block["title"],
                "body": block.get("body", ""),
                "source": source,
                "tag": block.get("tag", ""),
            }
        )
    return items[: cfg.market_news.max_items]
