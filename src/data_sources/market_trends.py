"""Сбор новостей/трендов и цен конкурентов для email-отчёта."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def fetch_competitor_prices() -> list[dict[str, Any]]:
    """Собрать цены конкурентов.

    # TODO: этап 6/7 — источники и парсинг конкурентов.
    """
    logger.info("fetch_competitor_prices: заглушка (этап 6/7)")
    return []


def fetch_market_news() -> list[dict[str, Any]]:
    """Собрать новости и тренды рынка.

    # TODO: этап 6/7 — RSS/API новостей туризма.
    """
    logger.info("fetch_market_news: заглушка (этап 6/7)")
    return []
