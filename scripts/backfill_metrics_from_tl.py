#!/usr/bin/env python3
"""Backfill metrics_daily из TravelLine для прогноза."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.forecast.metrics_history import backfill_metrics_history
from src.storage.db import get_metrics_daily, init_db
from src.utils.logging_setup import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill metrics_daily из TravelLine")
    parser.add_argument("--days", type=int, default=365, help="Глубина истории (дней)")
    parser.add_argument("--force", action="store_true", help="Перезаписать существующие дни")
    parser.add_argument("--delay", type=float, default=0.15, help="Пауза между днями (сек)")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Только daily-метрики без категорий/WebPMS (быстрый сезон для прогноза)",
    )
    args = parser.parse_args()
    setup_logging()
    reload_config()
    init_db()
    end = date.today()
    start = end - timedelta(days=max(1, args.days) - 1)
    delay = 0.0 if args.fast and args.delay == 0.15 else args.delay
    if args.fast and args.delay == 0.15:
        delay = 0.0
    stats = backfill_metrics_history(
        days=args.days,
        force=args.force,
        delay_sec=delay,
        daily_only=args.fast,
    )
    unique = len({m.report_date for m in get_metrics_daily(start, end)})
    print("backfill:", stats, "fast=" + str(args.fast))
    print(f"unique_days_in_db={unique}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
