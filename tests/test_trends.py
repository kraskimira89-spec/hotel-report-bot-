"""Тесты раздела «Тренды»."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import StorageConfig, reload_config
from src.data_sources.market_trends import (
    TREND_SEEDS,
    TrendItem,
    fetch_market_trends,
    seed_trends_if_empty,
)
from src.storage import db as storage_db
from src.storage.db import init_db, trends_count
from src.web import queries

RSS_SAMPLE = """<?xml version="1.0"?>
<rss><channel>
<item>
<title>Hotel AI automation grows in 2026</title>
<link>https://example.com/ai</link>
<description>Agents handle guest requests automatically.</description>
<pubDate>Mon, 07 Jul 2026 10:00:00 GMT</pubDate>
</item>
</channel></rss>
"""


@pytest.fixture
def trends_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "trends.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")
    reload_config()

    def _path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _path)
    monkeypatch.setattr("src.config.get_db_path", _path)
    init_db()
    cfg = reload_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    return db_file


def test_fetch_market_trends_with_mock_rss(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200
        text = RSS_SAMPLE

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url: str, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("src.data_sources.market_trends.httpx.Client", FakeClient)
    items = fetch_market_trends(period_days=30, region="world")
    assert items
    assert all(isinstance(i, TrendItem) for i in items)
    assert items[0].title


def test_seed_trends_if_empty(trends_db: Path) -> None:
    _ = trends_db
    assert trends_count() == 0
    saved = seed_trends_if_empty()
    assert saved == len(TREND_SEEDS)
    assert trends_count() == len(TREND_SEEDS)
    assert seed_trends_if_empty() == 0


def test_get_trends_filters(trends_db: Path) -> None:
    _ = trends_db
    seed_trends_if_empty()
    all_ru = queries.get_trends(region="ru", category=None, days=90)
    assert all_ru
    assert all(t["region"] == "ru" for t in all_ru)

    ai = queries.get_trends(region=None, category="Технологии и ИИ", days=90)
    assert ai
    assert all(t["category"] == "Технологии и ИИ" for t in ai)

    idea = queries.get_idea_of_week()
    assert idea is not None
    assert idea["title"]
