"""Тесты веб-админки FastAPI."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import StorageConfig, reload_config
from src.storage import db as storage_db
from src.storage.db import init_db, save_metrics_daily, save_report_log
from src.storage.models import MetricsDailyRecord, ReportLogRecord
from src.web.app import app


@pytest.fixture
def web_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_file = tmp_path / "test.db"
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
    monkeypatch.setattr(
        "src.notifiers.max_webhook.get_env_settings",
        lambda: type(
            "E",
            (),
            {"max_webhook_secret": ""},
        )(),
    )

    def _patched_db_path() -> Path:
        return db_file

    cfg = reload_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()

    save_metrics_daily(
        MetricsDailyRecord(
            report_date=date(2026, 7, 7),
            occupancy_pct=68.0,
            adr=5000.0,
            revpar=3400.0,
        )
    )
    save_report_log(
        ReportLogRecord(
            report_type="max",
            report_date=date(2026, 7, 7),
            run_date=date(2026, 7, 7),
            status="sent",
            dry_run=True,
        )
    )
    reload_config()
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_login_required(web_client: TestClient) -> None:
    response = web_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_max_webhook_accepts_update(web_client: TestClient) -> None:
    payload = {
        "updates": [
            {"update_type": "bot_started", "chat_id": 364502022, "user_id": 6407832}
        ]
    }
    response = web_client.post("/api/max/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert 364502022 in data["chat_ids"]


def test_max_webhook_rejects_bad_secret(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.notifiers.max_webhook.get_env_settings",
        lambda: type(
            "E",
            (),
            {
                "secret_key": "test-secret",
                "admin_password": "admin",
                "admin_token": "",
                "web_force_https": False,
                "max_webhook_secret": "expected-secret",
            },
        )(),
    )
    payload = {"updates": [{"update_type": "bot_started", "chat_id": 1}]}
    ok = web_client.post(
        "/api/max/webhook",
        json=payload,
        headers={"X-Max-Bot-Api-Secret": "expected-secret"},
    )
    assert ok.status_code == 200

    bad = web_client.post("/api/max/webhook", json=payload)
    assert bad.status_code == 403


def test_dashboard_after_login(web_client: TestClient) -> None:
    _login(web_client)
    # `/` → редирект на аналитику (стартовая страница)
    response = web_client.get("/", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert "/analytics" in response.headers.get("location", "")
    page = web_client.get("/analytics")
    assert page.status_code == 200
    assert "Аналитика" in page.text
    assert "Прогноз" in page.text
    assert "/forecast" in page.text


def test_snapshots_and_metrics_pages(web_client: TestClient) -> None:
    _login(web_client)
    assert web_client.get("/snapshots").status_code == 200
    assert web_client.get("/metrics").status_code == 200
    assert web_client.get("/channels").status_code == 200
    assert web_client.get("/competitors").status_code == 200
    assert web_client.get("/trends").status_code == 200
    assert web_client.get("/analytics").status_code == 200
    assert web_client.get("/forecast").status_code == 200
    assert web_client.get("/logs").status_code == 200
    assert web_client.get("/reports").status_code == 200
    assert web_client.get("/dashboard").status_code == 200


def test_competitors_page_content(web_client: TestClient) -> None:
    _login(web_client)
    response = web_client.get("/competitors")
    assert response.status_code == 200
    assert "Конкуренты" in response.text
    assert "Обзорная таблица" in response.text
    assert "Гоголь" in response.text or "Петровские" in response.text


def test_competitors_redirect_without_auth(web_client: TestClient) -> None:
    response = web_client.get("/competitors", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_trends_page_content(web_client: TestClient) -> None:
    _login(web_client)
    response = web_client.get("/trends")
    assert response.status_code == 200
    assert "Тренды" in response.text
    assert "Лента трендов" in response.text
    assert "Идея недели" in response.text or "Фильтры" in response.text


def test_trends_redirect_without_auth(web_client: TestClient) -> None:
    response = web_client.get("/trends", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_forecast_page_content(web_client: TestClient) -> None:
    _login(web_client)
    response = web_client.get("/forecast?horizon_days=7&scenario=base")
    assert response.status_code == 200
    assert "Прогноз" in response.text
    assert "Рекомендации по ценам" in response.text


def test_forecast_redirect_without_auth(web_client: TestClient) -> None:
    response = web_client.get("/forecast", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_forecast_reco_defer_action(web_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    from src.forecast.service import run_forecast_refresh
    from src.storage.db import get_price_recommendations, save_metrics_daily
    from src.storage.models import MetricsDailyRecord

    _login(web_client)
    start = date.today() - timedelta(days=30)
    for i in range(30):
        save_metrics_daily(
            MetricsDailyRecord(
                report_date=start + timedelta(days=i),
                occupancy_pct=55.0,
                adr=5000.0,
                revpar=2750.0,
                revenue=100000.0,
            )
        )
    run_forecast_refresh(horizons=[7])
    recs = get_price_recommendations(status="new", horizon_days=7)
    if not recs:
        pytest.skip("нет рекомендаций")
    rec_id = recs[0].id
    response = web_client.post(
        f"/forecast/recommendation/{rec_id}/defer",
        data={"horizon_days": "7", "scenario": "base", "room_type": ""},
        follow_redirects=False,
    )
    assert response.status_code == 302
    updated = get_price_recommendations(status="deferred", horizon_days=7)
    assert any(r.id == rec_id for r in updated)


def test_trends_page_filters(web_client: TestClient) -> None:
    _login(web_client)
    response = web_client.get("/trends?region=ru&days=90")
    assert response.status_code == 200
    assert "Лента трендов" in response.text

    filtered = web_client.get(
        "/trends?region=world&category=Технологии+и+ИИ&days=30"
    )
    assert filtered.status_code == 200
    assert "Фильтры" in filtered.text


def test_toggle_dry_run_without_restart(web_client: TestClient) -> None:
    _login(web_client)
    cfg_before = reload_config()
    new_value = not cfg_before.dry_run
    response = web_client.post(
        "/settings/dry-run",
        data={"dry_run": "true" if new_value else "false"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    cfg_after = reload_config()
    assert cfg_after.dry_run is new_value

    page = web_client.get("/settings")
    assert page.status_code == 200
    if new_value:
        assert "включён" in page.text
    else:
        assert "выключен" in page.text


def test_save_settings_thresholds(web_client: TestClient) -> None:
    _login(web_client)
    response = web_client.post(
        "/settings/save",
        data={
            "occupancy_green_min": "80",
            "occupancy_yellow_min": "55",
            "price_change_yellow_pct": "6",
            "price_change_red_pct": "12",
            "new_bookings_green_min": "4",
            "new_bookings_yellow_min": "2",
            "price_snapshot_cron": "0 9 * * *",
            "daily_summary_cron": "5 9 * * *",
            "weekly_email_cron": "0 8 * * 1",
            "request_delay_min_sec": "2",
            "request_delay_max_sec": "3",
            "max_retries": "3",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    cfg = reload_config()
    assert cfg.traffic_light.occupancy_green_min == 80.0


def test_health_skips_https_redirect(web_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Docker healthcheck ходит на HTTP /health при WEB_FORCE_HTTPS=true."""
    monkeypatch.setattr(
        "src.web.app.get_env_settings",
        lambda: type(
            "E",
            (),
            {
                "secret_key": "test-secret",
                "admin_password": "admin",
                "admin_token": "",
                "web_force_https": True,
                "max_webhook_secret": "",
            },
        )(),
    )
    health = web_client.get("/health", follow_redirects=False)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    login = web_client.get("/login", follow_redirects=False)
    assert login.status_code == 301
