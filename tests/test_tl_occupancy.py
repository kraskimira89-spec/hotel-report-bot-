"""Тесты загрузки на ночь из TravelLine."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from src.config import AppConfig, PropertyConfig
from src.data_sources.travelline import StayOccupancyResult, TravelLineClient


def test_get_stay_occupancy_counts_units_by_type() -> None:
    client = TravelLineClient(AppConfig(property=PropertyConfig(total_units=44)))
    client.get_analytics_services = MagicMock(
        return_value=[
            MagicMock(booking_number="A"),
            MagicMock(booking_number="B"),
        ]
    )
    client.get_booking = MagicMock(
        side_effect=[
            {
                "status": "Confirmed",
                "roomStays": [
                    {
                        "arrivalDate": "2026-07-14",
                        "departureDate": "2026-07-16",
                        "roomType": {"name": "1-комн. 23 кв.м."},
                    }
                ],
            },
            {
                "status": "Confirmed",
                "roomStays": [
                    {
                        "arrivalDate": "2026-07-13",
                        "departureDate": "2026-07-15",
                        "roomType": {"name": "Luxe"},
                    }
                ],
            },
        ]
    )
    result = client.get_stay_occupancy(date(2026, 7, 14))
    assert isinstance(result, StayOccupancyResult)
    assert result.sold == 2
    assert result.available == 44
    assert result.occupancy_pct == round(2 / 44 * 100, 2)
    assert result.by_type["1-комн. 23 кв.м."] == 1
    assert result.by_type["Люкс"] == 1


def test_get_stay_occupancy_skips_cancelled() -> None:
    client = TravelLineClient(AppConfig(property=PropertyConfig(total_units=44)))
    client.get_analytics_services = MagicMock(
        return_value=[MagicMock(booking_number="X")]
    )
    client.get_booking = MagicMock(return_value={"status": "Cancelled", "roomStays": []})
    result = client.get_stay_occupancy(date(2026, 7, 14))
    assert result.sold == 0
    assert result.occupancy_pct == 0.0
