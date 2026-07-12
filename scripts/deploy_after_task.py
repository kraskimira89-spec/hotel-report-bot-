#!/usr/bin/env python3
"""Деплой после завершения задачи агента / вручную."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.deploy.vps_deploy import run_deploy


def main() -> int:
    parser = argparse.ArgumentParser(description="Деплой hotel-report-bot на VPS")
    parser.add_argument(
        "--trigger",
        default="manual",
        help="Метка источника (manual, cursor_agent, job:…)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Игнорировать debounce min_interval_minutes",
    )
    args = parser.parse_args()
    ok = run_deploy(trigger=args.trigger, force=args.force)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
