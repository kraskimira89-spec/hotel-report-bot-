"""Отправка HTML email-отчётов через smtplib."""

from __future__ import annotations

import logging
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Protocol

from src.config import AppConfig, get_config, get_db_path, get_env_settings
from src.data_sources.market_trends import CompetitorPriceInfo
from src.data_sources.sheets import OccupancySheetData
from src.notifiers.weekly.data import prepare_weekly_report_data as _prepare_v2
from src.notifiers.weekly.html import build_weekly_report_html as _html_v2
from src.notifiers.weekly.models import MetricsSummary, OccupancyTypeRow, WeeklyReportData
from src.notifiers.weekly.plain import build_weekly_report_plain as _plain_v2
from src.notifiers.weekly.subject import build_weekly_subject
from src.storage.db import save_error_log, save_report_log
from src.storage.models import ErrorLogRecord, ReportLogRecord

logger = logging.getLogger(__name__)

__all__ = [
    "CompetitorPriceInfo",
    "MetricsSummary",
    "OccupancyTypeRow",
    "WeeklyReportData",
    "prepare_weekly_report_data",
    "build_weekly_report_html",
    "build_weekly_report_plain",
    "send_html_report",
    "send_weekly_report",
]


class SmtpSender(Protocol):
    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> Any: ...


def prepare_weekly_report_data(
    period_start: date,
    period_end: date,
    config: AppConfig | None = None,
    occupancy: OccupancySheetData | None = None,
) -> WeeklyReportData:
    """Собрать данные weekly email v2."""
    cfg = config or get_config()
    return _prepare_v2(
        period_start,
        period_end,
        config=cfg,
        occupancy=occupancy,
        use_llm=cfg.email.use_llm,
    )


def build_weekly_report_html(data: WeeklyReportData) -> str:
    return _html_v2(data)


def build_weekly_report_plain(data: WeeklyReportData) -> str:
    return _plain_v2(data)


def _snapshot_dir() -> Path:
    d = get_db_path().parent / "report_snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_snapshots(
    report_date: date,
    run_date: date,
    html_body: str,
    plain: str,
) -> tuple[str, str]:
    base = _snapshot_dir()
    stem = f"email_{report_date.isoformat()}_{run_date.isoformat()}"
    html_path = base / f"{stem}.html"
    txt_path = base / f"{stem}.txt"
    html_path.write_text(html_body, encoding="utf-8")
    txt_path.write_text(plain, encoding="utf-8")
    return str(html_path), str(txt_path)


def _resolve_recipients(cfg: AppConfig, dry_run: bool) -> list[str]:
    if dry_run:
        return cfg.email.test_addresses
    return cfg.email.to_addresses


def send_html_report(
    subject: str,
    html_body: str,
    text_plain: str,
    dry_run: bool | None = None,
    config: AppConfig | None = None,
    smtp_factory: Callable[[], Any] | None = None,
    *,
    use_subject_prefix: bool = True,
) -> dict[str, Any]:
    """Отправить HTML-письмо с текстовым дублем."""
    cfg = config or get_config()
    env = get_env_settings()
    is_dry = cfg.dry_run if dry_run is None else dry_run
    recipients = _resolve_recipients(cfg, is_dry)
    full_subject = (
        f"{cfg.email.subject_prefix} {subject}" if use_subject_prefix else subject
    )

    if not recipients:
        reason = "no_test_addresses" if is_dry else "no_recipients"
        logger.warning("Email пропущен: %s (dry_run=%s)", reason, is_dry)
        save_error_log(
            ErrorLogRecord(
                error_date=date.today(),
                source="email_sender",
                error_type=reason,
                message="Нет получателей для email",
            )
        )
        return {"status": "skipped", "reason": reason, "dry_run": is_dry}

    if is_dry:
        logger.info(
            "[DRY-RUN] Email → %s: %s (%s bytes HTML)",
            recipients,
            full_subject,
            len(html_body),
        )

    if not env.smtp_host:
        logger.warning("SMTP не настроен")
        save_error_log(
            ErrorLogRecord(
                error_date=date.today(),
                source="email_sender",
                error_type="no_smtp",
                message="SMTP не настроен",
            )
        )
        return {"status": "skipped", "reason": "no_smtp", "dry_run": is_dry}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = full_subject
    msg["From"] = cfg.email.from_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if smtp_factory:
            server = smtp_factory()
            server.sendmail(cfg.email.from_address, recipients, msg.as_string())
            if hasattr(server, "quit"):
                server.quit()
        else:
            use_ssl = bool(env.smtp_use_ssl) or int(env.smtp_port) == 465
            if use_ssl:
                with smtplib.SMTP_SSL(env.smtp_host, env.smtp_port) as server:
                    if env.smtp_user:
                        server.login(env.smtp_user, env.smtp_password)
                    server.sendmail(cfg.email.from_address, recipients, msg.as_string())
            else:
                with smtplib.SMTP(env.smtp_host, env.smtp_port) as server:
                    if env.smtp_use_tls:
                        server.starttls()
                    if env.smtp_user:
                        server.login(env.smtp_user, env.smtp_password)
                    server.sendmail(cfg.email.from_address, recipients, msg.as_string())
    except smtplib.SMTPException as exc:
        logger.error("Ошибка SMTP: %s", exc)
        save_error_log(
            ErrorLogRecord(
                error_date=date.today(),
                source="email_sender",
                error_type="smtp_error",
                message=str(exc),
            )
        )
        return {"status": "error", "reason": "smtp_error", "dry_run": is_dry}

    logger.info("Email отправлен: %s → %s", full_subject, recipients)
    return {
        "status": "sent",
        "recipients": recipients,
        "dry_run": is_dry,
        "recipient_count": len(recipients),
    }


def send_weekly_report(
    period_start: date | None = None,
    period_end: date | None = None,
    run_date: date | None = None,
    report_date: date | None = None,
    config: AppConfig | None = None,
    report_data: WeeklyReportData | None = None,
    smtp_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Собрать и отправить еженедельный отчёт v2; записать в reports_log."""
    cfg = config or get_config()
    run_date = run_date or date.today()
    report_date = report_date or run_date
    period_end = period_end or (report_date - timedelta(days=1))
    period_start = period_start or (period_end - timedelta(days=6))

    data = report_data or _prepare_v2(
        period_start,
        period_end,
        config=cfg,
        report_date=report_date,
        use_llm=cfg.email.use_llm,
    )

    if data.critical_error:
        from src.notifiers.incidents import send_incident

        send_incident(
            "Критическая ошибка источника",
            "\n".join(data.warnings) or "Ключевые источники недоступны.",
            config=cfg,
            source="email_sender",
        )
        save_report_log(
            ReportLogRecord(
                report_type="email",
                report_date=report_date,
                run_date=run_date,
                period_start=period_start,
                period_end=period_end,
                status="skipped",
                dry_run=cfg.dry_run,
                preview="; ".join(data.warnings)[:200],
                message="critical_error",
                data_quality=data.data_quality.overall,
                error_message="critical_error",
            )
        )
        return {
            "status": "skipped",
            "reason": "critical_error",
            "dry_run": cfg.dry_run,
            "warnings": data.warnings,
        }

    html_body = build_weekly_report_html(data)
    plain = build_weekly_report_plain(data)
    subject = build_weekly_subject(data)

    if data.warnings:
        from src.notifiers.incidents import send_incident

        send_incident(
            "Неполные данные weekly-отчёта",
            "\n".join(data.warnings),
            config=cfg,
            source="email_sender",
        )

    result = send_html_report(
        subject=subject,
        html_body=html_body,
        text_plain=plain,
        config=cfg,
        smtp_factory=smtp_factory,
        use_subject_prefix=False,
    )

    status = "sent" if result.get("status") == "sent" else result.get("status", "error")
    html_path, _txt_path = _save_snapshots(report_date, run_date, html_body, plain)
    save_report_log(
        ReportLogRecord(
            report_type="email",
            report_date=report_date,
            run_date=run_date,
            period_start=period_start,
            period_end=period_end,
            status=status,
            dry_run=cfg.dry_run,
            preview=plain[:200],
            message=str(result),
            recipient_count=result.get("recipient_count"),
            data_quality=data.data_quality.overall,
            html_snapshot_path=html_path,
            plain_text_snapshot=plain,
            error_message=result.get("reason") if status != "sent" else None,
        )
    )

    if status == "sent":
        from src.storage.db import log_trends_in_email

        trend_ids = [t.trend_id for t in data.industry_trends if t.trend_id]
        if trend_ids:
            log_trends_in_email(trend_ids, report_date, period_start, period_end)

    return {**result, "period_start": period_start, "period_end": period_end}