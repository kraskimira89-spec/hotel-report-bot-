#!/usr/bin/env python3
"""Пробная сводка Max с разделом Конкуренты."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import reload_config
from src.notifiers.max_bot import (
    build_daily_summary_sections,
    prepare_daily_summary_data,
    send_daily_summary,
)
from src.storage.db import init_db
from src.utils.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    reload_config()
    init_db()
    data = prepare_daily_summary_data(date.today())
    sections = build_daily_summary_sections(data)
    print("=== SECTIONS ===")
    for i, sec in enumerate(sections):
        print(f"--- {i} ---")
        print(sec)
        print()
    has_comp = any("Конкуренты" in s for s in sections)
    print("has_competitors_section=", has_comp)
    print("competitors_count=", len(data.competitors))
    result = send_daily_summary(report_date=date.today(), summary_data=data)
    print("send=", result.get("status"), "chat=", result.get("chat_id"), "dry_run=", result.get("dry_run"))
    if result.get("status") not in {"sent", "ok"}:
        print("full=", result)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
