"""Тесты industry_trends: scoring, dedup, labels, pilot."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.data_sources.industry_trends import (
    content_hash,
    create_trend_pilot_recommendation,
    enrich_pending_trends,
    format_industry_trend_card,
    is_leading_region,
    region_label,
    score_trend_relevance,
    select_industry_trends_for_email,
)
from src.storage import db as storage_db
from src.storage.db import (
    get_approved_trends_for_email,
    init_db,
    log_trends_in_email,
    save_trends,
)
from src.storage.models import TrendRecord


@pytest.fixture
def trends_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "industry.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _path)
    monkeypatch.setattr("src.config.get_db_path", _path)
    init_db()
    return db_file


def _trend(**kwargs: object) -> TrendRecord:
    base = dict(
        title="RMS в апарт-отелях",
        summary="Отели тестируют динамическое ценообразование.",
        category="Динамическое ценообразование",
        region="moscow",
        source_url="https://example.com/rms",
        takeaway="Проверить гипотезу на 3 категориях.",
        published_at=date.today() - timedelta(days=3),
        status="approved",
        relevance_score=75.0,
        evidence_level="industry_media",
        local_applicability="medium",
    )
    base.update(kwargs)
    return TrendRecord(**base)  # type: ignore[arg-type]


def test_region_label_moscow_world() -> None:
    assert region_label("moscow") == "Москва"
    assert region_label("world") == "Мир"
    assert is_leading_region("moscow")
    assert is_leading_region("world")
    assert not is_leading_region("tomsk")


def test_leading_trend_badge_on_card() -> None:
    card = format_industry_trend_card(_trend(region="world"), 1)
    assert card.is_leading_trend is True
    assert "Опережающий тренд" in card.why_important

    local = format_industry_trend_card(_trend(region="tomsk"), 1)
    assert local.is_leading_trend is False


def test_score_trend_relevance_official_boost() -> None:
    low = score_trend_relevance(_trend(evidence_level="industry_media", region="world"))
    high = score_trend_relevance(
        _trend(evidence_level="official", region="tomsk", local_applicability="high")
    )
    assert high > low


def test_content_hash_stable() -> None:
    h1 = content_hash("Title", "https://a.com")
    h2 = content_hash("Title", "https://a.com")
    assert h1 == h2
    assert content_hash("Other", "https://a.com") != h1


def test_email_dedup_excludes_recent(trends_db: Path) -> None:
    _ = trends_db
    save_trends(
        [
            _trend(title="A", relevance_score=80),
            _trend(title="B", source_url="https://example.com/b", relevance_score=70),
        ]
    )
    approved = get_approved_trends_for_email(min_relevance=60, limit=5)
    assert len(approved) == 2

    today = date.today()
    first_id = approved[0].id
    assert first_id is not None
    log_trends_in_email([first_id], today, today - timedelta(days=7), today - timedelta(days=1))
    after = get_approved_trends_for_email(min_relevance=60, limit=5)
    assert len(after) == 1
    assert after[0].title != approved[0].title or after[0].id != first_id


def test_select_industry_trends_for_email_logs_inclusion(trends_db: Path) -> None:
    _ = trends_db
    save_trends([_trend(relevance_score=85)])
    pe = date.today()
    ps = pe - timedelta(days=6)
    cards = select_industry_trends_for_email(
        report_date=pe,
        period_start=ps,
        period_end=pe,
        log_inclusion=True,
    )
    assert len(cards) == 1
    again = get_approved_trends_for_email(min_relevance=60, limit=5)
    assert len(again) == 0


def test_enrich_pending_trends_scores_candidates(trends_db: Path) -> None:
    _ = trends_db
    save_trends([_trend(status="candidate", relevance_score=0, evidence_level="official", region="tomsk")])
    n = enrich_pending_trends(use_llm=False)
    assert n == 1
    approved = get_approved_trends_for_email(min_relevance=60, limit=5)
    assert approved
    assert approved[0].relevance_score >= 80


def test_create_trend_pilot_recommendation(trends_db: Path) -> None:
    _ = trends_db
    save_trends([_trend()])
    records = get_approved_trends_for_email(min_relevance=60, limit=1)
    assert records and records[0].id
    rec_id = create_trend_pilot_recommendation(records[0].id)
    assert rec_id is not None
    rec_id2 = create_trend_pilot_recommendation(records[0].id)
    assert rec_id2 == rec_id
