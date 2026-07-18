"""Обработка webhook-событий Max Bot API."""

from __future__ import annotations

import logging
from typing import Any

from src.config import get_config, get_env_settings
from src.notifiers.max_api import (
    discover_chat_ids,
    extract_callback,
    extract_display_name,
    extract_message_text,
    parse_updates,
)
from src.staff_bot.dialog import dispatch_callback, dispatch_text, handle_staff_command
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
    cfg = get_config()
    updates = parse_updates(payload)
    chat_ids = discover_chat_ids(payload)
    results: list[dict[str, Any]] = []

    for upd in updates:
        logger.info(
            "Max webhook: type=%s chat_id=%s user_id=%s",
            upd.update_type,
            upd.chat_id,
            upd.user_id,
        )
        display_name = extract_display_name(upd.raw)

        if upd.update_type == "bot_started":
            # Первое подключение: всегда отвечаем (сводка в 9:00)
            results.append(
                handle_staff_command(
                    command="start",
                    user_id=upd.user_id,
                    chat_id=upd.chat_id,
                    display_name=display_name,
                    config=cfg,
                )
            )
            continue

        if upd.update_type == "message_created":
            text = extract_message_text(upd.raw)
            if not text.strip():
                continue
            # /start и «Начать» обрабатываем всегда
            from src.staff_bot.templates import resolve_command

            cmd = resolve_command(text)
            if cmd == "start" or cfg.staff_bot.enabled:
                result = dispatch_text(
                    text,
                    user_id=upd.user_id,
                    chat_id=upd.chat_id,
                    display_name=display_name,
                    config=cfg,
                )
                if result:
                    results.append(result)
            continue

        if upd.update_type == "message_callback":
            if not cfg.staff_bot.enabled:
                continue
            callback_id, cb_payload = extract_callback(upd.raw)
            # cmd:start — всегда
            if (cb_payload or "").strip() in ("cmd:start",) or cfg.staff_bot.enabled:
                results.append(
                    dispatch_callback(
                        cb_payload or "",
                        user_id=upd.user_id,
                        chat_id=upd.chat_id,
                        display_name=display_name,
                        callback_id=callback_id,
                        config=cfg,
                    )
                )
            continue

    if chat_ids:
        logger.info("Max webhook chat_ids: %s", chat_ids)
    return {
        "ok": True,
        "updates": len(updates),
        "chat_ids": chat_ids,
        "handled": len(results),
        "results": results,
    }


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
