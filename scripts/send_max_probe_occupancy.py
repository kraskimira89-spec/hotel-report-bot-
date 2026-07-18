#!/usr/bin/env python3
"""Пробная сводка: только блок загрузки (реальные TL-цифры), без конкурентов."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import reload_config
from src.notifiers.max_bot import (
    build_daily_summary_sections,
    prepare_daily_summary_data,
    send_message,
)
from src.storage.db import init_db
from src.utils.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    reload_config()
    init_db()
    data = prepare_daily_summary_data(date.today())
    # Только блок загрузки — проверить сходимость % и «занято»
    data.competitors = []
    data.bookings_by_channel = []
    occ = build_daily_summary_sections(data)[0]
    print(occ)
    print(
        f"check sold={data.totals.occupied if data.totals else None} "
        f"total={data.totals.total if data.totals else None} "
        f"pct={data.occupancy_pct} source={data.occupancy_source}"
    )
    if data.totals and data.totals.total:
        expected = round(100.0 * data.totals.occupied / data.totals.total, 1)
        print(f"expected_pct_from_totals={expected}")
    result = send_message(occ)
    print("send=", result.get("status"), result.get("chat_id"))
    return 0 if result.get("status") == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
