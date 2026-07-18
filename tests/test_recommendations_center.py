"""Тесты Центра рекомендаций."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from src.config import ForecastConfig, StorageConfig, reload_config
from src.recommendations.render import render_instruction_card
from src.recommendations.service import (
    build_external_trends_payload,
    build_system_recommendations,
    build_trend_pilot_recommendations,
    refresh_recommendations_center,
    sync_price_recommendations,
)
from src.storage import db as storage_db
from src.storage.db import (
    get_recommendation_by_id,
    get_recommendation_by_source_ref,
    init_db,
    list_recommendations,
    save_error_log,
    save_price_recommendations,
    update_recommendation_status,
    upsert_recommendation,
)
from src.storage.models import (
    SCHEMA_VERSION,
    ErrorLogRecord,
    PriceRecommendationRecord,
    RecommendationRecord,
    TrendRecord,
)
from src.web.app import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_file = tmp_path / "reco_center.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")
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

    def _patched_db_path() -> Path:
        return db_file

    cfg = reload_config()
    cfg.storage = StorageConfig(db_path=str(db_file), retention_days=730)
    cfg.forecast = ForecastConfig(enabled=True, min_history_days=30)
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()
    reload_config()
    return TestClient(app)


def _login(c: TestClient) -> None:
    resp = c.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_schema_15(client: TestClient) -> None:
    with storage_db.db_session() as conn:
        ver = conn.execute("SELECT version FROM schema_version").fetchone()
        assert ver["version"] == SCHEMA_VERSION
        conn.execute("SELECT 1 FROM recommendations LIMIT 1")


def test_upsert_idempotent_and_preserves_accepted(client: TestClient) -> None:
    rec = RecommendationRecord(
        source_module="system",
        recommendation_type="travelline_sync_error",
        title="TravelLine не синхронизируется",
        instruction_template="travelline_sync_error",
        source_ref="error:test1",
        priority="critical",
        status="new",
        evidence_snapshot_json={"what_happens": ["ошибка A"]},
    )
    rid = upsert_recommendation(rec)
    update_recommendation_status(rid, "accepted")
    rec.evidence_snapshot_json = {"what_happens": ["ошибка B"]}
    rid2 = upsert_recommendation(rec)
    assert rid2 == rid
    row = get_recommendation_by_id(rid)
    assert row is not None
    assert row.status == "accepted"
    assert row.evidence_snapshot_json["what_happens"] == ["ошибка B"]


def test_sync_price_and_redirect(client: TestClient) -> None:
    save_price_recommendations(
        [
            PriceRecommendationRecord(
                room_type="1room",
                target_date=date.today() + timedelta(days=5),
                current_price=4500,
                recommended_price_min=4800,
                recommended_price_max=4950,
                recommendation_type="increase",
                reason="тест",
                confidence="high",
                status="new",
                horizon_days=7,
                recommendation_snapshot_json={
                    "occupancy_pct": 80,
                    "pickup_7d": 4,
                    "market_gap_pct": -10,
                },
                selected_price=4900,
            )
        ],
        horizon_days=7,
        as_of=date.today(),
    )
    from src.storage.db import get_price_recommendations

    price = get_price_recommendations(horizon_days=7, limit=1)[0]
    assert price.id is not None
    n = sync_price_recommendations()
    assert n >= 1
    uni = get_recommendation_by_source_ref(f"price:{price.id}")
    assert uni is not None
    _login(client)
    resp = client.get(f"/forecast/recommendation/{price.id}", follow_redirects=False)
    assert resp.status_code == 302
    assert f"/recommendations/{uni.id}" in resp.headers["location"]


def test_list_and_detail_auth(client: TestClient) -> None:
    assert client.get("/recommendations", follow_redirects=False).status_code == 302
    upsert_recommendation(
        RecommendationRecord(
            source_module="system",
            recommendation_type="travelline_sync_error",
            title="TravelLine не синхронизируется",
            instruction_template="travelline_sync_error",
            source_ref="error:auth",
            priority="critical",
            evidence_snapshot_json={"what_happens": ["API down"]},
        )
    )
    _login(client)
    page = client.get("/recommendations")
    assert page.status_code == 200
    assert "Центр рекомендаций" in page.text
    row = list_recommendations(limit=1)[0]
    detail = client.get(f"/recommendations/{row.id}")
    assert detail.status_code == 200
    assert "Пошаговые действия" in detail.text
    assert "TravelLine" in detail.text


def test_docx_universal(client: TestClient) -> None:
    rid = upsert_recommendation(
        RecommendationRecord(
            source_module="system",
            recommendation_type="travelline_sync_error",
            title="TravelLine не синхронизируется",
            instruction_template="travelline_sync_error",
            source_ref="error:docx",
            priority="critical",
            evidence_snapshot_json={"what_happens": ["нет ответа API"]},
        )
    )
    _login(client)
    resp = client.get(f"/recommendations/{rid}/export.docx")
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"
    with ZipFile(BytesIO(resp.content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "TravelLine" in xml
    assert str(rid) in xml


def test_accept_complete_flow(client: TestClient) -> None:
    rid = upsert_recommendation(
        RecommendationRecord(
            source_module="forecast",
            recommendation_type="price_increase",
            title="Повысить цену",
            instruction_template="price_increase",
            source_ref="price:flow",
            status="new",
            instruction_payload_json={
                "target_date": "20.07.2026",
                "room_label": "1-КК",
                "current_price": 4500,
                "rec_min": 4800,
                "rec_max": 4950,
                "selected_price": 4900,
                "check_hours": 24,
            },
            evidence_snapshot_json={"what_happens": ["загрузка 80%"]},
        )
    )
    _login(client)
    assert client.post(f"/recommendations/{rid}/accept", follow_redirects=False).status_code == 302
    row = get_recommendation_by_id(rid)
    assert row is not None and row.status == "accepted"
    assert client.post(
        f"/recommendations/{rid}/complete",
        data={"completion_note": "сделано в TL"},
        follow_redirects=False,
    ).status_code == 302
    row2 = get_recommendation_by_id(rid)
    assert row2 is not None and row2.status == "done"
    assert row2.completion_note == "сделано в TL"


def test_system_from_errors(client: TestClient) -> None:
    save_error_log(
        ErrorLogRecord(
            error_date=date.today(),
            source="travelline",
            error_type="api",
            message="timeout",
            details="x",
            resolved=False,
        )
    )
    n = build_system_recommendations()
    assert n >= 1
    rows = list_recommendations(source_module="system")
    assert any(r.recommendation_type == "travelline_sync_error" for r in rows)


def test_external_trends_payload_from_db(client: TestClient) -> None:
    from src.storage.db import save_trends

    save_trends(
        [
            TrendRecord(
                title="Бесконтактное заселение",
                summary="Практика в Москве",
                category="technology",
                region="moscow",
                source_url="https://example.com/trend",
                takeaway="пилот",
                published_at=date(2026, 7, 10),
            )
        ]
    )
    payload = build_external_trends_payload()
    assert payload
    assert payload[0]["source_url"] == "https://example.com/trend"
    assert payload[0]["published_at"] == "2026-07-10"
    assert payload[0]["local_confirmation"] is False
    assert payload[0]["evidence_level"] == "source_confirmed"
    empty = build_external_trends_payload(days=1)
    assert isinstance(empty, list)


def test_trend_pilot_from_db_and_empty_skips(client: TestClient) -> None:
    from src.storage.db import list_recommendations, save_trends

    # Без трендов — пилотов нет
    assert build_trend_pilot_recommendations() == 0

    save_trends(
        [
            TrendRecord(
                title="Бесконтактное заселение",
                summary="Практика применяется в апарт-отелях Москвы.",
                category="technology",
                region="moscow",
                source_url="https://example.com/checkin",
                takeaway="пилот для Томска",
                published_at=date.today() - timedelta(days=2),
            ),
            TrendRecord(
                title="Локальный фестиваль",
                summary="Томск",
                category="events",
                region="tomsk",
                source_url="https://example.com/tomsk",
                takeaway="локально",
                published_at=date.today() - timedelta(days=1),
            ),
        ]
    )
    n = build_trend_pilot_recommendations()
    assert n >= 1
    rows = list_recommendations(source_module="trends")
    assert any(r.recommendation_type == "trend_pilot" for r in rows)
    # Локальный tomsk не создаёт trend_pilot (local_confirmation)
    assert not any("Локальный фестиваль" in (r.title or "") for r in rows)
    pilot = next(r for r in rows if r.recommendation_type == "trend_pilot")
    assert "Томск" in (pilot.summary or "")
    assert pilot.evidence_snapshot_json.get("local_confirmation") is False
    assert "source_url" in (pilot.instruction_payload_json or {})


def test_prompt_has_tomsk_trends_section() -> None:
    from src.analytics.prompt_loader import clear_prompt_cache, load_prompt_file

    clear_prompt_cache()
    text = load_prompt_file("03_recommendations.md")
    assert "Внешние тренды и адаптация для Томска" in text
    assert "external_trends" in text
    assert "малозатратный пилот" in text


def test_render_card_blocks(client: TestClient) -> None:
    rec = RecommendationRecord(
        id=1,
        source_module="forecast",
        recommendation_type="price_increase",
        title="Повысить",
        instruction_template="price_increase",
        status="new",
        owner="Менеджер объекта",
        instruction_payload_json={
            "target_date": "12.09.2026",
            "room_label": "Улучшенная",
            "current_price": 4500,
            "rec_min": 4800,
            "rec_max": 4950,
            "selected_price": 4900,
            "check_hours": 24,
            "forecast_occupancy": 78,
        },
        evidence_snapshot_json={"what_happens": ["Прогноз 78%"]},
    )
    card = render_instruction_card(rec)
    assert card["steps"]
    assert "TravelLine" in card["steps"][0]
    assert "4900" in card["steps"][3]


def test_refresh_center(client: TestClient) -> None:
    stats = refresh_recommendations_center()
    assert "expired" in stats
    assert "price" in stats
