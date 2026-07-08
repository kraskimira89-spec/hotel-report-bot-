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
            },
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


def test_dashboard_after_login(web_client: TestClient) -> None:
    _login(web_client)
    response = web_client.get("/")
    assert response.status_code == 200
    assert "Дашборд" in response.text
    assert "68.0" in response.text or "68" in response.text


def test_snapshots_and_metrics_pages(web_client: TestClient) -> None:
    _login(web_client)
    assert web_client.get("/snapshots").status_code == 200
    assert web_client.get("/metrics").status_code == 200
    assert web_client.get("/channels").status_code == 200
    assert web_client.get("/logs").status_code == 200
    assert web_client.get("/reports").status_code == 200


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
