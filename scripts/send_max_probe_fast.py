#!/usr/bin/env python3
"""Быстрая пробная сводка Max: без тяжёлого TL occupancy, данные из БД + competitors."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import reload_config
from src.notifiers.max_bot import (
    DailySummaryData,
    RoomStatusSummary,
    _collect_competitor_summary,
    build_daily_summary_sections,
    send_daily_summary,
)
from src.storage.db import init_db
from src.utils.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    reload_config()
    init_db()
    today = date.today()
    # Лёгкая сводка без TL: только чтобы проверить формат сообщений
    data = DailySummaryData(
        report_date=today,
        room_types=[
            RoomStatusSummary(label="1-КК 23", occupied=9, free=0, booked=0),
            RoomStatusSummary(label="1-КК 27", occupied=3, free=0, booked=0),
        ],
        totals=RoomStatusSummary(label="Итого", occupied=12, free=0, booked=0),
        occupancy_pct=54.5,
        occupancy_light="🟡",
        new_bookings_total=5,
        new_bookings_light="🟢",
        competitors=_collect_competitor_summary(today),
    )
    sections = build_daily_summary_sections(data)
    print("parts_preview=", len(sections))
    for i, s in enumerate(sections[:4]):
        print(f"--- {i} ---\n{s}\n")
    result = send_daily_summary(report_date=today, summary_data=data)
    print("send=", result.get("status"), "parts=", result.get("parts"))
    return 0 if result.get("status") == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
