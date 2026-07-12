"""Тесты парсинга цен конкурентов (static HTML, этап 6/7)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from src.config import CompetitorConfig, SitePricesConfig, reload_config
from src.data_sources.competitor_prices import (
    collect_competitor_prices,
    parse_gogol_html,
    parse_kuhterin_html,
    parse_petrovskie_html,
    parse_static_competitor_html,
)
from src.data_sources.market_trends import fetch_competitor_prices

FIXTURES = Path(__file__).parent / "fixtures" / "competitors"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_petrovskie_fixture() -> None:
    html = _read_fixture("petrovskie.html")
    assert parse_petrovskie_html(html) == 12000.0


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
    assert parse_static_competitor_html(_read_fixture("petrovskie.html"), petrovskie) == 12000.0
    assert parse_static_competitor_html(_read_fixture("gogol.html"), gogol) == 3600.0
    assert parse_static_competitor_html(_read_fixture("kuhterin.html"), kuhterin) == 4500.0


def test_collect_competitor_prices_skips_widgets() -> None:
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
    result = collect_competitor_prices(competitors, site_cfg, client=mock_client)
    assert result["Гоголь"] == 3600.0
    assert result["Bon Apart"] is None


def test_fetch_competitor_prices_marks_widget_unavailable(monkeypatch) -> None:
    cfg = reload_config()
    monkeypatch.setattr(
        "src.data_sources.market_trends.collect_competitor_prices",
        lambda competitors, site_cfg, client=None: {
            "Апартаменты Петровские": 12000.0,
            "Гоголь": 3600.0,
            "Кухтерин": 4500.0,
            "Bon Apart (Банапарт)": None,
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
