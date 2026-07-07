"""Отправка HTML email-отчётов через smtplib."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from src.config import AppConfig, get_config, get_env_settings

logger = logging.getLogger(__name__)


def send_html_report(
    subject: str,
    html_body: str,
    text_plain: str,
    dry_run: bool | None = None,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    """Отправить HTML-письмо с текстовым дублем.

    # TODO: этап 6 — шаблон еженедельного отчёта.
    """
    cfg = config or get_config()
    env = get_env_settings()
    is_dry = cfg.dry_run if dry_run is None else dry_run

    recipients = cfg.email.to_addresses
    full_subject = f"{cfg.email.subject_prefix} {subject}"

    if is_dry:
        logger.info(
            "[DRY-RUN] Email → %s: %s (%s bytes HTML)",
            recipients,
            full_subject,
            len(html_body),
        )
        return {"status": "dry_run", "recipients": recipients}

    if not env.smtp_host or not recipients:
        logger.warning("SMTP не настроен или нет получателей")
        return {"status": "skipped"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = full_subject
    msg["From"] = cfg.email.from_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(env.smtp_host, env.smtp_port) as server:
        if env.smtp_use_tls:
            server.starttls()
        if env.smtp_user:
            server.login(env.smtp_user, env.smtp_password)
        server.sendmail(cfg.email.from_address, recipients, msg.as_string())

    logger.info("Email отправлен: %s", full_subject)
    return {"status": "sent", "recipients": recipients}
