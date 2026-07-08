"""Технические уведомления о сбоях источников."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from src.config import AppConfig, get_config
from src.notifiers.email_sender import send_html_report
from src.notifiers.max_bot import send_message
from src.storage.db import save_error_log
from src.storage.models import ErrorLogRecord

logger = logging.getLogger(__name__)


def send_incident(
    title: str,
    details: str,
    *,
    config: AppConfig | None = None,
    source: str = "incident",
) -> dict[str, Any]:
    """Отправить техническое уведомление (Max + email)."""
    cfg = config or get_config()
    text = f"⚠️ {title}\n{details}"
    html = (
        "<h2>⚠️ " + title + "</h2>"
        + "<p>" + details.replace("\n", "<br>") + "</p>"
    )

    max_result = send_message(text, config=cfg)
    email_result = send_html_report(
        subject=f"Сбой: {title}",
        html_body=html,
        text_plain=text,
        config=cfg,
    )

    save_error_log(
        ErrorLogRecord(
            error_date=date.today(),
            source=source,
            error_type="incident",
            message=title,
            details=details[:500],
        )
    )

    logger.warning("Отправлено инцидент-уведомление: %s", title)
    return {"max": max_result, "email": email_result}
