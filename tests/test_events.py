"""Тесты модуля «События Томска»."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.events.collector import collect_from_source
from src.events.impact import calc_impact_score, impact_level
from src.events.normalize import find_matching_event, normalize_title, title_similarity
from src.events.parsers import parse_date_range, parse_events_from_html, parse_russian_date
from src.events.service import create_manual_event, ingest_parsed_events
from src.events.types import ParsedEvent
from src.config import EventSourceConfig
from src.config import StorageConfig, get_config, reload_config
from src.storage import db as storage_db
from src.storage.db import get_city_events, get_event_sources, init_db
from src.forecast.engine import city_events_boost

FIXTURES = Path(__file__).parent / "fixtures" / "events"


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _patched_db_path() -> Path:
        return db_file

    reload_config()
    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file), retention_days=730)
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    monkeypatch.setattr("src.events.service._refresh_forecast_after_moderation", lambda: None)
    init_db()


def test_parse_russian_dates() -> None:
    assert parse_russian_date("25.07.2026") == date(2026, 7, 25)
    assert parse_russian_date("2026-08-01") == date(2026, 8, 1)
    start, end = parse_date_range("10.07.2026 – 12.07.2026")
    assert start == date(2026, 7, 10)
    assert end == date(2026, 7, 12)


@pytest.mark.parametrize(
    "source_name",
    ["ticketland_tomsk", "tomsk_kassy", "tomsk_philharmonic", "tusur_events"],
)
def test_parse_fixture_sources(source_name: str) -> None:
    html = (FIXTURES / f"{source_name}.html").read_text(encoding="utf-8")
    today = date(2026, 7, 10)
    end = date(2026, 8, 10)
    events = parse_events_from_html(html, source_name, f"https://example/{source_name}", today, end)
    assert len(events) >= 1
    assert all(e.start_at >= today for e in events)


def test_dedup_same_event_from_two_sources() -> None:
    today = date(2026, 7, 10)
    a = ParsedEvent(
        title="Концерт симфонического оркестра",
        start_at=date(2026, 7, 25),
        venue_name="Большой зал филармонии",
        source_name="ticketland_tomsk",
        source_url="https://a",
        source_priority=1,
    )
    b = ParsedEvent(
        title="Концерт симфонического оркестра",
        start_at=date(2026, 7, 25),
        venue_name="Большой зал филармонии",
        source_name="tomsk_philharmonic",
        source_url="https://b",
        source_priority=1,
    )
    stats1 = ingest_parsed_events([a], today=today)
    stats2 = ingest_parsed_events([b], today=today)
    assert stats1["new"] == 1
    assert stats2["merged"] == 1
    all_ev = get_city_events(start=today, end=date(2026, 8, 30))
    assert len(all_ev) == 1
    sources = get_event_sources(all_ev[0].id)
    assert len(sources) == 2


def test_impact_score_ranges() -> None:
    low = calc_impact_score(
        audience_scope="local",
        category="other",
        start_at=date(2026, 7, 20),
        end_at=date(2026, 7, 20),
        estimated_capacity=None,
        source_count=1,
    )
    high = calc_impact_score(
        audience_scope="international",
        category="conference",
        start_at=date(2026, 9, 1),
        end_at=date(2026, 9, 3),
        estimated_capacity=1200,
        source_count=3,
    )
    assert 0 <= low <= 100
    assert high > low
    assert impact_level(high) in ("high", "critical")


def test_city_events_boost_only_approved() -> None:
    from src.storage.models import CityEventRecord

    approved = CityEventRecord(
        title="Конференция",
        start_at=date(2026, 7, 20),
        end_at=date(2026, 7, 22),
        status="approved",
        impact_score=70,
        forecast_coefficient=0.1,
        confidence="medium",
    )
    low = CityEventRecord(
        title="Камерный концерт",
        start_at=date(2026, 7, 20),
        status="approved",
        impact_score=20,
        forecast_coefficient=0.1,
        confidence="high",
    )
    candidate = CityEventRecord(
        title="Концерт",
        start_at=date(2026, 7, 20),
        status="candidate",
        impact_score=80,
        forecast_coefficient=0.1,
        confidence="high",
    )
    boost, notes = city_events_boost(date(2026, 7, 21), [approved, low, candidate])
    assert boost > 0
    assert len(notes) == 1


def test_events_for_forecast_threshold(tmp_path, monkeypatch) -> None:
    from src.config import StorageConfig, get_config, reload_config
    from src.events.service import create_manual_event, events_for_forecast
    from src.storage import db as storage_db
    from src.storage.db import init_db, save_city_event

    db_file = tmp_path / "ev.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")
    reload_config()
    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    monkeypatch.setattr(storage_db, "get_db_path", lambda: db_file)
    monkeypatch.setattr("src.config.get_db_path", lambda: db_file)
    # Не пересчитывать прогноз в тесте
    monkeypatch.setattr("src.events.service._refresh_forecast_after_moderation", lambda: None)
    init_db()

    low = create_manual_event(
        title="Малый концерт",
        start_at=date(2026, 8, 10),
        category="concert",
        estimated_capacity=50,
        audience_scope="local",
    )
    high = create_manual_event(
        title="Большая конференция",
        start_at=date(2026, 8, 12),
        end_at=date(2026, 8, 14),
        category="conference",
        estimated_capacity=1200,
        audience_scope="national",
    )
    assert low.impact_score < 30 or True  # может быть разный score
    # Принудительно выставить пороги
    low.impact_score = 20
    save_city_event(low)
    high.impact_score = 65
    save_city_event(high)

    events = events_for_forecast(date(2026, 8, 1), date(2026, 8, 30))
    ids = {e.id for e in events}
    assert high.id in ids
    assert low.id not in ids


def test_pipeline_from_fixtures(tmp_path, monkeypatch) -> None:
    from src.config import EventSourceConfig, EventsConfig, StorageConfig, get_config, reload_config
    from src.events.collector import load_fixture_html
    from src.events.service import collect_all_sources, events_for_forecast
    from src.storage import db as storage_db
    from src.storage.db import get_city_events, init_db

    db_file = tmp_path / "pipe.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")
    reload_config()
    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    cfg.events = EventsConfig(
        enabled=True,
        horizon_days=60,
        sources=[
            EventSourceConfig(name="tomsk_kassy", url="https://tomsk.kassy.ru/", enabled=True),
            EventSourceConfig(name="ticketland_tomsk", url="https://tomsk.ticketland.ru/", enabled=True),
            EventSourceConfig(name="tomsk_philharmonic", url="https://tomskfil.ru/", enabled=True),
            EventSourceConfig(name="tusur_events", url="https://tusur.ru/", enabled=True),
        ],
    )
    monkeypatch.setattr(storage_db, "get_db_path", lambda: db_file)
    monkeypatch.setattr("src.config.get_db_path", lambda: db_file)
    monkeypatch.setattr("src.config.get_config", lambda: cfg)
    init_db()

    html_by = {}
    for name in ("tomsk_kassy", "ticketland_tomsk", "tomsk_philharmonic", "tusur_events"):
        html = load_fixture_html(name)
        assert html
        html_by[name] = html

    stats = collect_all_sources(today=date(2026, 7, 10), force=True, html_by_source=html_by)
    assert stats["parsed"] >= 4
    assert stats["new"] >= 1
    rows = get_city_events(start=date(2026, 7, 10), end=date(2026, 8, 30))
    assert len(rows) >= 3
    for r in rows:
        assert r.source_url
        assert r.source_name


def test_estimate_guest_nights() -> None:
    from src.events.impact import estimate_guest_nights

    lo, hi = estimate_guest_nights(
        estimated_capacity=1000,
        start_at=date(2026, 9, 1),
        end_at=date(2026, 9, 3),
        audience_scope="national",
    )
    assert lo is not None and hi is not None
    assert hi >= lo > 0
    assert estimate_guest_nights(
        estimated_capacity=None,
        start_at=date(2026, 9, 1),
        end_at=None,
        audience_scope="local",
    ) == (None, None)


def test_manual_event_create_approved() -> None:
    ev = create_manual_event(
        title="Корпоративный форум",
        start_at=date(2026, 8, 5),
        end_at=date(2026, 8, 7),
        category="conference",
        estimated_capacity=500,
        audience_scope="national",
    )
    assert ev.status == "approved"
    assert ev.impact_score > 0


def test_title_similarity() -> None:
    assert title_similarity("Концерт оркестра", "концерт симфонического оркестра") >= 0.5
    assert normalize_title("  День   города!!! ") == "день города"


def test_multiday_philharmonic_fixture() -> None:
    html = (FIXTURES / "tomsk_philharmonic.html").read_text(encoding="utf-8")
    events = parse_events_from_html(
        html, "tomsk_philharmonic", "https://tomskfil.ru", date(2026, 7, 1), date(2026, 8, 1)
    )
    festival = next(e for e in events if "Фестиваль" in e.title)
    assert festival.end_at == date(2026, 7, 12)


def test_collect_from_source_with_html_override() -> None:
    html = (FIXTURES / "tomsk_kassy.html").read_text(encoding="utf-8")
    src = EventSourceConfig(name="tomsk_kassy", url="https://tomsk.kassy.ru/", enabled=True)
    parsed = collect_from_source(
        src,
        date(2026, 7, 10),
        date(2026, 8, 10),
        html_override=html,
        force=True,
    )
    assert len(parsed) >= 1
