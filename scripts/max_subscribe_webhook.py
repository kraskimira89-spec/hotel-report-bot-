#!/usr/bin/env python3
"""Подписка на webhook Max Bot API (POST /subscriptions)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import get_config, get_env_settings, reload_config
from src.notifiers.max_api import build_max_api_client

_SECRET_RE = re.compile(r"^[a-zA-Z0-9_-]{5,256}$")


def _validate_secret(secret: str) -> str | None:
    if not secret:
        return "MAX_WEBHOOK_SECRET не задан (рекомендуется для production)"
    if not _SECRET_RE.fullmatch(secret):
        return (
            "MAX_WEBHOOK_SECRET: только A-Z, a-z, 0-9, дефис, длина 5–256 "
            "(требование Max API)"
        )
    return None


def main() -> int:
    reload_config()
    cfg = get_config()
    url = (cfg.max_bot.webhook_url or "").strip()
    if not url:
        print(
            "Задайте MAX_WEBHOOK_URL в .env или max_bot.webhook_url в settings.yaml",
            file=sys.stderr,
        )
        return 1
    if not url.startswith("https://"):
        print("webhook_url должен начинаться с https://", file=sys.stderr)
        return 1

    client = build_max_api_client(cfg)
    if client is None:
        print("MAX_TOKEN не задан в .env", file=sys.stderr)
        return 1

    secret = get_env_settings().max_webhook_secret.strip() or None
    secret_error = _validate_secret(secret or "")
    if secret_error:
        print(f"Предупреждение: {secret_error}", file=sys.stderr)

    print(f"Подписка: {url}")
    print(f"Типы: {', '.join(cfg.max_bot.webhook_update_types)}")
    result = client.create_subscription(
        url,
        update_types=cfg.max_bot.webhook_update_types,
        secret=secret,
    )
    print(result)
    if result.get("success") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
