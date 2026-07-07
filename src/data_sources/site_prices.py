"""Сбор базовых цен категорий со статического HTML 1apart.ru (httpx + BeautifulSoup)."""

from __future__ import annotations

import logging
import random
import time
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from src.config import AppConfig, SitePricesConfig, get_config

logger = logging.getLogger(__name__)


def parse_category_html(html: str, category_slug: str) -> dict[str, Any] | None:
    """Распарсить HTML страницы категории и извлечь цену.

    Ищет элемент с data-price или классом price.
    """
    soup = BeautifulSoup(html, "lxml")
    price_el = soup.select_one("[data-price]") or soup.select_one(".price-value")
    if price_el is None:
        return None

    raw = price_el.get("data-price") or price_el.get_text(strip=True)
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None

    return {
        "category": category_slug,
        "price": float(digits),
        "currency": "RUB",
    }


def _request_with_backoff(
    client: httpx.Client,
    url: str,
    cfg: SitePricesConfig,
) -> httpx.Response:
    """HTTP-запрос с backoff при 403/429/503."""
    delay = cfg.backoff_initial_sec
    last_exc: Exception | None = None

    for attempt in range(cfg.max_retries):
        try:
            resp = client.get(url)
            if resp.status_code in (403, 429, 503):
                logger.warning(
                    "HTTP %s для %s, попытка %s/%s",
                    resp.status_code,
                    url,
                    attempt + 1,
                    cfg.max_retries,
                )
                time.sleep(min(delay, cfg.backoff_max_sec))
                delay *= 2
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            time.sleep(min(delay, cfg.backoff_max_sec))
            delay *= 2

    raise last_exc or httpx.HTTPError(f"Не удалось загрузить {url}")


def fetch_category_prices(config: AppConfig | None = None) -> list[dict[str, Any]]:
    """Собрать базовые цены по всем категориям с сайта.

    # TODO: этап 3 — сохранение в price_snapshots, fallback на последний snapshot.
    """
    cfg = config or get_config()
    site_cfg = cfg.site_prices
    results: list[dict[str, Any]] = []

    headers = {"User-Agent": site_cfg.user_agent}

    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        for path in site_cfg.category_urls:
            url = urljoin(site_cfg.base_url, path)
            slug = path.rstrip("/").split("/")[-1]

            pause = random.uniform(
                site_cfg.request_delay_min_sec,
                site_cfg.request_delay_max_sec,
            )
            time.sleep(pause)

            try:
                resp = _request_with_backoff(client, url, site_cfg)
                parsed = parse_category_html(resp.text, slug)
                if parsed:
                    results.append(parsed)
                    logger.info("Цена %s: %s RUB", slug, parsed["price"])
                else:
                    logger.warning("Не удалось распарсить цену: %s", url)
            except httpx.HTTPError as exc:
                logger.error("Ошибка сбора цен %s: %s", url, exc)

    return results
