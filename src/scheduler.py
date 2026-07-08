"""Планировщик задач APScheduler (Europe/Moscow)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Callable, TypeVar
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import get_config
from src.data_sources.site_prices import SnapshotCollectionResult, collect_price_snapshots
from src.data_sources.travelline import run_daily_reconciliation
from src.notifiers.email_sender import send_weekly_report
from src.notifiers.incidents import send_incident
from src.notifiers.max_bot import send_daily_summary
from src.storage.db import (
    init_db,
    price_snapshot_exists,
    report_log_exists,
    save_error_log,
    save_price_snapshots,
)
from src.storage.models import ErrorLogRecord, PriceSnapshotRecord

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
    if price_snapshot_exists(report_date):
        logger.info("Snapshot цен уже есть за %s, пропуск", report_date)
        return
    result = _run_job(
        "price_snapshot",
        run_date,
        report_date,
        _collect_price_snapshot,
    )
    if isinstance(result, SnapshotCollectionResult) and result.used_fallback:
        send_incident(
            "Источник цен недоступен",
            "Часть данных из последнего снимка.",
            source="site_prices",
        )
    _run_job(
        "sheets_reconcile",
        run_date,
        report_date,
        lambda: run_daily_reconciliation(report_date),
    )


def _collect_price_snapshot() -> SnapshotCollectionResult:
    result = collect_price_snapshots()
    records = [
        PriceSnapshotRecord(
            snapshot_at=s.snapshot_at,
            category=s.category,
            price=s.price,
            source=s.source,
            is_estimated=False,
            is_fallback=s.is_fallback,
            url=s.url or None,
        )
        for s in result.snapshots
    ]
    saved = save_price_snapshots(records)
    logger.info(
        "Snapshot цен: собрано %s, сохранено в БД %s, fallback=%s",
        len(result.snapshots),
        saved,
        result.used_fallback,
    )
    return result


def job_daily_summary(
    report_date: date | None = None,
    run_date: date | None = None,
) -> None:
    """Ежедневная сводка в Max (09:05 MSK)."""
    run_date = run_date or _msk_now().date()
    report_date = report_date or run_date
    logger.info(
        "Задача daily_summary: report_date=%s, run_date=%s",
        report_date,
        run_date,
    )
    if report_log_exists("max", report_date):
        logger.info("Сводка Max за %s уже отправлена, пропуск", report_date)
        return
    _run_job(
        "daily_summary",
        run_date,
        report_date,
        lambda: send_daily_summary(report_date=report_date, run_date=run_date),
    )


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
    if report_log_exists(
        "email", report_date, period_start=period_start, period_end=period_end
    ):
        logger.info("Email-отчёт за %s..%s уже отправлен, пропуск", period_start, period_end)
        return
    _run_job(
        "weekly_email",
        run_date,
        report_date,
        lambda: send_weekly_report(
            report_date=report_date,
            run_date=run_date,
            period_start=period_start,
            period_end=period_end,
        ),
    )


T = TypeVar("T")


def _run_job(
    job_name: str,
    run_date: date,
    report_date: date,
    func: Callable[[], T],
) -> T | None:
    try:
        return func()
    except Exception as exc:
        logger.exception("Ошибка задачи %s: %s", job_name, exc)
        save_error_log(
            ErrorLogRecord(
                error_date=run_date,
                source="scheduler",
                error_type=job_name,
                message=str(exc),
                details=f"report_date={report_date}",
            )
        )
        return None


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
