"""Тесты парсинга статического HTML и сбора snapshot цен (без сети)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from src.config import AppConfig, SitePricesConfig
from src.data_sources.site_prices import (
    PriceSnapshot,
    SnapshotCollectionResult,
    collect_price_snapshots,
    is_path_allowed,
    load_cached_snapshots,
    parse_category_html,
    parse_robots_disallow,
    save_cached_snapshots,
)

FIXTURE = Path(__file__).parent / "fixtures" / "category_page.html"
ROBOTS_FIXTURE = """User-agent: *
Disallow: /manager/
"""


def _site_config(**overrides: object) -> SitePricesConfig:
    defaults = {
        "base_url": "https://1apart.ru",
        "category_urls": ["/1room23", "/1room"],
        "request_delay_min_sec": 0.01,
        "request_delay_max_sec": 0.02,
        "backoff_initial_sec": 0.01,
        "backoff_max_sec": 0.05,
        "max_retries": 2,
        "snapshot_cache_path": "data/test_price_snapshots.json",
    }
    defaults.update(overrides)
    return SitePricesConfig(**defaults)


def test_parse_price_from_text_ot_rub() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    result = parse_category_html(html, "1room23")
    assert result is not None
    assert result.category == "1room23"
    assert result.price == 4500.0


def test_parse_data_price_attribute() -> None:
    html = '<div data-price="5000">от 5000 руб</div>'
    result = parse_category_html(html, "1room")
    assert result is not None
    assert result.price == 5000.0


def test_parse_price_value_class() -> None:
    html = '<div class="price-value">3 200 ₽</div>'
    result = parse_category_html(html, "2room")
    assert result is not None
    assert result.price == 3200.0


def test_parse_missing_price() -> None:
    html = "<html><body><h1>Нет цены</h1></body></html>"
    assert parse_category_html(html, "1room") is None


def test_parse_robots_disallow() -> None:
    paths = parse_robots_disallow(ROBOTS_FIXTURE)
    assert "/manager/" in paths


def test_is_path_allowed() -> None:
    assert is_path_allowed("/1room", ["/manager/"]) is True
    assert is_path_allowed("/manager/admin", ["/manager/"]) is False


def test_cache_roundtrip(tmp_path: Path) -> None:
    cfg = _site_config(snapshot_cache_path=str(tmp_path / "cache.json"))
    now = datetime(2026, 7, 7, 9, 0, 0)
    snapshots = [
        PriceSnapshot(
            snapshot_at=now,
            category="1room23",
            price=4500.0,
            url="https://1apart.ru/1room23",
        )
    ]
    save_cached_snapshots(cfg, snapshots)
    loaded = load_cached_snapshots(cfg)
    assert len(loaded) == 1
    assert loaded[0].category == "1room23"
    assert loaded[0].price == 4500.0


def _mock_response(text: str, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://1apart.ru/test")
    return httpx.Response(status_code=status_code, text=text, request=request)


def test_collect_snapshots_success(tmp_path: Path) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    client = MagicMock()
    client.get.side_effect = [
        _mock_response(ROBOTS_FIXTURE),
        _mock_response(html),
        _mock_response(html),
    ]
    cfg = AppConfig(
        site_prices=_site_config(
            category_urls=["/1room23", "/1room"],
            snapshot_cache_path=str(tmp_path / "cache.json"),
        )
    )

    result = collect_price_snapshots(config=cfg, client=client)
    assert isinstance(result, SnapshotCollectionResult)
    assert result.used_fallback is False
    assert result.fetched_count == 2
    assert len(result.snapshots) == 2
    assert all(isinstance(s, PriceSnapshot) for s in result.snapshots)
    assert tmp_path.joinpath("cache.json").exists()


def test_collect_snapshots_fallback_to_cache(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    cached = [
        {
            "snapshot_at": "2026-07-06T09:00:00+03:00",
            "category": "1room23",
            "price": 4500.0,
            "source": "site",
            "currency": "RUB",
            "url": "https://1apart.ru/1room23",
            "is_fallback": False,
        }
    ]
    cache_file.write_text(json.dumps(cached), encoding="utf-8")

    client = MagicMock()
    client.get.side_effect = [
        _mock_response(ROBOTS_FIXTURE),
        httpx.HTTPError("403"),
    ]

    cfg = AppConfig(
        site_prices=_site_config(
            category_urls=["/1room23"],
            snapshot_cache_path=str(cache_file),
            max_retries=1,
        )
    )

    result = collect_price_snapshots(config=cfg, client=client)
    assert result.used_fallback is True
    assert len(result.snapshots) == 1
    assert result.snapshots[0].is_fallback is True
    assert result.snapshots[0].price == 4500.0


def test_collect_skips_robots_disallowed_path(tmp_path: Path) -> None:
    client = MagicMock()
    client.get.return_value = _mock_response(
        "User-agent: *\nDisallow: /manager/\nDisallow: /1room23\n"
    )
    cfg = AppConfig(
        site_prices=_site_config(
            category_urls=["/1room23"],
            snapshot_cache_path=str(tmp_path / "cache.json"),
        )
    )
    result = collect_price_snapshots(config=cfg, client=client)
    assert result.fetched_count == 0
