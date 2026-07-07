"""Отправка сообщений через Max Bot API."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from src.config import AppConfig, get_config, get_env_settings

logger = logging.getLogger(__name__)


def _truncate_message(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def send_message(
    text: str,
    dry_run: bool | None = None,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    """Отправить сообщение в Max (POST /messages).

    При dry_run=True — только лог, без отправки.
    Backoff при 429/5xx.
    """
    cfg = config or get_config()
    env = get_env_settings()
    is_dry = cfg.dry_run if dry_run is None else dry_run

    message = _truncate_message(text, cfg.max_bot.max_message_length)
    chat_id = cfg.max_bot.test_chat_id if is_dry else cfg.max_bot.chat_id

    if is_dry or not env.max_token:
        logger.info("[DRY-RUN] Max → chat %s: %s", chat_id, message[:200])
        return {"status": "dry_run", "chat_id": chat_id}

    url = f"{cfg.max_bot.api_url.rstrip('/')}/messages"
    headers = {"Authorization": env.max_token}
    payload = {"chat_id": chat_id, "text": message, "format": "markdown"}

    delay = 1.0
    for attempt in range(3):
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
            if resp.status_code in (429, 500, 502, 503, 504):
                logger.warning("Max API %s, retry %s", resp.status_code, attempt + 1)
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.error("Ошибка Max API: %s", exc)
            if attempt < 2:
                time.sleep(delay)
                delay *= 2
            else:
                raise

    return {"status": "error"}
