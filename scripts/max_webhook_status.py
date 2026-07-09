#!/usr/bin/env python3
"""Статус webhook Max: список подписок или отписка."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import get_config, reload_config
from src.notifiers.max_api import build_max_api_client


def main() -> int:
    parser = argparse.ArgumentParser(description="Webhook Max Bot API")
    parser.add_argument(
        "--delete",
        metavar="URL",
        help="DELETE /subscriptions — отписаться от URL",
    )
    args = parser.parse_args()

    reload_config()
    client = build_max_api_client(get_config())
    if client is None:
        print("MAX_TOKEN не задан в .env", file=sys.stderr)
        return 1

    if args.delete:
        result = client.delete_subscription(args.delete.strip())
    else:
        result = client.list_subscriptions()
    print(result)
    if isinstance(result, dict) and result.get("success") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
