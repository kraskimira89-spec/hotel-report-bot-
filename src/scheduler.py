"""Планировщик задач APScheduler (Europe/Moscow)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import get_config
from src.data_sources.site_prices import fetch_category_prices
from src.notifiers.email_sender import send_html_report
from src.notifiers.max_bot import send_message
from src.storage.db import init_db

logger = logging.getLogger(__name__)


def _msk_now() -> datetime:
    cfg = get_config()
    return datetime.now(ZoneInfo(cfg.property.timezone))


def job_price_snapshot(
    report_date: date | None = None,
    run_date: date | None = None,
) -> None:
    """Ежедневный snapshot цен (09:00 MSK).

    report_date — дата, за которую собираются данные.
    run_date — дата фактического запуска задачи.
    """
    run_date = run_date or _msk_now().date()
    report_date = report_date or run_date
    logger.info(
        "Задача price_snapshot: report_date=%s, run_date=%s",
        report_date,
        run_date,
    )
    # TODO: этап 4 — сохранить в price_snapshots (SQLite)
    prices = fetch_category_prices()
    logger.info("Собрано %s цен (snapshot)", len(prices))


def job_daily_summary(
    report_date: date | None = None,
    run_date: date | None = None,
) -> None:
    """Ежедневная сводка в Max (09:05 MSK)."""
    run_date = run_date or _msk_now().date()
    report_date = report_date or run_date
    cfg = get_config()
    logger.info(
        "Задача daily_summary: report_date=%s, run_date=%s",
        report_date,
        run_date,
    )
    # TODO: этап 5 — полный расчёт метрик и светофор
    text = (
        f"📊 Сводка за {report_date}\n"
        f"🟢 Загрузка: —\n"
        f"🟡 Цены: —\n"
        f"🟢 Новые брони: —\n"
        f"(каркас, dry_run={cfg.dry_run})"
    )
    send_message(text)


def job_weekly_email(
    report_date: date | None = None,
    run_date: date | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> None:
    """Еженедельный HTML-отчёт на email (пн 08:00 MSK)."""
    run_date = run_date or _msk_now().date()
    report_date = report_date or run_date
    period_end = period_end or (report_date - timedelta(days=1))
    period_start = period_start or (period_end - timedelta(days=6))
    logger.info(
        "Задача weekly_email: report_date=%s, run_date=%s, period=%s..%s",
        report_date,
        run_date,
        period_start,
        period_end,
    )
    # TODO: этап 6 — полный HTML-отчёт
    html = f"<h1>Отчёт {period_start} — {period_end}</h1><p>Каркас проекта.</p>"
    plain = f"Отчёт {period_start} — {period_end}. Каркас проекта."
    send_html_report(
        subject=f"{period_start} — {period_end}",
        html_body=html,
        text_plain=plain,
    )


def _parse_cron(cron_expr: str) -> dict[str, str]:
    """Разобрать cron 'min hour dom month dow' в kwargs для CronTrigger."""
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"Некорректный cron: {cron_expr}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def create_scheduler() -> BackgroundScheduler:
    """Создать и зарегистрировать задачи планировщика."""
    cfg = get_config()
    tz = ZoneInfo(cfg.property.timezone)
    scheduler = BackgroundScheduler(timezone=tz)

    snapshot_kw = _parse_cron(cfg.scheduler.price_snapshot_cron)
    summary_kw = _parse_cron(cfg.scheduler.daily_summary_cron)
    email_kw = _parse_cron(cfg.scheduler.weekly_email_cron)

    scheduler.add_job(
        job_price_snapshot,
        CronTrigger(timezone=tz, **snapshot_kw),
        id="price_snapshot",
        name="Snapshot цен",
    )
    scheduler.add_job(
        job_daily_summary,
        CronTrigger(timezone=tz, **summary_kw),
        id="daily_summary",
        name="Сводка Max",
    )
    scheduler.add_job(
        job_weekly_email,
        CronTrigger(timezone=tz, **email_kw),
        id="weekly_email",
        name="Email-отчёт",
    )

    logger.info("Планировщик: зарегистрировано %s задач (TZ=%s)", 3, cfg.property.timezone)
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Инициализировать БД и запустить планировщик."""
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    return scheduler
