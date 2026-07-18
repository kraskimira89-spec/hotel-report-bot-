"""Тесты внутреннего бота сотрудников Max."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.config import (
    AppConfig,
    StaffBotConfig,
    StaffEmployeeConfig,
    StorageConfig,
)
from src.notifiers.max_api import extract_message_text, parse_updates
from src.staff_bot.acl import DENIED_TEXT, check_access, sync_staff_from_config
from src.staff_bot.handlers import reply_detail, reply_start, reply_summary
from src.staff_bot.templates import resolve_command, welcome_text
from src.storage import db as storage_db
from src.storage.db import (
    get_staff_user,
    init_db,
    save_metrics_daily,
    upsert_recommendation,
)
from src.storage.models import MetricsDailyRecord, RecommendationRecord


@pytest.fixture
def staff_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "staff.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _path)
    monkeypatch.setattr("src.config.get_db_path", _path)
    init_db()
    return db_file


def _cfg(*employees: StaffEmployeeConfig, dry_run: bool = True) -> AppConfig:
    return AppConfig(
        storage=StorageConfig(db_path="unused"),
        staff_bot=StaffBotConfig(
            enabled=True,
            dry_run=dry_run,
            admin_base_url="https://bot.example.test",
            test_user_ids=[e.user_id for e in employees if dry_run][:1]
            or ([employees[0].user_id] if employees else []),
            employees=list(employees),
        ),
    )


def test_welcome_text() -> None:
    text = welcome_text("Екатерина")
    assert "Екатерина" in text
    assert "1apart" in text
    assert "9:00" in text


def test_first_connect_text() -> None:
    from src.staff_bot.templates import first_connect_text

    text = first_connect_text("Иван")
    assert "9:00" in text
    assert "сводку" in text.lower() or "сводка" in text.lower() or "присылать" in text
    assert "1apart" in text


def test_resolve_command() -> None:
    assert resolve_command("/start") == "start"
    assert resolve_command("📊 Сводка на сегодня") == "summary"
    assert resolve_command("⚠️ Проблемы") == "problems"


def test_parse_single_webhook_update() -> None:
    payload = {
        "update_type": "message_created",
        "timestamp": 1,
        "message": {
            "sender": {"user_id": 42, "name": "Test"},
            "recipient": {"chat_id": 42},
            "body": {"text": "/start"},
        },
    }
    updates = parse_updates(payload)
    assert len(updates) == 1
    assert updates[0].user_id == 42
    assert updates[0].chat_id == 42
    assert extract_message_text(updates[0].raw) == "/start"


def test_acl_deny_unknown(staff_db: Path) -> None:
    cfg = _cfg(
        StaffEmployeeConfig(user_id=100, name="A", role="owner"),
        dry_run=True,
    )
    cfg.staff_bot.test_user_ids = [100]
    sync_staff_from_config(cfg)
    result = check_access(999, "start", config=cfg)
    assert result.allowed is False
    assert result.reason == "not_in_allowlist"


def test_acl_dry_run_gate(staff_db: Path) -> None:
    cfg = _cfg(
        StaffEmployeeConfig(user_id=100, name="A", role="owner"),
        StaffEmployeeConfig(user_id=200, name="B", role="manager"),
        dry_run=True,
    )
    cfg.staff_bot.test_user_ids = [100]
    sync_staff_from_config(cfg)
    assert check_access(100, "start", config=cfg).allowed is True
    denied = check_access(200, "start", config=cfg)
    assert denied.allowed is False
    assert denied.reason == "dry_run_gate"


def test_acl_viewer_cannot_recommendations(staff_db: Path) -> None:
    cfg = _cfg(
        StaffEmployeeConfig(user_id=100, name="V", role="viewer"),
        dry_run=False,
    )
    cfg.staff_bot.test_user_ids = []
    sync_staff_from_config(cfg)
    assert check_access(100, "summary", config=cfg).allowed is True
    assert check_access(100, "recommendations", config=cfg).allowed is False


def test_reply_start_has_menu(staff_db: Path) -> None:
    cfg = _cfg(StaffEmployeeConfig(user_id=1, name="Сергей", role="owner"), dry_run=False)
    sync_staff_from_config(cfg)
    staff = get_staff_user(1)
    assert staff is not None
    reply = reply_start(staff)
    assert "Сергей" in reply["text"]
    assert reply["attachments"]
    assert reply["attachments"][0]["type"] == "inline_keyboard"
    buttons = reply["attachments"][0]["payload"]["buttons"]
    assert buttons[0][0]["text"] == "🚀 Начать"
    assert buttons[0][0]["payload"] == "cmd:start"


def test_resolve_nachat() -> None:
    assert resolve_command("🚀 Начать") == "start"
    assert resolve_command("начать") == "start"


def test_reply_summary_and_detail(staff_db: Path) -> None:
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=date.today(),
            occupancy_pct=54.5,
            revenue=100000,
            bookings_count=3,
            adr=5000,
            revpar=2700,
        )
    )
    rec_id = upsert_recommendation(
        RecommendationRecord(
            source_module="forecast",
            recommendation_type="price",
            title="Поднять цену",
            summary="Спрос растёт",
            priority="high",
            instruction_template="price_increase",
            source_ref="test-staff-1",
        )
    )
    cfg = _cfg(
        StaffEmployeeConfig(user_id=1, name="Менеджер", role="manager"),
        dry_run=False,
    )
    sync_staff_from_config(cfg)
    staff = get_staff_user(1)
    assert staff is not None
    summary = reply_summary(config=cfg)
    assert "54.5%" in summary["text"]
    detail = reply_detail(rec_id, staff=staff, config=cfg)
    assert "Краткий план" in detail["text"]
    assert f"/recommendations/{rec_id}" in detail["text"]


def test_denied_constant() -> None:
    assert DENIED_TEXT == "Доступ не предоставлен"
