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
            MagicMock(booking_number="20260714-8134-A", raw={}),
            MagicMock(booking_number="20260714-8134-B", raw={}),
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
        return_value=[MagicMock(booking_number="20260714-8134-1", raw={})]
    )
    client.get_booking = MagicMock(return_value={"status": "Cancelled", "roomStays": []})
    result = client.get_stay_occupancy(date(2026, 7, 14))
    assert result.sold == 0
    assert result.occupancy_pct == 0.0


def test_get_stay_occupancy_from_reservation_id_rows() -> None:
    """WebPMS analytics без bookingNumber — разбивка по roomTypeId."""
    from src.config import TravelLineConfig
    from src.data_sources.travelline import AnalyticsServiceItem

    client = TravelLineClient(
        AppConfig(
            property=PropertyConfig(total_units=44),
            travelline=TravelLineConfig(
                room_type_id_map={
                    "53590": "Однокомнатные квартиры 23 м²",
                    "61691": "Однокомнатные квартиры 27 м²",
                }
            ),
        )
    )
    client.get_analytics_services = MagicMock(
        return_value=[
            AnalyticsServiceItem(
                booking_number=None,
                raw={"kind": 0, "name": "Проживание", "reservationId": 111, "quantity": 1},
            ),
            AnalyticsServiceItem(
                booking_number=None,
                raw={"kind": 0, "name": "Проживание", "reservationId": 222, "quantity": 1},
            ),
            AnalyticsServiceItem(
                booking_number=None,
                raw={"kind": 1, "name": "Завтрак", "reservationId": 111, "quantity": 1},
            ),
        ]
    )
    client.get_rooms = MagicMock(
        return_value=[
            *[{"roomTypeId": "53590"} for _ in range(17)],
            *[{"roomTypeId": "61691"} for _ in range(8)],
        ]
    )
    client._match_stays_by_type = MagicMock(
        return_value=(
            {"Однокомнатные квартиры 23 м²": 1, "Однокомнатные квартиры 27 м²": 1},
            {},
            {111, 222},
        )
    )
    result = client.get_stay_occupancy(date(2026, 7, 16))
    assert result.sold == 2
    assert result.by_type["Однокомнатные квартиры 23 м²"] == 1
    assert result.by_type["Однокомнатные квартиры 27 м²"] == 1
    assert result.free_by_type["Однокомнатные квартиры 23 м²"] == 16
    assert result.free_by_type["Однокомнатные квартиры 27 м²"] == 7
