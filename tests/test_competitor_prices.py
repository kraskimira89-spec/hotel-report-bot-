"""Тесты парсинга цен конкурентов (static HTML, этап 6/7)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from src.config import CompetitorConfig, SitePricesConfig, reload_config
from src.data_sources.competitor_prices import (
    collect_competitor_prices,
    parse_central_catalog,
    parse_central_html,
    parse_gogol_html,
    parse_kuhterin_html,
    parse_petrovskie_html,
    parse_petrovskie_products,
    parse_static_competitor_html,
    parse_xander_catalog,
    parse_xander_html,
)
from src.data_sources.market_trends import fetch_competitor_prices

FIXTURES = Path(__file__).parent / "fixtures" / "competitors"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_petrovskie_fixture() -> None:
    html = _read_fixture("petrovskie.html")
    # Минимум по объектам: диапазон 2590-3490, не пакет «1 сутки 12000».
    assert parse_petrovskie_html(html) == 2590.0
    products = parse_petrovskie_products(html)
    assert len(products) == 4
    by_name = {p.name: p.price_from for p in products}
    assert by_name["ПУШКИНА 61/2"] == 2590.0
    assert by_name["НОВЫЙ КИРЕЕВСК"] == 12000.0


def test_parse_gogol_fixture() -> None:
    html = _read_fixture("gogol.html")
    assert parse_gogol_html(html) == 3600.0


def test_parse_kuhterin_fixture() -> None:
    html = _read_fixture("kuhterin.html")
    assert parse_kuhterin_html(html) == 4500.0


def test_parse_static_by_config_selectors() -> None:
    petrovskie = CompetitorConfig(
        name="Апартаменты Петровские",
        type="direct",
        url="https://apartment.tomsk.ru/",
        parser="static",
        selectors={"price": ".t776__price-value"},
    )
    gogol = CompetitorConfig(
        name="Гоголь",
        type="direct",
        url="https://gogolhotel.ru/",
        parser="static",
        selectors={"price_regex": r"Цена от\s*([\d\s]+)\s*руб"},
    )
    kuhterin = CompetitorConfig(
        name="Кухтерин",
        type="indirect",
        url="https://kuhterinhotel.ru/catalog/catalog/",
        parser="static",
        selectors={"price_block": ".price"},
    )
    assert parse_static_competitor_html(_read_fixture("petrovskie.html"), petrovskie) == 2590.0
    assert parse_static_competitor_html(_read_fixture("gogol.html"), gogol) == 3600.0
    assert parse_static_competitor_html(_read_fixture("kuhterin.html"), kuhterin) == 4500.0


def test_collect_competitor_prices_skips_widgets_when_disabled() -> None:
    reload_config()
    site_cfg = SitePricesConfig(
        user_agent="test-agent",
        request_delay_min_sec=0,
        request_delay_max_sec=0,
    )
    mock_client = MagicMock()
    mock_client.get.return_value = httpx.Response(
        200,
        text=_read_fixture("gogol.html"),
        request=httpx.Request("GET", "https://gogolhotel.ru/"),
    )

    competitors = [
        CompetitorConfig(
            name="Гоголь",
            type="direct",
            url="https://gogolhotel.ru/",
            parser="static",
            selectors={"price_regex": r"Цена от\s*([\d\s]+)\s*руб"},
        ),
        CompetitorConfig(
            name="Bon Apart",
            type="direct",
            url="https://www.bon-apart.ru/",
            parser="tl_widget",
        ),
    ]
    result = collect_competitor_prices(
        competitors,
        site_cfg,
        client=mock_client,
        enable_widgets=False,
    )
    assert result["Гоголь"].price_from == 3600.0
    assert result["Bon Apart"].price_from is None
    assert result["Bon Apart"].available is False


def test_fetch_competitor_prices_marks_widget_unavailable(monkeypatch) -> None:
    from src.data_sources.competitor_prices import CollectedCompetitorPrice

    cfg = reload_config()
    monkeypatch.setattr(
        "src.data_sources.market_trends.collect_competitor_prices",
        lambda competitors, site_cfg, client=None, **kwargs: {
            "Апартаменты Петровские": CollectedCompetitorPrice(price_from=12000.0),
            "Гоголь": CollectedCompetitorPrice(price_from=3600.0),
            "Кухтерин": CollectedCompetitorPrice(price_from=4500.0),
            "Bon Apart (Банапарт)": CollectedCompetitorPrice(),
        },
    )
    monkeypatch.setattr(
        "src.storage.db.get_competitor_prices_latest",
        lambda: [],
    )
    items = fetch_competitor_prices(date(2026, 7, 1), date(2026, 7, 7))
    by_name = {i.name: i for i in items}
    assert len(by_name) == len(cfg.competitors)
    assert by_name["Апартаменты Петровские"].available is True
    assert by_name["Апартаменты Петровские"].price_from == 12000.0
    assert by_name["Bon Apart (Банапарт)"].available is False


def test_parse_central_catalog_fixture() -> None:
    html = _read_fixture("central_rooms.html")
    products = parse_central_catalog(html)
    assert len(products) == 6
    by_price = sorted(p.price_from for p in products)
    assert by_price[0] == 4400.0
    assert by_price[-1] == 5800.0
    assert parse_central_html(html) == 4400.0


def test_parse_xander_catalog_fixture() -> None:
    html = _read_fixture("xander_catalog.html")
    products = parse_xander_catalog(html)
    assert len(products) == 5
    by_name = {p.name.replace("\n", " ").strip(): p.price_from for p in products}
    assert by_name["Стандарт"] == 7600.0
    assert by_name["Люкс"] == 11900.0
    assert parse_xander_html(html) == 7600.0


def test_catalog_fallback_for_central_when_widget_empty(monkeypatch) -> None:
    site_cfg = SitePricesConfig(
        user_agent="test-agent",
        request_delay_min_sec=0,
        request_delay_max_sec=0,
    )
    mock_client = MagicMock()
    mock_client.get.return_value = httpx.Response(
        200,
        text=_read_fixture("central_rooms.html"),
        request=httpx.Request("GET", "http://centraltomsk.ru/rooms/"),
    )
    central = CompetitorConfig(
        name="Центральный",
        type="direct",
        url="http://centraltomsk.ru/",
        catalog_url="http://centraltomsk.ru/rooms/",
        parser="tl_widget",
    )
    monkeypatch.setattr(
        "src.data_sources.competitor_prices.collect_widget_prices",
        lambda *a, **k: {"Центральный": type("W", (), {
            "price_from": None, "source": "dom", "screenshot_path": None,
            "products": None, "error": "widget fail",
        })()},
    )
    result = collect_competitor_prices(
        [central], site_cfg, client=mock_client, enable_widgets=True
    )
    row = result["Центральный"]
    assert row.price_from == 4400.0
    assert row.price_kind == "public_from"
    assert row.source == "static_html"
    assert row.products is not None
    assert len(row.products) == 6
