"""Тесты раздела «Аналитика» (ИИ-лента)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.analytics.ai_insights import (
    generate_insights,
    parse_llm_insight_json,
    run_insights_refresh,
)
from src.config import StorageConfig, reload_config
from src.storage import db as storage_db
from src.storage.db import get_insights_records, init_db, save_metrics_daily
from src.storage.models import MetricsDailyRecord
from src.web import queries
from src.web.app import app


@pytest.fixture
def analytics_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "analytics.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")
    reload_config()

    def _path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _path)
    monkeypatch.setattr("src.config.get_db_path", _path)
    init_db()
    cfg = reload_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=date(2026, 7, 10),
            occupancy_pct=55.0,
            adr=4800.0,
            revpar=2640.0,
            als=2.5,
        )
    )
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=date(2026, 7, 3),
            occupancy_pct=70.0,
            adr=5000.0,
            revpar=3500.0,
            als=2.2,
        )
    )
    return db_file


@pytest.fixture
def analytics_client(analytics_db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _ = analytics_db
    monkeypatch.setattr(
        "src.web.app.get_env_settings",
        lambda: type(
            "E",
            (),
            {
                "secret_key": "test-secret",
                "admin_password": "admin",
                "admin_token": "",
                "web_force_https": False,
                "max_webhook_secret": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "src.notifiers.max_webhook.get_env_settings",
        lambda: type("E", (), {"max_webhook_secret": ""})(),
    )
    return TestClient(app)


def test_parse_llm_insight_json() -> None:
    raw = """
    {"title": "Загрузка падает", "summary": "Минус 10% к прошлой неделе.",
     "recommendations": ["Снизить цену пт-сб", "Акция 2+1"], "severity": "action"}
    """
    card = parse_llm_insight_json(raw, "occupancy", "travelline", "2026-07-01 — 2026-07-14")
    assert card.topic == "occupancy"
    assert card.severity == "action"
    assert len(card.recommendations) == 2
    assert "падает" in card.title.lower() or "Загрузка" in card.title


def test_generate_insights_rule_based(analytics_db: Path) -> None:
    _ = analytics_db
    cards = generate_insights(period_days=14, use_llm=False)
    assert len(cards) >= 8
    topics = {c.topic for c in cards}
    assert "occupancy" in topics
    assert "competitors" in topics


def test_run_insights_refresh_and_sort(analytics_db: Path) -> None:
    _ = analytics_db
    saved = run_insights_refresh(period_days=14)
    assert saved >= 8
    rows = queries.get_insights()
    assert rows
    ranks = {"action": 0, "attention": 1, "info": 2}
    scores = [ranks.get(r["severity"], 9) for r in rows]
    assert scores == sorted(scores)


def test_analytics_requires_auth(analytics_client: TestClient) -> None:
    resp = analytics_client.get("/analytics", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("location", "")


def test_analytics_ok_and_layout(analytics_client: TestClient) -> None:
    analytics_client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    resp = analytics_client.get("/analytics")
    assert resp.status_code == 200
    assert "Аналитика" in resp.text
    assert "insight-grid" in resp.text
    assert "Рекомендации" in resp.text


def test_root_redirects_to_analytics(analytics_client: TestClient) -> None:
    analytics_client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    resp = analytics_client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/analytics" in resp.headers.get("location", "")


def test_fallback_rule_based_without_llm(analytics_db: Path) -> None:
    _ = analytics_db
    run_insights_refresh(period_days=14)
    before = len(get_insights_records())
    cards = generate_insights(use_llm=False)
    assert before >= 8
    assert len(cards) >= 8
