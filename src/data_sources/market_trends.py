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
from typing import Any

from src.config import AppConfig, get_config

logger = logging.getLogger(__name__)


def fetch_competitor_prices(config: AppConfig | None = None) -> list[dict[str, Any]]:
    """Собрать цены конкурентов из списка config.competitors.

    Возвращает список словарей вида:
        {"name": str, "type": "direct"|"indirect", "url": str,
         "price_from": float | None, "available": bool}
    где available=False, если цену не удалось получить из открытых источников.

    # TODO: этап 6/7 — реализовать парсинг по каждому сайту с анти-блок правилами,
    #        переиспользовать backoff/паузы из site_prices, уточнить селекторы.
    """
    cfg = config or get_config()
    competitors = getattr(cfg, "competitors", []) or []
    logger.info(
        "fetch_competitor_prices: %s конкурентов в конфиге (заглушка, этап 6/7)",
        len(competitors),
    )
    # TODO: реальный сбор. Пока возвращаем структуру без цен.
    return [
        {
            "name": c.get("name") if isinstance(c, dict) else getattr(c, "name", ""),
            "type": c.get("type") if isinstance(c, dict) else getattr(c, "type", ""),
            "url": c.get("url") if isinstance(c, dict) else getattr(c, "url", ""),
            "price_from": None,
            "available": False,
        }
        for c in competitors
    ]


def fetch_market_news(config: AppConfig | None = None) -> list[dict[str, Any]]:
    """Собрать 3–5 новостей/трендов рынка для email-отчёта.

    # TODO: этап 6/7 — источники (RSS/API новостей туризма и гостеприимства),
    #        ограничение по config.market_news.max_items.
    """
    logger.info("fetch_market_news: заглушка (этап 6/7)")
    return []
