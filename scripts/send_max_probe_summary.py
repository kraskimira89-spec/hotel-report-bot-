#!/usr/bin/env python3
"""Отправить полную ежедневную сводку в Max (test chat при dry_run)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.notifiers.max_bot import send_daily_summary
from src.storage.db import init_db
from src.utils.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    reload_config()
    init_db()
    result = send_daily_summary(report_date=date.today())
    print(
        "status={status} parts={parts} dry_run={dry_run}".format(
            status=result.get("status"),
            parts=result.get("parts"),
            dry_run=result.get("dry_run"),
        )
    )
    return 0 if result.get("status") in {"sent", "ok"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
