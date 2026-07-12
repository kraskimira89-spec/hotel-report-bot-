"""Тесты хелперов раздела «Конкуренты»."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.config import StorageConfig, reload_config
from src.storage import db as storage_db
from src.storage.db import init_db, save_competitor_prices
from src.storage.models import CompetitorPriceRecord
from src.web import queries


@pytest.fixture
def competitor_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "competitors.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")
    reload_config()

    def _path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _path)
    monkeypatch.setattr("src.config.get_db_path", _path)
    init_db()
    save_competitor_prices(
        [
            CompetitorPriceRecord(
                competitor_name="Гоголь",
                date=date(2026, 7, 1),
                price_from=3600.0,
                available=True,
                source="dom",
            ),
            CompetitorPriceRecord(
                competitor_name="Гоголь",
                date=date(2026, 7, 7),
                price_from=3800.0,
                available=True,
                source="dom",
            ),
            CompetitorPriceRecord(
                competitor_name="Кухтерин",
                date=date(2026, 7, 6),
                price_from=4500.0,
                available=True,
                source="dom",
            ),
        ]
    )
    cfg = reload_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    return db_file


def test_get_competitor_latest_and_history(competitor_db: Path) -> None:
    _ = competitor_db
    latest = queries.get_competitor_latest()
    gogol = next(r for r in latest if r["name"] == "Гоголь")
    assert gogol["price_from"] == 3800.0
    assert gogol["updated_at"] == "2026-07-07"

    history = queries.get_competitor_history("Гоголь", days=90)
    assert len(history) == 2
    assert history[0]["date"] == "2026-07-07"
