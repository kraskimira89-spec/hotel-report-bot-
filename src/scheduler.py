"""Планировщик задач APScheduler (Europe/Moscow)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Callable, TypeVar
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.analytics.ai_insights import run_insights_refresh
from src.config import get_config
from src.data_sources.mail_inbox import collect_and_save_mail_inbox
from src.data_sources.market_trends import (
    collect_and_save_competitor_prices,
    run_weekly_trends_collection,
)
from src.data_sources.site_prices import SnapshotCollectionResult, collect_price_snapshots
from src.data_sources.travelline import run_daily_reconciliation
from src.deploy.vps_deploy import run_deploy_after_job
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


def job_competitor_prices(
    report_date: date | None = None,
    run_date: date | None = None,
) -> None:
    """Еженедельный автосбор цен конкурентов (Playwright + static)."""
    run_date = run_date or _msk_now().date()
    report_date = report_date or run_date
    logger.info(
        "Задача competitor_prices: report_date=%s, run_date=%s",
        report_date,
        run_date,
    )
    _run_job(
        "competitor_prices",
        run_date,
        report_date,
        lambda: collect_and_save_competitor_prices(report_date),
    )


def job_mail_inbox(
    report_date: date | None = None,
    run_date: date | None = None,
) -> None:
    """Ежедневный сбор входящей почты (IMAP)."""
    run_date = run_date or _msk_now().date()
    report_date = report_date or run_date
    cfg = get_config()
    if not getattr(cfg.mail_inbox, "enabled", False):
        logger.info("mail_inbox выключен — задача пропущена")
        return
    logger.info(
        "Задача mail_inbox: report_date=%s, run_date=%s",
        report_date,
        run_date,
    )
    lookback = max(1, int(getattr(cfg.mail_inbox, "lookback_days", 7) or 7))
    period_start = report_date - timedelta(days=lookback)
    _run_job(
        "mail_inbox",
        run_date,
        report_date,
        lambda: collect_and_save_mail_inbox(period_start, report_date),
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


def job_weekly_trends(
    run_date: date | None = None,
    report_date: date | None = None,
) -> None:
    """Еженедельный сбор трендов рынка (пн 07:00 MSK)."""
    run_date = run_date or _msk_now().date()
    report_date = report_date or run_date
    logger.info(
        "Задача weekly_trends: report_date=%s, run_date=%s",
        report_date,
        run_date,
    )
    _run_job(
        "weekly_trends",
        run_date,
        report_date,
        lambda: run_weekly_trends_collection(period_days=7),
    )


def job_analytics_insights(
    run_date: date | None = None,
    report_date: date | None = None,
) -> None:
    """Ежедневный пересчёт ИИ-ленты аналитики."""
    run_date = run_date or _msk_now().date()
    report_date = report_date or run_date
    logger.info("Задача analytics_insights: run_date=%s", run_date)
    _run_job(
        "analytics_insights",
        run_date,
        report_date,
        run_insights_refresh,
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


def _on_job_finished(event) -> None:
    """После успешной задачи планировщика — автодеплой (если включён)."""
    if event.code != EVENT_JOB_EXECUTED:
        return
    job_id = event.job_id or ""
    try:
        run_deploy_after_job(job_id, job_success=True)
    except Exception as exc:
        logger.warning("Автодеплой после %s не выполнен: %s", job_id, exc)


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
    trends_kw = _parse_cron(cfg.scheduler.weekly_trends_cron)
    analytics_cron = getattr(cfg.analytics, "refresh_cron", "15 9 * * *")
    analytics_kw = _parse_cron(analytics_cron)
    competitors_kw = _parse_cron(cfg.scheduler.competitor_prices_cron)
    mail_cron = getattr(cfg.scheduler, "mail_inbox_cron", "45 9 * * *")
    mail_kw = _parse_cron(mail_cron)

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
    scheduler.add_job(
        job_weekly_trends,
        CronTrigger(timezone=tz, **trends_kw),
        id="weekly_trends",
        name="Сбор трендов",
    )
    if getattr(cfg.analytics, "enabled", True):
        scheduler.add_job(
            job_analytics_insights,
            CronTrigger(timezone=tz, **analytics_kw),
            id="analytics_insights",
            name="ИИ-аналитика",
        )
    scheduler.add_job(
        job_competitor_prices,
        CronTrigger(timezone=tz, **competitors_kw),
        id="competitor_prices",
        name="Цены конкурентов",
    )
    if getattr(cfg.mail_inbox, "enabled", False):
        scheduler.add_job(
            job_mail_inbox,
            CronTrigger(timezone=tz, **mail_kw),
            id="mail_inbox",
            name="Входящая почта",
        )

    scheduler.add_listener(_on_job_finished, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    logger.info("Планировщик: зарегистрировано задач (TZ=%s)", cfg.property.timezone)
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Инициализировать БД и запустить планировщик."""
    init_db()
    scheduler = create_scheduler()
    scheduler.start()
    return scheduler
