#!/usr/bin/env python3
"""Dry-run еженедельного отчёта v2 (локально или на VPS)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import get_config, reload_config
from src.notifiers.email_sender import send_weekly_report
from src.storage.db import init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Тестовый weekly email v2 (dry-run)")
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Выполнить init_db перед отправкой",
    )
    args = parser.parse_args()

    reload_config()
    if args.init_db:
        init_db()

    cfg = get_config()
    cfg = cfg.model_copy(update={"dry_run": True})
    result = send_weekly_report(config=cfg)
    print(result)
    return 0 if result.get("status") in ("sent", "dry_run", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
