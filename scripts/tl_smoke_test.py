#!/usr/bin/env python3
"""Smoke-тест TravelLine с текущим TL_API_KEY (без сети в pytest)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.data_sources.travelline import TravelLineClient, TravelLineError


def main() -> int:
    reload_config()
    client = TravelLineClient()
    end = date.today()
    start = end

    print("property_id:", client.property_id)
    try:
        numbers = client.search_webpms_booking_numbers(start, end)
        print(f"webpms bookings: {len(numbers)} номеров за {start}..{end}")
        if numbers:
            sample = numbers[0]
            booking = client.get_booking(sample)
            source = booking.get("source")
            print(f"пример {sample}: source={source}")
        reservations = client.get_reservations(start, end, date_kind=2)
        print(f"get_reservations (webpms): {len(reservations)}")
    except TravelLineError as exc:
        print("ошибка:", exc)
        return 1

    for label, fn in [
        ("analytics/services", lambda: client.get_analytics_services(start, end)),
        ("get_revenue", lambda: client.get_revenue(start, end)),
    ]:
        try:
            result = fn()
            print(f"{label}: OK ({result})")
        except TravelLineError as exc:
            print(f"{label}: недоступно ({exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
