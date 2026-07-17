#!/usr/bin/env python3
"""Диагностика цен в сводке Max."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.notifiers.max_bot import prepare_daily_summary_data, build_daily_summary_sections
from src.storage.db import (
    compare_prices_yesterday,
    db_session,
    get_price_snapshots_by_date,
    init_db,
)
from src.utils.category_labels import category_short_label


def main() -> None:
    reload_config()
    init_db()
    d = date.today()
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*), MIN(snapshot_at), MAX(snapshot_at) FROM price_snapshots"
        ).fetchone()
        print("price_snapshots_all", dict(row) if row else None)
        last = conn.execute(
            "SELECT date(snapshot_at) AS d, COUNT(*) AS c FROM price_snapshots "
            "GROUP BY date(snapshot_at) ORDER BY d DESC LIMIT 5"
        ).fetchall()
        for r in last:
            print("day", r["d"], "count", r["c"])

    snaps = get_price_snapshots_by_date(d)
    print("snaps_today", len(snaps), [(s.category, s.price) for s in snaps])
    cmp = compare_prices_yesterday(d)
    print("compare", len(cmp), [(c.category, c.reference_price) for c in cmp])

    data = prepare_daily_summary_data(d)
    print("summary_prices", len(data.prices))
    for p in data.prices:
        print("P", category_short_label(p.category), p.price, p.category)
    for r in data.room_types:
        print("R", category_short_label(r.label), "|", r.label)

    sec0 = build_daily_summary_sections(data)[0]
    for line in sec0.splitlines():
        if line.startswith("•") or line.startswith("*Итого"):
            print("LINE", line)


if __name__ == "__main__":
    main()
