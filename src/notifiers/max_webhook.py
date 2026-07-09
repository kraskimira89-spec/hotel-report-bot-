"""Обработка webhook-событий Max Bot API."""

from __future__ import annotations

import logging
from typing import Any

from src.config import get_env_settings
from src.notifiers.max_api import discover_chat_ids, parse_updates
from src.storage.db import save_error_log
from src.storage.models import ErrorLogRecord

logger = logging.getLogger(__name__)


def verify_webhook_secret(header_value: str | None) -> bool:
    """Проверка заголовка X-Max-Bot-Api-Secret."""
    secret = get_env_settings().max_webhook_secret.strip()
    if not secret:
        return True
    return header_value == secret


def handle_max_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Обработать Update от Max (POST /subscriptions → наш endpoint)."""
    updates = parse_updates(payload)
    chat_ids = discover_chat_ids(payload)
    for upd in updates:
        logger.info(
            "Max webhook: type=%s chat_id=%s user_id=%s",
            upd.update_type,
            upd.chat_id,
            upd.user_id,
        )
    if chat_ids:
        logger.info("Max webhook chat_ids: %s", chat_ids)
    return {"ok": True, "updates": len(updates), "chat_ids": chat_ids}


def log_webhook_error(message: str) -> None:
    from datetime import date

    save_error_log(
        ErrorLogRecord(
            error_date=date.today(),
            source="max_webhook",
            error_type="webhook",
            message=message,
        )
    )
