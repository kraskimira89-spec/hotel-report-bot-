"""Парсинг публичных цен конкурентов (static HTML, этап 6/7)."""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Protocol
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.config import CompetitorConfig, SitePricesConfig
from src.data_sources.site_prices import (
    is_path_allowed,
    parse_robots_disallow,
)
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

_WIDGET_PARSERS = frozenset({"widget", "tl_widget", "wubook_widget"})


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: object) -> httpx.Response: ...


def _extract_price_digits(raw: str) -> float | None:
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    return float(digits)


def parse_petrovskie_html(html: str) -> float | None:
    """Tilda: минимальная цена «1 сутки» из .t776__price-value."""
    soup = BeautifulSoup(html, "lxml")
    prices: list[float] = []
    one_night = re.compile(
        r"1\s*сут(?:ки|ок)?\s*[-–]\s*([\d\s]+)",
        re.IGNORECASE,
    )
    for el in soup.select(".t776__price-value, .js-product-price"):
        text = el.get_text(" ", strip=True)
        match = one_night.search(text)
        if match:
            value = _extract_price_digits(match.group(1))
            if value is not None:
                prices.append(value)
                continue
        for part in text.split("|"):
            part_match = one_night.search(part)
            if part_match:
                value = _extract_price_digits(part_match.group(1))
                if value is not None:
                    prices.append(value)
    return min(prices) if prices else None


def parse_gogol_html(html: str, price_regex: str | None = None) -> float | None:
    """Regex «Цена от N руб» на gogolhotel.ru."""
    pattern = re.compile(
        price_regex or r"Цена от\s*([\d\s]+)\s*руб",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if not match:
        return None
    return _extract_price_digits(match.group(1))


def parse_kuhterin_html(html: str) -> float | None:
    """Каталог: минимум из блоков .price (каждое «N руб» отдельно)."""
    soup = BeautifulSoup(html, "lxml")
    prices: list[float] = []
    price_num = re.compile(r"([\d\s\u00a0]+)\s*руб", re.IGNORECASE)
    for block in soup.select(".price"):
        text = block.get_text(" ", strip=True)
        for match in price_num.finditer(text):
            value = _extract_price_digits(match.group(1))
            if value is not None:
                prices.append(value)
    return min(prices) if prices else None


def parse_static_competitor_html(
    html: str,
    competitor: CompetitorConfig,
) -> float | None:
    """Распарсить HTML по селекторам конфига или эвристике имени."""
    sel = competitor.selectors
    if sel.get("price_regex"):
        return parse_gogol_html(html, sel["price_regex"])

    if sel.get("price_block"):
        if "кухтерин" in competitor.name.lower():
            return parse_kuhterin_html(html)
        soup = BeautifulSoup(html, "lxml")
        prices: list[float] = []
        price_num = re.compile(r"([\d\s\u00a0]+)\s*руб", re.IGNORECASE)
        for block in soup.select(sel["price_block"]):
            text = block.get_text(" ", strip=True)
            for match in price_num.finditer(text):
                value = _extract_price_digits(match.group(1))
                if value is not None:
                    prices.append(value)
        if prices:
            return min(prices)

    if sel.get("price"):
        if "петровск" in competitor.name.lower():
            return parse_petrovskie_html(html)
        soup = BeautifulSoup(html, "lxml")
        el = soup.select_one(sel["price"])
        if el is not None:
            value = _extract_price_digits(el.get_text(" ", strip=True))
            if value is not None:
                return value

    name_lower = competitor.name.lower()
    if "петровск" in name_lower:
        return parse_petrovskie_html(html)
    if "гоголь" in name_lower:
        return parse_gogol_html(html)
    if "кухтерин" in name_lower:
        return parse_kuhterin_html(html)
    return None


def _anti_block_pause(site_cfg: SitePricesConfig) -> None:
    pause = random.uniform(site_cfg.request_delay_min_sec, site_cfg.request_delay_max_sec)
    time.sleep(pause)


def _request_with_backoff(
    client: HttpClient,
    url: str,
    site_cfg: SitePricesConfig,
) -> httpx.Response:
    return retry_with_backoff(
        lambda: client.get(url, headers={"User-Agent": site_cfg.user_agent}),
        retries=site_cfg.max_retries,
        backoff_initial=site_cfg.backoff_initial_sec,
        backoff_max=site_cfg.backoff_max_sec,
        retry_statuses=(403, 429, 503, 500, 502, 504),
        log_prefix=f"competitor_prices {url}",
    )


def _robots_disallow(client: HttpClient, base_url: str, site_cfg: SitePricesConfig) -> list[str]:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    disallow: list[str] = []
    try:
        resp = client.get(robots_url, headers={"User-Agent": site_cfg.user_agent})
        if resp.status_code == 200:
            disallow = parse_robots_disallow(resp.text)
    except httpx.HTTPError as exc:
        logger.warning("robots.txt недоступен для %s: %s", base_url, exc)
    return disallow


def fetch_static_competitor_price(
    competitor: CompetitorConfig,
    site_cfg: SitePricesConfig,
    client: HttpClient | None = None,
) -> float | None:
    """Скачать страницу и извлечь минимальную цену (только parser=static)."""
    path = urlparse(competitor.url).path or "/"
    own_client: httpx.Client | None = None
    http = client
    if http is None:
        own_client = httpx.Client(timeout=30.0, follow_redirects=True)
        http = own_client

    try:
        disallow = _robots_disallow(http, competitor.url, site_cfg)
        if not is_path_allowed(path, disallow):
            logger.warning("Путь запрещён robots.txt: %s", competitor.url)
            return None

        _anti_block_pause(site_cfg)
        resp = _request_with_backoff(http, competitor.url, site_cfg)
        if resp.status_code != 200:
            logger.warning("HTTP %s для %s", resp.status_code, competitor.url)
            return None

        price = parse_static_competitor_html(resp.text, competitor)
        if price is None:
            logger.warning("Не удалось распарсить цену: %s", competitor.name)
        else:
            logger.info("Цена конкурента %s: %s RUB", competitor.name, price)
        return price
    except httpx.HTTPError as exc:
        logger.error("Ошибка сбора цены %s: %s", competitor.name, exc)
        return None
    finally:
        if own_client is not None:
            own_client.close()


def collect_competitor_prices(
    competitors: list[CompetitorConfig],
    site_cfg: SitePricesConfig,
    client: HttpClient | None = None,
) -> dict[str, float | None]:
    """Собрать цены по списку конкурентов. Widget — пропуск."""
    result: dict[str, float | None] = {}
    for item in competitors:
        if item.parser in _WIDGET_PARSERS:
            result[item.name] = None
            continue
        if item.parser != "static":
            result[item.name] = None
            continue
        result[item.name] = fetch_static_competitor_price(item, site_cfg, client=client)
    return result
