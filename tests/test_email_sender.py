"""Тесты email-отчёта: HTML, dry-run, reports_log."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.config import AppConfig, EmailConfig, EnvSettings, StorageConfig, get_config
from src.data_sources.market_trends import CompetitorPriceInfo
from src.notifiers.email_sender import (
    MetricsSummary,
    OccupancyTypeRow,
    WeeklyReportData,
    build_weekly_report_html,
    build_weekly_report_plain,
    send_html_report,
    send_weekly_report,
)
from src.storage import db as storage_db
from src.storage.db import init_db


@pytest.fixture
def email_config() -> AppConfig:
    return AppConfig(
        dry_run=True,
        email=EmailConfig(
            from_address="reports@1apart.ru",
            to_addresses=["manager@1apart.ru"],
            test_addresses=["test@1apart.ru"],
        ),
    )


@pytest.fixture
def smtp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.notifiers.email_sender.get_env_settings",
        lambda: EnvSettings(
            smtp_host="smtp.test",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
        ),
    )


from src.notifiers.weekly.models import ExecutiveSummary, KpiCard


def _sample_report(*, estimated: bool = False) -> WeeklyReportData:
    return WeeklyReportData(
        period_start=date(2026, 6, 30),
        period_end=date(2026, 7, 6),
        executive_summary=ExecutiveSummary(
            headline="Загрузка 68%",
            main_action="Проверить цены",
            confidence_label="средняя",
        ),
        kpi_cards=[
            KpiCard(
                label="Загрузка",
                value="68.0%",
                delta="+8.0 п.п.",
                status="🟢",
            ),
            KpiCard(
                label="ADR",
                value="5 000 ₽",
                status="🟡",
                is_estimated=estimated,
                note="Оценочно" if estimated else "",
            ),
            KpiCard(
                label="RevPAR",
                value="3 400 ₽",
                status="🟡",
                is_estimated=estimated,
            ),
        ],
        occupancy_by_type=[
            OccupancyTypeRow(room_type="1-комн. 23", occupancy_pct=75.0),
        ],
        current_metrics=MetricsSummary(
            occupancy_pct=68.0,
            adr=5000.0,
            revpar=3400.0,
            als=2.5,
            revenue=100000.0,
            bookings_count=12,
            is_estimated=estimated,
        ),
        prev_week_metrics=MetricsSummary(
            occupancy_pct=60.0, adr=4800.0, revpar=3000.0
        ),
        direct_share_pct=55.0,
        aggregator_share_pct=45.0,
        returning_guests_pct=20.0,
        market_trends=["Спрос стабилен", "Доля прямых растёт"],
        competitor_prices=[
            CompetitorPriceInfo(
                name="Апартаменты Петровские",
                kind="direct",
                url="https://petrovskie.example.ru/",
                price_from=4500.0,
                available=True,
            )
        ],
    )


def test_build_weekly_report_html_sections() -> None:
    html = build_weekly_report_html(_sample_report())
    assert "1apart · Итоги недели" in html
    assert "Ключевые показатели" in html
    assert "Главное за неделю" in html
    assert "1-комн. 23" in html


def test_build_weekly_report_html_estimated_marker() -> None:
    html = build_weekly_report_html(_sample_report(estimated=True))
    assert "Оценочно" in html


def test_build_weekly_report_plain_key_figures() -> None:
    plain = build_weekly_report_plain(_sample_report(estimated=True))
    assert "ADR" in plain
    assert "5 000" in plain
    assert "[Оценочно]" in plain
    assert "68.0%" in plain


def test_send_html_report_dry_run_uses_test_addresses(
    email_config: AppConfig,
    smtp_env: None,
) -> None:
    sent: list[dict[str, Any]] = []

    class FakeSmtp:
        def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
            sent.append({"from": from_addr, "to": to_addrs, "msg": msg})

    result = send_html_report(
        subject="test",
        html_body="<p>hi</p>",
        text_plain="hi",
        config=email_config,
        smtp_factory=lambda: FakeSmtp(),
    )

    assert result["status"] == "sent"
    assert result["dry_run"] is True
    assert sent[0]["to"] == ["test@1apart.ru"]
    assert "manager@1apart.ru" not in sent[0]["to"]


def test_send_html_report_production_uses_main_addresses(
    email_config: AppConfig,
    smtp_env: None,
) -> None:
    email_config.dry_run = False
    recipients: list[str] = []

    class FakeSmtp:
        def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
            recipients.extend(to_addrs)

    send_html_report(
        subject="test",
        html_body="<p>hi</p>",
        text_plain="hi",
        config=email_config,
        smtp_factory=lambda: FakeSmtp(),
    )
    assert recipients == ["manager@1apart.ru"]


def test_send_weekly_report_writes_reports_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    email_config: AppConfig,
    smtp_env: None,
) -> None:
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _patched_db_path() -> Path:
        return db_file

    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()

    class FakeSmtp:
        def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
            return None

    result = send_weekly_report(
        period_start=date(2026, 6, 30),
        period_end=date(2026, 7, 6),
        config=email_config,
        report_data=_sample_report(),
        smtp_factory=lambda: FakeSmtp(),
    )

    assert result["status"] == "sent"
    conn = storage_db.get_connection()
    try:
        row = conn.execute(
            "SELECT report_type, status, dry_run FROM reports_log"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["report_type"] == "email"
    assert row["status"] == "sent"
    assert row["dry_run"] == 1
