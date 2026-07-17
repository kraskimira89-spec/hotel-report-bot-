#!/usr/bin/env python3
from datetime import date

from src.notifiers.max_bot import build_daily_summary_sections, prepare_daily_summary_data

d = prepare_daily_summary_data(date.today())
print("prices", len(d.prices))
sec = build_daily_summary_sections(d)[0]
for line in sec.splitlines():
    if line.startswith("•") or line.startswith("*Итого") or "за " in line:
        print(line.encode("unicode_escape").decode("ascii"))
