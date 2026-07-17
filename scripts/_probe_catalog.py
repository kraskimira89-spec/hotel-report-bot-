"""Быстрая проверка catalog fallback для Центрального и Xander."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import get_config, reload_config
from src.data_sources.competitor_prices import collect_competitor_prices
from src.data_sources.market_trends import collect_and_save_competitor_prices


def main() -> None:
    reload_config()
    cfg = get_config()
    result = collect_competitor_prices(
        cfg.competitors,
        cfg.site_prices,
        enable_widgets=False,
    )
    for name in ("Центральный", "Xander Hotel"):
        row = result.get(name)
        if row is None:
            print(name, "MISSING")
            continue
        print(
            name,
            "price=",
            row.price_from,
            "kind=",
            row.price_kind,
            "products=",
            len(row.products or []),
            "url=",
            row.raw_url,
        )
    saved = collect_and_save_competitor_prices()
    print("saved_rows=", saved)


if __name__ == "__main__":
    main()
