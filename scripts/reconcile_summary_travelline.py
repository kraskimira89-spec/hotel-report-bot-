#!/usr/bin/env python3
"""CLI: сверка сводки с TravelLine."""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.data_sources.summary_reconcile import (
    build_summary_travelline_reconcile,
    run_summary_travelline_reconcile,
    save_reconcile_report,
)
from src.data_sources.travelline import TravelLineError
from src.storage.db import init_db


def _print_report(data: dict) -> None:
    print(f"=== Сверка сводки vs TravelLine · {data['report_date']} ===")
    print(
        f"dry_run={data.get('dry_run')} · "
        f"occupancy={data['summary_sources']['occupancy']} · "
        f"bookings={data['summary_sources']['bookings']}"
    )
    print()
    print(f"{'Метрика':<40} {'Сводка':>12} {'TravelLine':>12} {'OK':>4}  Примечание")
    print("-" * 90)
    for row in data["comparisons"]:
        s = row["summary"]
        t = row["travelline"]
        s_txt = "—" if s is None else str(s)
        t_txt = "—" if t is None else str(t)
        mark = "✓" if row["ok"] else "✗"
        print(f"{row['name']:<40} {s_txt:>12} {t_txt:>12} {mark:>4}  {row['note']}")
    tl = data["travelline_raw"]
    print()
    print(
        f"TL ADR={tl.get('adr')}  RevPAR={tl.get('revpar')}  "
        f"revenue={tl.get('revenue')}"
    )
    print()
    print("ИТОГ:", "OK" if data["all_ok"] else "ЕСТЬ РАСХОЖДЕНИЯ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Сверка сводки с TravelLine")
    parser.add_argument("--date", help="YYYY-MM-DD (по умолчанию — сегодня)")
    parser.add_argument("--json-out", help="Доп. путь для JSON (опционально)")
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Не писать в data/reconcile/",
    )
    args = parser.parse_args()

    reload_config()
    init_db()
    report_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else date.today()
    )

    try:
        if args.no_save:
            data = build_summary_travelline_reconcile(report_date)
        else:
            data = run_summary_travelline_reconcile(report_date)
    except TravelLineError as exc:
        print(f"TravelLine недоступен: {exc}", file=sys.stderr)
        return 2

    _print_report(data)

    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = _ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        import json

        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON: {out}")

    return 0 if data["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
