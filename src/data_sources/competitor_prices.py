"""Парсинг публичных цен конкурентов (static HTML + виджеты, этап 6/7)."""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Protocol, cast
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.config import CompetitorConfig, SitePricesConfig
from src.data_sources.site_prices import (
    is_path_allowed,
    parse_robots_disallow,
)
from src.data_sources.tl_ibe import collect_widget_prices
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

_WIDGET_PARSERS = frozenset({"widget", "tl_widget", "wubook_widget"})


@dataclass
class CompetitorProductPrice:
    """Цена одного объекта/категории конкурента."""

    name: str
    price_from: float


@dataclass
class CollectedCompetitorPrice:
    """Результат сбора цены одного конкурента."""

    price_from: float | None = None
    source: str = "dom"
    screenshot_path: str | None = None
    products: list[CompetitorProductPrice] | None = None

    @property
    def available(self) -> bool:
        return self.price_from is not None


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: object) -> httpx.Response: ...


def _extract_price_digits(raw: str) -> float | None:
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    return float(digits)


def _extract_petrovskie_day_price(text: str) -> float | None:
    """Цена за сутки: «1 сутки - N» или диапазон «2590-3490» (берём нижнюю)."""
    one_night = re.compile(
        r"1\s*сут(?:ки|ок)?\s*[-–—−]\s*([\d\s\u00a0]+)",
        re.IGNORECASE,
    )
    match = one_night.search(text)
    if match:
        return _extract_price_digits(match.group(1))
    for part in text.split("|"):
        part_match = one_night.search(part)
        if part_match:
            return _extract_price_digits(part_match.group(1))

    # Диапазон «от-до» за сутки (актуальный формат каталога).
    range_m = re.search(
        r"(\d[\d\s\u00a0]*)\s*[-–—−]\s*(\d[\d\s\u00a0]*)",
        text,
    )
    if range_m:
        low = _extract_price_digits(range_m.group(1))
        high = _extract_price_digits(range_m.group(2))
        if low is not None and high is not None and 500 <= low <= high <= 200_000:
            return low
    return None


def parse_petrovskie_products(html: str) -> list[CompetitorProductPrice]:
    """Карточки Tilda (.js-product): имя объекта + цена «от» за сутки."""
    soup = BeautifulSoup(html, "lxml")
    products: list[CompetitorProductPrice] = []
    cards = soup.select(".js-product") or soup.select("[class*='t776__product']")
    for card in cards:
        name_el = card.select_one(
            ".js-product-name, .t776__title, [class*='product-name']"
        )
        price_el = card.select_one(".t776__price-value, .js-product-price")
        if price_el is None:
            continue
        price = _extract_petrovskie_day_price(price_el.get_text(" ", strip=True))
        if price is None:
            continue
        name = (
            name_el.get_text(" ", strip=True)
            if name_el is not None
            else "Без названия"
        )
        products.append(CompetitorProductPrice(name=name, price_from=price))
    return products


def parse_petrovskie_html(html: str) -> float | None:
    """Tilda: минимум по объектам (сутки / диапазон), не пакет «3 суток»."""
    products = parse_petrovskie_products(html)
    if products:
        return min(p.price_from for p in products)

    # Фолбэк без карточек — только price-блоки.
    soup = BeautifulSoup(html, "lxml")
    prices: list[float] = []
    for el in soup.select(".t776__price-value, .js-product-price"):
        value = _extract_petrovskie_day_price(el.get_text(" ", strip=True))
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
) -> CollectedCompetitorPrice:
    """Скачать страницу и извлечь минимальную цену (только parser=static)."""
    path = urlparse(competitor.url).path or "/"
    own_client: httpx.Client | None = None
    http: HttpClient | None = client
    if http is None:
        own_client = httpx.Client(timeout=30.0, follow_redirects=True)
        http = cast(HttpClient, own_client)

    try:
        disallow = _robots_disallow(http, competitor.url, site_cfg)
        if not is_path_allowed(path, disallow):
            logger.warning("Путь запрещён robots.txt: %s", competitor.url)
            return CollectedCompetitorPrice()

        _anti_block_pause(site_cfg)
        resp = _request_with_backoff(http, competitor.url, site_cfg)
        if resp.status_code != 200:
            logger.warning("HTTP %s для %s", resp.status_code, competitor.url)
            return CollectedCompetitorPrice()

        products: list[CompetitorProductPrice] | None = None
        if "петровск" in competitor.name.lower():
            products = parse_petrovskie_products(resp.text)
            price = min((p.price_from for p in products), default=None)
        else:
            price = parse_static_competitor_html(resp.text, competitor)

        if price is None:
            logger.warning("Не удалось распарсить цену: %s", competitor.name)
        else:
            logger.info(
                "Цена конкурента %s: %s RUB (объектов: %s)",
                competitor.name,
                price,
                len(products or []),
            )
        return CollectedCompetitorPrice(
            price_from=price,
            source="dom",
            products=products or None,
        )
    except httpx.HTTPError as exc:
        logger.error("Ошибка сбора цены %s: %s", competitor.name, exc)
        return CollectedCompetitorPrice()
    finally:
        if own_client is not None:
            own_client.close()


def collect_competitor_prices(
    competitors: list[CompetitorConfig],
    site_cfg: SitePricesConfig,
    client: HttpClient | None = None,
    *,
    snapshot_date: date | None = None,
    enable_widgets: bool = True,
) -> dict[str, CollectedCompetitorPrice]:
    """Собрать цены: static (BS) + tl_widget/wubook (Playwright)."""
    result: dict[str, CollectedCompetitorPrice] = {}
    for item in competitors:
        if item.parser in _WIDGET_PARSERS:
            continue
        if item.parser != "static":
            result[item.name] = CollectedCompetitorPrice()
            continue
        result[item.name] = fetch_static_competitor_price(
            item, site_cfg, client=client
        )

    widget_map = collect_widget_prices(
        competitors,
        site_cfg,
        snapshot_date=snapshot_date,
        enable_widgets=enable_widgets,
    )
    for name, widget in widget_map.items():
        products = None
        if widget.products:
            products = [
                CompetitorProductPrice(name=p.name, price_from=p.price_from)
                for p in widget.products
            ]
        result[name] = CollectedCompetitorPrice(
            price_from=widget.price_from,
            source=widget.source if widget.price_from is not None else "dom",
            screenshot_path=widget.screenshot_path,
            products=products,
        )
    # Гарантируем ключ для каждого конкурента из конфига.
    for item in competitors:
        result.setdefault(item.name, CollectedCompetitorPrice())
    return result
