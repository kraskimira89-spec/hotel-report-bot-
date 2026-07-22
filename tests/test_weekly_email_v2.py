"""Тесты weekly email v2."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.config import AppConfig, EmailConfig, StorageConfig
from src.notifiers.weekly.models import (
    DataQualityBlock,
    ExecutiveSummary,
    IndustryTrendCard,
    KpiCard,
    MetricsSummary,
    WeeklyReportData,
)
from src.notifiers.weekly.plain import build_weekly_report_plain
from src.notifiers.weekly.subject import build_weekly_subject
from src.notifiers.email_sender import build_weekly_report_html, send_weekly_report
from src.storage import db as storage_db
from src.storage.db import init_db, save_trends
from src.storage.models import TrendRecord


@pytest.fixture
def weekly_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "weekly.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _path)
    monkeypatch.setattr("src.config.get_db_path", _path)
    init_db()
    return db_file


def _sample_v2(*, partial: bool = False) -> WeeklyReportData:
    ps = date(2026, 7, 14)
    pe = date(2026, 7, 20)
    return WeeklyReportData(
        period_start=ps,
        period_end=pe,
        forecast_end=pe + timedelta(days=13),
        executive_summary=ExecutiveSummary(
            headline="Загрузка выросла на 6 п.п.",
            main_action="Проверить цены на 25–27 июля",
            confidence_label="средняя",
        ),
        kpi_cards=[
            KpiCard(label="Загрузка", value="72%", delta="+6 п.п.", status="🟢"),
            KpiCard(label="Выручка", value="185 000 ₽", delta="+12%", status="🟢"),
        ],
        industry_trends=[
            IndustryTrendCard(
                trend_id=1,
                index=1,
                title="Динамическое ценообразование",
                region_label="Москва",
                what_happened="Отели тестируют RMS.",
                why_important="Может повлиять на прямой канал.",
                for_1apart="Гипотеза для проверки.",
                action="Пилот в 3 категориях.",
                source_name="hospitalitynet.org",
                source_url="https://example.com/a",
                published_at=date(2026, 7, 18),
                is_leading_trend=True,
            )
        ],
        data_quality=DataQualityBlock(lines=["TravelLine: OK"], overall="средняя"),
        current_metrics=MetricsSummary(occupancy_pct=72.0, revenue=185000),
        is_partial=partial,
    )


def test_weekly_subject_full() -> None:
    subj = build_weekly_subject(_sample_v2())
    assert subj.startswith("1apart · Итоги 14.07–20.07")
    assert "план на" in subj


def test_weekly_subject_partial() -> None:
    subj = build_weekly_subject(_sample_v2(partial=True))
    assert subj.startswith("⚠️ 1apart")


def test_html_v2_blocks() -> None:
    html = build_weekly_report_html(_sample_v2())
    assert "Главное за неделю" in html
    assert "Ключевые показатели" in html
    assert "Тренды и новости отрасли" in html
    assert "Опережающий тренд" in html
    assert "max-width:640px" in html or 'width="640"' in html


def test_plain_v2_kpi() -> None:
    plain = build_weekly_report_plain(_sample_v2())
    assert "72%" in plain
    assert "Загрузка выросла" in plain


def test_send_weekly_report_dry_run(
    weekly_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = weekly_db
    cfg = AppConfig(
        dry_run=True,
        email=EmailConfig(
            from_address="r@1apart.ru",
            test_addresses=["test@1apart.ru"],
        ),
        storage=StorageConfig(db_path=str(weekly_db)),
    )
    monkeypatch.setattr(
        "src.notifiers.email_sender._prepare_v2",
        lambda *a, **k: _sample_v2(),
    )

    class FakeSMTP:
        def sendmail(self, *args, **kwargs) -> None:
            return None

        def quit(self) -> None:
            return None

    monkeypatch.setattr(
        "src.notifiers.email_sender.get_env_settings",
        lambda: type("E", (), {"smtp_host": "smtp.test", "smtp_port": 587, "smtp_user": "", "smtp_password": "", "smtp_use_ssl": False, "smtp_use_tls": True})(),
    )

    result = send_weekly_report(
        period_start=date(2026, 7, 14),
        period_end=date(2026, 7, 20),
        config=cfg,
        smtp_factory=lambda: FakeSMTP(),
    )
    assert result["status"] == "sent"
    assert result["dry_run"] is True


def test_industry_trends_max_three(weekly_db: Path) -> None:
    _ = weekly_db
    records = [
        TrendRecord(
            title=f"Trend {i}",
            summary="Hotel market news " * 3,
            category="Рынок апарт-отелей",
            region="russia",
            source_url=f"https://example.com/{i}",
            takeaway="Проверить.",
            published_at=date.today() - timedelta(days=i),
            source_name="example.com",
            relevance_score=80.0,
            status="approved",
            content_hash=f"hash{i}",
        )
        for i in range(5)
    ]
    save_trends(records)
    from src.data_sources.industry_trends import select_industry_trends_for_email

    cards = select_industry_trends_for_email(
        report_date=date.today(),
        period_start=date.today() - timedelta(days=7),
        period_end=date.today() - timedelta(days=1),
        log_inclusion=False,
    )
    assert len(cards) <= 3
