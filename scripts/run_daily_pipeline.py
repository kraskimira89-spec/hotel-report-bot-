#!/usr/bin/env python3
"""Ручной прогон ежедневного пайплайна (этап 11, dry-run)."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.data_sources.summary_reconcile import run_summary_travelline_reconcile
from src.data_sources.travelline import run_daily_reconciliation
from src.notifiers.max_bot import prepare_daily_summary_data, send_daily_summary
from src.scheduler import job_price_snapshot
from src.storage.db import init_db


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ежедневный пайплайн hotel-report-bot")
    parser.add_argument(
        "--date",
        help="Дата отчёта YYYY-MM-DD (по умолчанию — сегодня MSK)",
    )
    parser.add_argument("--snapshot", action="store_true", help="Собрать snapshot цен")
    parser.add_argument("--reconcile", action="store_true", help="Сверка TL ↔ ГуглТабл")
    parser.add_argument(
        "--summary-reconcile",
        action="store_true",
        help="Сверка сводки Max vs TravelLine",
    )
    parser.add_argument("--summary", action="store_true", help="Отправить сводку в Max")
    parser.add_argument(
        "--all",
        action="store_true",
        help="snapshot + reconcile + summary + summary-reconcile",
    )
    args = parser.parse_args()

    if not (
        args.snapshot
        or args.reconcile
        or args.summary
        or args.summary_reconcile
        or args.all
    ):
        args.all = True

    reload_config()
    init_db()
    report_date = _parse_date(args.date) if args.date else date.today()
    run_date = date.today()

    print(f"Пайплайн: report_date={report_date:%d.%m.%Y}, run_date={run_date:%d.%m.%Y}")

    if args.all or args.snapshot:
        print("\n[1/4] Snapshot цен...")
        job_price_snapshot(report_date=report_date, run_date=run_date)

    if args.all or args.reconcile:
        print("\n[2/4] Сверка TravelLine ↔ ГуглТабл...")
        warnings = run_daily_reconciliation(report_date)
        if warnings:
            for w in warnings:
                print("  ⚠", w.message)
        else:
            print("  OK — расхождений нет")

    if args.all or args.summary:
        print("\n[3/4] Сводка Max...")
        data = prepare_daily_summary_data(report_date)
        result = send_daily_summary(
            report_date=report_date,
            summary_data=data,
            run_date=run_date,
        )
        print(
            "  status:", result.get("status"),
            "dry_run:", result.get("dry_run"),
            "occupancy:", data.occupancy_pct,
            "bookings:", data.new_bookings_total,
            "occ_src:", data.occupancy_source,
            "book_src:", data.bookings_source,
        )

    if args.all or args.summary_reconcile:
        print("\n[4/4] Сверка сводки vs TravelLine...")
        reconcile_data = run_summary_travelline_reconcile(report_date)
        failed = [c for c in reconcile_data["comparisons"] if not c["ok"]]
        print(
            "  all_ok:", reconcile_data["all_ok"],
            "dry_run:", reconcile_data.get("dry_run"),
            "failed:", len(failed),
        )
        if failed:
            for row in failed:
                print("  ⚠", row["name"], "—", row["note"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
