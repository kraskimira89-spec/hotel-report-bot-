#!/usr/bin/env python3
"""Проверка Issue #18: сводка из TravelLine."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.data_sources.travelline import run_daily_reconciliation
from src.notifiers.max_bot import prepare_daily_summary_data
from src.storage.db import init_db


def main() -> None:
    reload_config()
    init_db()
    report_date = date.today()
    warnings = run_daily_reconciliation(report_date)
    print(f"report_date={report_date.isoformat()}")
    print(f"reconcile_warnings={len(warnings)}")
    for w in warnings:
        print(f"  WARN: {w.message}")
    if not warnings:
        print("  OK")
    data = prepare_daily_summary_data(report_date)
    print(f"occupancy={data.occupancy_pct}")
    print(f"bookings={data.new_bookings_total}")
    print(f"occ_src={data.occupancy_source}")
    print(f"book_src={data.bookings_source}")
    print(f"critical={data.critical_error}")
    if data.warnings:
        print("summary_warnings:")
        for note in data.warnings:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
