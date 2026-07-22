#!/usr/bin/env python3
"""Экспорт данных и PNG для презентации 1apart."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.web import queries


def main() -> int:
    out: dict = {"forecast_30": None, "forecast_7": None, "events": None}
    for h in (7, 30):
        bundle = queries.fetch_forecast_bundle(horizon_days=h, scenario="base")
        key = f"forecast_{h}"
        out[key] = {
            "horizon_days": bundle.get("horizon_days"),
            "series": bundle.get("series", [])[:h],
            "kpi": bundle.get("kpi"),
        }
    events = queries.fetch_events_bundle()
    out["events"] = {
        "rows": events.get("rows", [])[:8],
        "stats": events.get("stats"),
    }
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
