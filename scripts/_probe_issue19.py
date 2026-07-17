#!/usr/bin/env python3
"""Проверка Issue #19: цены конкурентов TL/WuBook виджетов в БД."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.storage.db import db_session, init_db


WIDGET_NAMES = (
    "Bon Apart (Банапарт)",
    "Центральный",
    "Скандинавия",
    "Парад Парк",
    "Элегант",
    "Xander Hotel",
)


def main() -> None:
    reload_config()
    init_db()
    with db_session() as conn:
        for name in WIDGET_NAMES:
            agg = conn.execute(
                """
                SELECT date, price_from, available, source, screenshot_path
                FROM competitor_prices
                WHERE competitor_name = ? AND COALESCE(category, '') = ''
                ORDER BY date DESC, id DESC LIMIT 1
                """,
                (name,),
            ).fetchone()
            cats = conn.execute(
                """
                SELECT category, price_from
                FROM competitor_prices
                WHERE competitor_name = ? AND COALESCE(category, '') != ''
                ORDER BY date DESC, id DESC LIMIT 5
                """,
                (name,),
            ).fetchall()
            print(f"=== {name} ===")
            if agg:
                print(
                    f"  aggregate: date={agg['date']} price={agg['price_from']} "
                    f"available={agg['available']} source={agg['source']}"
                )
            else:
                print("  aggregate: none")
            if cats:
                for c in cats:
                    print(f"  cat: {c['category']} = {c['price_from']}")
            else:
                print("  categories: none")


if __name__ == "__main__":
    main()
