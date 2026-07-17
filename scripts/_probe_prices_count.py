#!/usr/bin/env python3
from datetime import date

from src.storage.db import db_session, get_price_snapshots_by_date, init_db

init_db()
with db_session() as c:
    r = c.execute(
        "SELECT COUNT(*) AS cnt, MAX(date(snapshot_at)) AS last_d FROM price_snapshots"
    ).fetchone()
    print("count", r["cnt"], "last", r["last_d"])
print("today", len(get_price_snapshots_by_date(date.today())))
