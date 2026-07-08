"""Сбор базовых цен категорий со статического HTML 1apart.ru (httpx + BeautifulSoup)."""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.config import AppConfig, SitePricesConfig, get_config
from src.storage.db import save_error_log
from src.storage.models import ErrorLogRecord
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

SOURCE_SITE = "site"

# TODO: этап 7 — цены на конкретные даты (Price Optimizer) только через TravelLine API.


class PriceSnapshot(BaseModel):
    """Snapshot базовой цены категории."""

    snapshot_at: datetime
    category: str
    price: float
    source: str = SOURCE_SITE
    currency: str = "RUB"
    url: str = ""
    is_fallback: bool = False


class SnapshotCollectionResult(BaseModel):
    """Результат сбора snapshot цен."""

    snapshots: list[PriceSnapshot] = Field(default_factory=list)
    used_fallback: bool = False
    fetched_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> httpx.Response: ...


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _cache_path(cfg: SitePricesConfig) -> Path:
    path = Path(cfg.snapshot_cache_path)
    if not path.is_absolute():
        path = _project_root() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_msk(config: AppConfig) -> datetime:
    tz = ZoneInfo(config.property.timezone)
    return datetime.now(tz)


def _extract_price_digits(raw: str) -> float | None:
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    return float(digits)


def parse_category_html(
    html: str,
    category_slug: str,
    selectors: SitePricesConfig | None = None,
) -> PriceSnapshot | None:
    """Распарсить HTML страницы категории и извлечь цену «от N руб»."""
    site_cfg = selectors or get_config().site_prices
    sel = site_cfg.selectors
    soup = BeautifulSoup(html, "lxml")

    price_el = soup.select_one(sel.data_price) or soup.select_one(sel.price_value)
    if price_el is not None:
        raw = price_el.get("data-price") or price_el.get_text(" ", strip=True)
        price = _extract_price_digits(raw)
        if price is not None:
            return _make_snapshot_stub(category_slug, price)

    pattern = re.compile(sel.price_from_regex, re.IGNORECASE)
    text = soup.get_text(" ", strip=True)
    match = pattern.search(text)
    if match:
        price = _extract_price_digits(match.group(1))
        if price is not None:
            return _make_snapshot_stub(category_slug, price)

    return None


def _make_snapshot_stub(category: str, price: float) -> PriceSnapshot:
    """Временный snapshot без даты (заполняется при сборе)."""
    return PriceSnapshot(
        snapshot_at=datetime.now(),
        category=category,
        price=price,
        source=SOURCE_SITE,
    )


def parse_robots_disallow(robots_txt: str) -> list[str]:
    """Извлечь Disallow-пути из robots.txt."""
    paths: list[str] = []
    for line in robots_txt.splitlines():
        line = line.strip()
        if not line.lower().startswith("disallow:"):
            continue
        path = line.split(":", 1)[1].strip()
        if path:
            paths.append(path)
    return paths


def is_path_allowed(path: str, disallow_paths: list[str]) -> bool:
    """Проверить, разрешён ли путь согласно robots.txt / config."""
    for disallow in disallow_paths:
        if path.startswith(disallow):
            return False
    return True


def load_cached_snapshots(cfg: SitePricesConfig) -> list[PriceSnapshot]:
    """Загрузить последний успешный snapshot из кэша."""
    path = _cache_path(cfg)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [PriceSnapshot.model_validate(item) for item in data]
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Не удалось прочитать кэш snapshot: %s", exc)
        return []


def save_cached_snapshots(
    cfg: SitePricesConfig,
    snapshots: list[PriceSnapshot],
) -> None:
    """Сохранить успешный snapshot в кэш."""
    if not snapshots:
        return
    path = _cache_path(cfg)
    payload = [s.model_dump(mode="json") for s in snapshots]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _anti_block_pause(cfg: SitePricesConfig) -> None:
    pause = random.uniform(cfg.request_delay_min_sec, cfg.request_delay_max_sec)
    time.sleep(pause)


def _request_with_backoff(
    client: HttpClient,
    url: str,
    cfg: SitePricesConfig,
) -> httpx.Response:
    """HTTP-запрос с backoff (единый helper)."""
    return retry_with_backoff(
        lambda: client.get(url),
        retries=cfg.max_retries,
        backoff_initial=cfg.backoff_initial_sec,
        backoff_max=cfg.backoff_max_sec,
        retry_statuses=(403, 429, 503, 500, 502, 504),
        log_prefix=f"site_prices {url}",
    )


def _fetch_robots_disallow(
    client: HttpClient,
    site_cfg: SitePricesConfig,
) -> list[str]:
    """Получить disallow-пути: config + robots.txt."""
    disallow = list(site_cfg.robots_disallow_paths)
    robots_url = urljoin(site_cfg.base_url, "/robots.txt")
    try:
        resp = client.get(robots_url)
        if resp.status_code == 200:
            for path in parse_robots_disallow(resp.text):
                if path not in disallow:
                    disallow.append(path)
    except httpx.HTTPError as exc:
        logger.warning("robots.txt недоступен, используем config: %s", exc)
    return disallow


def collect_price_snapshots(
    config: AppConfig | None = None,
    client: HttpClient | None = None,
) -> SnapshotCollectionResult:
    """Собрать базовые цены по всем категориям (последовательно, с анти-блоком).

    При полной неудаче возвращает последний успешный snapshot из кэша.
    """
    cfg = config or get_config()
    site_cfg = cfg.site_prices
    snapshots: list[PriceSnapshot] = []
    now = _now_msk(cfg)

    own_client: httpx.Client | None = None
    http = client
    if http is None:
        own_client = httpx.Client(
            headers={"User-Agent": site_cfg.user_agent},
            timeout=30.0,
            follow_redirects=True,
        )
        http = own_client

    try:
        disallow_paths = _fetch_robots_disallow(http, site_cfg)

        for path in site_cfg.category_urls:
            url = urljoin(site_cfg.base_url, path)
            slug = path.rstrip("/").split("/")[-1] or path

            if not is_path_allowed(path, disallow_paths):
                logger.warning("Путь запрещён robots.txt: %s", path)
                continue

            _anti_block_pause(site_cfg)

            try:
                resp = _request_with_backoff(http, url, site_cfg)
                parsed = parse_category_html(resp.text, slug, site_cfg)
                if parsed is None:
                    logger.warning("Не удалось распарсить цену: %s", url)
                    continue
                snapshot = parsed.model_copy(
                    update={
                        "snapshot_at": now,
                        "url": url,
                        "is_fallback": False,
                    }
                )
                snapshots.append(snapshot)
                logger.info("Цена %s: %s RUB (%s)", slug, snapshot.price, url)
            except httpx.HTTPError as exc:
                logger.error("Ошибка сбора цен %s: %s", url, exc)

        if snapshots:
            save_cached_snapshots(site_cfg, snapshots)
            return SnapshotCollectionResult(
                snapshots=snapshots,
                used_fallback=False,
                fetched_count=len(snapshots),
            )

        cached = load_cached_snapshots(site_cfg)
        if cached:
            warning = (
                "Сбор цен недоступен, часть данных из последнего снимка"
            )
            logger.warning(
                "Сбор не удался, возвращаем последний успешный snapshot (%s записей)",
                len(cached),
            )
            save_error_log(
                ErrorLogRecord(
                    error_date=now.date(),
                    source="site_prices",
                    error_type="fallback",
                    message=warning,
                    details=f"cached={len(cached)}",
                )
            )
            fallback = [
                s.model_copy(update={"is_fallback": True}) for s in cached
            ]
            return SnapshotCollectionResult(
                snapshots=fallback,
                used_fallback=True,
                fetched_count=0,
                warnings=[warning],
            )

        logger.error("Нет цен и нет кэшированного snapshot")
        save_error_log(
            ErrorLogRecord(
                error_date=now.date(),
                source="site_prices",
                error_type="no_data",
                message="Нет цен и нет кэшированного snapshot",
            )
        )
        return SnapshotCollectionResult(warnings=["Нет цен и нет кэшированного snapshot"])

    finally:
        if own_client is not None:
            own_client.close()


def fetch_category_prices(
    config: AppConfig | None = None,
    client: HttpClient | None = None,
) -> list[PriceSnapshot]:
    """Собрать snapshot цен (обёртка для планировщика)."""
    result = collect_price_snapshots(config=config, client=client)
    return result.snapshots
