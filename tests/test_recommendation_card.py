"""Карточка внедрения рекомендации: UI, Word, статусы, снимок."""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from src.config import ForecastConfig, StorageConfig, reload_config
from src.forecast.engine import DayForecast, ForecastFactors
from src.forecast.recommendations import build_price_recommendation
from src.forecast.service import run_forecast_refresh
from src.notifiers.docx_export import build_recommendation_docx, recommendation_docx_filename
from src.storage import db as storage_db
from src.storage.db import (
    apply_price_recommendation,
    get_price_recommendation_by_id,
    get_price_recommendations,
    init_db,
    rollback_price_recommendation,
    save_metrics_daily,
    save_price_recommendations,
    update_price_recommendation_status,
)
from src.storage.models import MetricsDailyRecord, PriceRecommendationRecord, SCHEMA_VERSION
from src.web.app import app
from src.web import queries


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_file = tmp_path / "reco_card.db"
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
    start = date.today() - timedelta(days=40)
    for i in range(40):
        save_metrics_daily(
            MetricsDailyRecord(
                report_date=start + timedelta(days=i),
                occupancy_pct=70.0,
                adr=4500.0,
                revpar=3150.0,
                revenue=120000.0,
            )
        )
    reload_config()
    return TestClient(app)


def _login(c: TestClient) -> None:
    resp = c.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def _seed_reco(
    *,
    target: date | None = None,
    status: str = "new",
    current: float = 4500.0,
    lo: float = 4800.0,
    hi: float = 4950.0,
    rtype: str = "increase",
) -> int:
    target = target or (date.today() + timedelta(days=5))
    snap = {
        "as_of": date.today().isoformat(),
        "model_version": "v1",
        "occupancy_pct": 82.0,
        "confidence": "medium",
        "pickup_3d": 2,
        "pickup_7d": 5,
        "current_price": current,
        "market_median": 5200.0,
        "market_gap_pct": -13.5,
        "events": [],
        "recommended_price_min": lo,
        "recommended_price_max": hi,
        "recommendation_type": rtype,
        "reason": "тест",
    }
    rec = PriceRecommendationRecord(
        room_type="1room",
        target_date=target,
        current_price=current,
        recommended_price_min=lo,
        recommended_price_max=hi,
        recommendation_type=rtype,
        reason="тест: сильный pickup",
        confidence="medium",
        status=status,
        horizon_days=7,
        recommendation_snapshot_json=snap,
        selected_price=round((lo + hi) / 2, 0),
    )
    save_price_recommendations([rec], horizon_days=7, as_of=date.today())
    rows = get_price_recommendations(horizon_days=7, limit=1)
    assert rows
    return int(rows[0].id)


def test_schema_has_snapshot_columns(client: TestClient) -> None:
    with storage_db.db_session() as conn:
        ver = conn.execute("SELECT version FROM schema_version").fetchone()
        assert ver["version"] == SCHEMA_VERSION
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(price_recommendations)").fetchall()
        }
    assert "recommendation_snapshot_json" in cols
    assert "applied_price" in cols
    assert "rollback_reason" in cols


def test_detail_requires_auth(client: TestClient) -> None:
    rec_id = _seed_reco()
    resp = client.get(f"/forecast/recommendation/{rec_id}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"
    resp2 = client.get(
        f"/forecast/recommendation/{rec_id}/export.docx", follow_redirects=False
    )
    assert resp2.status_code == 302


def test_detail_card_and_reviewed(client: TestClient) -> None:
    _login(client)
    rec_id = _seed_reco(status="new")
    # Старый URL редиректит в Центр рекомендаций после sync
    resp = client.get(f"/forecast/recommendation/{rec_id}", follow_redirects=True)
    assert resp.status_code == 200
    assert "Пошаговые действия" in resp.text or "Инструкция для менеджера" in resp.text
    assert "Контроль" in resp.text or "Если результата нет" in resp.text


def test_docx_export_contains_key_fields(client: TestClient) -> None:
    _login(client)
    rec_id = _seed_reco()
    resp = client.get(f"/forecast/recommendation/{rec_id}/export.docx")
    assert resp.status_code == 200
    assert "wordprocessingml" in resp.headers["content-type"]
    data = resp.content
    assert data[:2] == b"PK"
    # docx = zip; document.xml содержит текст
    with ZipFile(BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert str(rec_id) in xml
    assert "TravelLine" in xml
    assert "4800" in xml or "4 800" in xml or "4900" in xml or "4 900" in xml


def test_snapshot_stable_on_refresh(client: TestClient) -> None:
    run_forecast_refresh(horizons=[7])
    recs = get_price_recommendations(status="new", horizon_days=7)
    if not recs:
        pytest.skip("нет рекомендаций после refresh")
    first = recs[0]
    assert first.id is not None
    assert first.recommendation_snapshot_json is not None
    snap_before = dict(first.recommendation_snapshot_json)
    # повторный refresh создаёт новые строки и expires старые new
    run_forecast_refresh(horizons=[7])
    old = get_price_recommendation_by_id(int(first.id))
    assert old is not None
    assert old.status == "expired"
    assert old.recommendation_snapshot_json == snap_before


def test_apply_rejects_past_date(client: TestClient) -> None:
    _login(client)
    rec_id = _seed_reco(target=date.today() - timedelta(days=1), status="accepted")
    resp = client.post(
        f"/forecast/recommendation/{rec_id}/apply",
        data={"selected_price": "4900"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    row = get_price_recommendation_by_id(rec_id)
    assert row is not None
    assert row.status == "accepted"


def test_apply_rejects_out_of_range(client: TestClient) -> None:
    _login(client)
    rec_id = _seed_reco(status="accepted")
    resp = client.post(
        f"/forecast/recommendation/{rec_id}/apply",
        data={"selected_price": "10000"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_apply_only_after_accept(client: TestClient) -> None:
    _login(client)
    rec_id = _seed_reco(status="reviewed")
    resp = client.post(
        f"/forecast/recommendation/{rec_id}/apply",
        data={"selected_price": "4900"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    update_price_recommendation_status(rec_id, "accepted")
    ok = client.post(
        f"/forecast/recommendation/{rec_id}/apply",
        data={"selected_price": "4900", "applied_note": "вручную в TL"},
        follow_redirects=False,
    )
    assert ok.status_code == 302
    row = get_price_recommendation_by_id(rec_id)
    assert row is not None
    assert row.status == "applied"
    assert row.applied_price == 4900.0
    assert row.applied_at is not None


def test_rollback_stores_reason(client: TestClient) -> None:
    _login(client)
    rec_id = _seed_reco(status="accepted")
    apply_price_recommendation(
        rec_id, selected_price=4900.0, applied_by="admin", applied_note="ok"
    )
    resp = client.post(
        f"/forecast/recommendation/{rec_id}/rollback",
        data={"rollback_reason": "нет pickup за сутки"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    row = get_price_recommendation_by_id(rec_id)
    assert row is not None
    assert row.status == "rolled_back"
    assert row.rollback_reason == "нет pickup за сутки"
    assert row.rollback_at is not None


def test_build_recommendation_includes_snapshot() -> None:
    day = DayForecast(
        forecast_date=date.today() + timedelta(days=3),
        room_type="1room",
        scenario="base",
        occupancy_pct=85.0,
        adr=5000.0,
        revpar=4000.0,
        revenue=100000.0,
        sold_unit_nights=30.0,
        available_unit_nights=40,
        lower_bound=70.0,
        upper_bound=95.0,
        confidence="high",
        factors=ForecastFactors(history_days=90),
    )
    rec = build_price_recommendation(
        forecast=day,
        current_price=4500.0,
        market_median=5200.0,
        pickup_7d=5,
        pickup_3d=2,
        min_price=2000.0,
        max_price=20000.0,
        max_change_pct=15.0,
        use_competitors=True,
        free_units=5,
        total_units=10,
        model_version="v1",
        as_of=date.today(),
        horizon_days=7,
    )
    assert rec is not None
    assert rec.recommendation_snapshot_json is not None
    assert rec.recommendation_snapshot_json["occupancy_pct"] == 85.0
    assert rec.recommendation_snapshot_json["pickup_7d"] == 5
    assert rec.selected_price is not None


def test_docx_filename_slug() -> None:
    name = recommendation_docx_filename(42, date(2026, 9, 12), "Улучшенная 1-комнатная")
    assert name.startswith("1apart_рекомендация_42_2026-09-12_")
    assert name.endswith(".docx")


def test_fetch_card_and_docx_builder(client: TestClient) -> None:
    rec_id = _seed_reco(status="accepted")
    card = queries.fetch_recommendation_card(rec_id)
    assert card is not None
    assert card["decision"]["id"] == rec_id
    assert card["steps"]
    blob = build_recommendation_docx(card)
    assert blob[:2] == b"PK"
