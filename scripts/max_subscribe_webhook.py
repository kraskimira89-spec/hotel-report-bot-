#!/usr/bin/env python3
"""Подписка на webhook Max Bot API (POST /subscriptions)."""

from __future__ import annotations

import sys

from src.config import get_config, get_env_settings
from src.notifiers.max_api import build_max_api_client


def main() -> int:
    cfg = get_config()
    url = (cfg.max_bot.webhook_url or "").strip()
    if not url:
        print("Задайте max_bot.webhook_url в settings.yaml", file=sys.stderr)
        return 1
    client = build_max_api_client(cfg)
    if client is None:
        print("MAX_TOKEN не задан в .env", file=sys.stderr)
        return 1
    secret = get_env_settings().max_webhook_secret.strip() or None
    result = client.create_subscription(
        url,
        update_types=cfg.max_bot.webhook_update_types,
        secret=secret,
    )
    print(result)
    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
