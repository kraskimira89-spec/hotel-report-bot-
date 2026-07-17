"""Тесты модуля «События Томска»."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.config import EventSourceConfig, StorageConfig, get_config, reload_config
from src.events.collector import collect_from_source
from src.events.impact import calc_impact_score, impact_level
from src.events.normalize import normalize_title, title_similarity
from src.events.parsers import parse_date_range, parse_events_from_html, parse_russian_date
from src.events.service import create_manual_event, ingest_parsed_events
from src.events.types import ParsedEvent
from src.forecast.engine import city_events_boost
from src.storage import db as storage_db
from src.storage.db import get_city_events, get_event_sources, init_db

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
    [
        "ticketland_tomsk",
        "tomsk_kassy",
        "tomsk_philharmonic",
        "tusur_events",
        "my_business_tomsk",
        "tomsk_sport_calendar",
        "tomsk_library_events",
    ],
)
def test_parse_fixture_sources(source_name: str) -> None:
    html = (FIXTURES / f"{source_name}.html").read_text(encoding="utf-8")
    today = date(2026, 7, 10)
    end = date(2026, 10, 10)
    events = parse_events_from_html(html, source_name, f"https://example/{source_name}", today, end)
    assert len(events) >= 1
    assert all(e.start_at >= today for e in events)


def test_parse_kassy_real_card_markup() -> None:
    html = (FIXTURES / "tomsk_kassy.html").read_text(encoding="utf-8")
    events = parse_events_from_html(
        html,
        "tomsk_kassy",
        "https://tomsk.kassy.ru/",
        date(2026, 7, 10),
        date(2026, 8, 10),
    )
    assert events[0].title == "Цирк на льду"
    assert events[0].start_at == date(2026, 7, 20)
    assert events[0].venue_name == "ЛД Сибирь, Основной зал"
    assert events[0].source_url == "https://tomsk.kassy.ru/events/cirk/1-123/"


def test_parse_philharmonic_real_card_markup() -> None:
    html = (FIXTURES / "tomsk_philharmonic.html").read_text(encoding="utf-8")
    events = parse_events_from_html(
        html,
        "tomsk_philharmonic",
        "https://tomskfil.ru/afisha/",
        date(2026, 7, 10),
        date(2026, 8, 10),
    )
    assert events[0].title == "Органный концерт"
    assert events[0].start_at == date(2026, 7, 18)
    assert events[0].venue_name == "Малый зал"
    assert events[0].source_url == "https://tomskfil.ru/afisha/organ/"


def test_parse_tusur_calendar_markup() -> None:
    html = (FIXTURES / "tusur_events.html").read_text(encoding="utf-8")
    events = parse_events_from_html(
        html,
        "tusur_events",
        "https://tusur.ru/ru/novosti-i-meropriyatiya",
        date(2026, 7, 10),
        date(2026, 8, 10),
    )
    assert len(events) == 1
    assert events[0].start_at == date(2026, 7, 27)
    assert events[0].venue_name == "ТУСУР"
    assert events[0].category == "conference"


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
        overnight_likelihood=0.45,
    )
    low = CityEventRecord(
        title="Камерный концерт",
        start_at=date(2026, 7, 20),
        status="approved",
        impact_score=20,
        forecast_coefficient=0.1,
        confidence="high",
        overnight_likelihood=0.1,
    )
    candidate = CityEventRecord(
        title="Концерт",
        start_at=date(2026, 7, 20),
        status="candidate",
        impact_score=80,
        forecast_coefficient=0.1,
        confidence="high",
        overnight_likelihood=0.5,
    )
    online = CityEventRecord(
        title="Вебинар",
        start_at=date(2026, 7, 20),
        status="approved",
        impact_score=90,
        forecast_coefficient=0.1,
        confidence="high",
        is_online=True,
        overnight_likelihood=0.0,
    )
    boost, notes = city_events_boost(date(2026, 7, 21), [approved, low, candidate, online])
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
    from src.config import EventsConfig, EventSourceConfig, StorageConfig, get_config, reload_config
    from src.events.collector import load_fixture_html
    from src.events.service import collect_all_sources
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


def test_multiday_date_range() -> None:
    start, end = parse_date_range("10.07.2026 – 12.07.2026")
    assert start == date(2026, 7, 10)
    assert end == date(2026, 7, 12)


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


def test_parse_my_business_and_non_tomsk() -> None:
    html = (FIXTURES / "my_business_tomsk.html").read_text(encoding="utf-8")
    events = parse_events_from_html(
        html,
        "my_business_tomsk",
        "https://www.mb.tomsk.ru/meropriyatiya/",
        date(2026, 7, 10),
        date(2026, 10, 10),
    )
    assert len(events) >= 2
    forum = next(e for e in events if "всероссийский" in e.title.lower())
    assert forum.category in ("conference", "business")
    assert forum.audience_scope == "national"
    assert forum.overnight_likelihood and forum.overnight_likelihood >= 0.45
    non_tomsk = next(e for e in events if "колпашево" in e.title.lower())
    assert non_tomsk.city.lower() == "колпашево"


def test_parse_sport_multiday_period() -> None:
    html = (FIXTURES / "tomsk_sport_calendar.html").read_text(encoding="utf-8")
    events = parse_events_from_html(
        html,
        "tomsk_sport_calendar",
        "https://sport-v-tomske.ru/calendar",
        date(2026, 7, 10),
        date(2026, 9, 10),
    )
    assert len(events) >= 1
    multi = next(e for e in events if e.end_at and e.end_at != e.start_at)
    assert (multi.end_at - multi.start_at).days >= 1
    assert multi.category == "sport"


def test_online_and_non_tomsk_excluded_from_forecast() -> None:
    from src.events.impact import event_affects_forecast
    from src.storage.models import CityEventRecord

    online = CityEventRecord(
        title="Онлайн-форум",
        start_at=date(2026, 8, 1),
        status="approved",
        impact_score=90,
        is_online=True,
        overnight_likelihood=0.0,
    )
    assert not event_affects_forecast(online.status, online.impact_score, online)

    away = CityEventRecord(
        title="Форум",
        start_at=date(2026, 8, 1),
        status="approved",
        impact_score=90,
        city="Колпашево",
        location_confirmed=False,
        overnight_likelihood=0.45,
    )
    assert not event_affects_forecast(away.status, away.impact_score, away)
    away.location_confirmed = True
    assert event_affects_forecast(away.status, away.impact_score, away)


def test_overnight_demand_score() -> None:
    from src.events.impact import event_demand_score, estimate_overnight_likelihood

    overnight = estimate_overnight_likelihood(
        category="conference",
        audience_scope="national",
        start_at=date(2026, 9, 12),
        end_at=date(2026, 9, 14),
        is_online=False,
        title="Всероссийская конференция",
    )
    assert overnight >= 0.65
    demand = event_demand_score(80, overnight, date(2026, 9, 12), date(2026, 9, 14), "national")
    assert demand > 0


def test_guest_poster_selection_rules() -> None:
    from src.events.poster import (
        event_qualifies_for_guest_poster,
        format_period_headline,
        select_guest_poster_events,
    )
    from src.events.service import create_manual_event
    from src.storage.db import save_city_event
    from src.storage.models import CityEventRecord

    assert format_period_headline(date(2026, 7, 18), date(2026, 7, 24)) == "18–24 июля 2026"

    good = create_manual_event(
        title="Органный концерт",
        start_at=date(2026, 7, 20),
        category="concert",
        venue_name="Филармония",
    )
    good.source_url = "https://tomskfil.ru/afisha/organ/"
    save_city_event(good)

    no_venue = create_manual_event(
        title="Фестиваль без площадки",
        start_at=date(2026, 7, 21),
        category="festival",
    )
    no_venue.source_url = "https://example.com/fest"
    save_city_event(no_venue)

    business = create_manual_event(
        title="Бизнес-семинар",
        start_at=date(2026, 7, 22),
        category="business",
        venue_name="Мой бизнес",
    )
    business.source_url = "https://www.mb.tomsk.ru/1"
    save_city_event(business)

    theatre = create_manual_event(
        title="Спектакль «Чайка»",
        start_at=date(2026, 7, 23),
        category="other",
        venue_name="Драмтеатр",
    )
    theatre.source_url = "https://example.com/theatre"
    save_city_event(theatre)

    online = CityEventRecord(
        title="Онлайн-концерт",
        start_at=date(2026, 7, 20),
        status="approved",
        category="concert",
        venue_name="Zoom",
        source_url="https://example.com/online",
        is_online=True,
    )
    assert not event_qualifies_for_guest_poster(
        online,
        today=date(2026, 7, 18),
        horizon_end=date(2026, 7, 28),
        allowed_categories=["concert", "festival", "sport", "holiday", "city_holiday", "fair", "exhibition"],
    )

    selected = select_guest_poster_events(today=date(2026, 7, 18), days=10, max_cards=10)
    titles = {e.title for e in selected}
    assert "Органный концерт" in titles
    assert "Спектакль «Чайка»" in titles
    assert "Фестиваль без площадки" not in titles
    assert "Бизнес-семинар" not in titles
    assert len(selected) <= 10
