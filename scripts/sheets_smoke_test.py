#!/usr/bin/env python3
"""Проверка подключения Google Sheets (этап 1)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import get_config, get_env_settings, reload_config
from src.data_sources.sheets import GoogleSheetsClient, SheetsReadError


def main() -> int:
    reload_config()
    env = get_env_settings()
    cfg = get_config()
    sa_path = env.google_sa_json_path.strip()

    print("=== Google Sheets smoke test ===")
    print("spreadsheet:", cfg.sheets.spreadsheet_title)
    print("spreadsheet_id:", cfg.sheets.spreadsheet_id)
    print("GOOGLE_SA_JSON_PATH:", sa_path or "(не задан)")

    if not sa_path:
        print("\nШаг 3: задайте GOOGLE_SA_JSON_PATH в config/.env")
        return 1
    if not Path(sa_path).is_file():
        print(f"\nФайл ключа не найден: {sa_path}")
        return 1

    try:
        client = GoogleSheetsClient(cfg)
        client._get_client()
        print("Авторизация: OK")
    except SheetsReadError as exc:
        print("Авторизация: FAIL —", exc)
        return 1
    except Exception as exc:
        print("Авторизация: FAIL —", exc)
        return 1

    report_date = date.today()
    print(f"\nДата отчёта: {report_date:%d.%m.%Y}")

    try:
        occ = client.read_occupancy_daily(report_date)
        print(f"Заселяемость: типов={len(occ.by_type)}, total={occ.total_pct}, TL={occ.travelline_pct}")
        if occ.by_type:
            sample = occ.by_type[0]
            print(f"  пример: {sample.room_type} = {sample.occupancy_pct}%")

        bookings = client.read_bookings_for_date(report_date)
        total_day = sum(b.count for b in bookings)
        top = sorted(bookings, key=lambda x: -x.count)[:5]
        print(f"Брони за день: источников={len(bookings)}, всего={total_day}")
        for item in top:
            if item.count:
                print(f"  {item.source}: {item.count}")

        month = client.read_bookings_month(report_date.year, report_date.month)
        print(f"Брони за месяц: total={month.total}, источников={len(month.by_source)}")
    except Exception as exc:
        print("Чтение листов: FAIL —", exc)
        return 1

    print("\nИтог: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
