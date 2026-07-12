"""Тесты справочника конкурентов и трендов."""

from __future__ import annotations

from src.config import reload_config
from src.web.market_intel import build_competitor_cards, competitor_summary, get_all_trends


def test_build_competitor_cards_from_config() -> None:
    reload_config()
    cards = build_competitor_cards()
    assert len(cards) == 9
    assert "name" in cards[0]
    assert "vs_1apart" in cards[0]
    names = {c["name"] for c in cards}
    assert "Гоголь" in names
    assert "Апартаменты Петровские" in names


def test_competitor_summary() -> None:
    cards = [
        {"type": "direct", "available": True, "parser": "static"},
        {"type": "indirect", "available": False, "parser": "tl_widget"},
    ]
    summary = competitor_summary(cards)
    assert summary["total"] == 2
    assert summary["direct"] == 1
    assert summary["with_price"] == 1


def test_get_all_trends() -> None:
    data = get_all_trends()
    assert len(data["tomsk"]) >= 3
    assert len(data["global"]) >= 3
    assert len(data["ideas"]) >= 2
