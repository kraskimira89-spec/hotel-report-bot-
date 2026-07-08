"""Тесты Google Sheets (моки gspread, без сети)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

from src.config import AppConfig, EnvSettings, SheetsConfig
from src.data_sources.sheets import (
    BookingRecord,
    BookingsSheetData,
    GoogleSheetsClient,
    OccupancySheetData,
    RoomStatus,
    RoomTypeOccupancy,
    RoomUnit,
    SheetsReadError,
    parse_bookings_rows,
    parse_occupancy_rows,
)

OCCUPANCY_ROWS = [
    ["Тип квартиры", "Загрузка %", "Всего", "Свободно", "Занято", "Забронировано"],
    ["Студия", "75", "8", "2", "5", "1"],
    ["Комфорт", "60%", "10", "4", "5", "1"],
    ["Бизнес", "50", "8", "4", "3", "1"],
    ["Премиум", "80", "6", "1", "4", "1"],
    ["Люкс", "40", "6", "3", "2", "1"],
    ["Пентхаус", "100", "6", "0", "5", "1"],
    [],
    ["Номер", "Тип", "Статус"],
    ["101", "Студия", "занят"],
    ["102", "Студия", "свободен"],
    ["201", "Комфорт", "забронирован"],
    ["", "", ""],
]

BOOKINGS_PIVOT_ROWS = [
    ["Дата", "1apart.ru", "Островок", "Звонок"],
    ["01.07.2026", "2", "1", "0"],
    ["02.07.2026", "1", "", "3"],
    ["03.07.2026", "-", "2", "1"],
]

BOOKINGS_LONG_ROWS = [
    ["Дата", "Источник", "Кол-во броней"],
    ["2026-07-01", "1apart.ru", "2"],
    ["2026-07-01", "Островок", "1"],
    ["2026-07-02", "Авито", "3"],
]


def test_parse_occupancy_room_types() -> None:
    data = parse_occupancy_rows(OCCUPANCY_ROWS)
    assert len(data.room_types) == 6
    assert data.room_types[0] == RoomTypeOccupancy(
        room_type="Студия",
        occupancy_pct=75.0,
        total_rooms=8,
        free_count=2,
        occupied_count=5,
        booked_count=1,
    )
    assert data.room_types[1].occupancy_pct == 60.0


def test_parse_occupancy_units() -> None:
    data = parse_occupancy_rows(OCCUPANCY_ROWS)
    assert len(data.units) == 3
    assert data.units[0] == RoomUnit(
        room_id="101", room_type="Студия", status=RoomStatus.OCCUPIED
    )
    assert data.units[1].status == RoomStatus.FREE
    assert data.units[2].status == RoomStatus.BOOKED


def test_parse_occupancy_empty() -> None:
    data = parse_occupancy_rows([])
    assert data == OccupancySheetData()


def test_parse_bookings_pivot() -> None:
    data = parse_bookings_rows(BOOKINGS_PIVOT_ROWS)
    assert len(data.records) == 6  # нулевые ячейки пропускаются
    first = data.records[0]
    assert first == BookingRecord(
        report_date=date(2026, 7, 1),
        source="1apart.ru",
        bookings_count=2,
    )
    ostrovok = [r for r in data.records if r.source == "Островок" and r.report_date.day == 3]
    assert len(ostrovok) == 1
    assert ostrovok[0].bookings_count == 2


def test_parse_bookings_long_format() -> None:
    data = parse_bookings_rows(BOOKINGS_LONG_ROWS)
    assert len(data.records) == 3
    assert data.records[2].source == "Авито"
    assert data.records[2].bookings_count == 3


def test_parse_bookings_empty() -> None:
    assert parse_bookings_rows([]) == BookingsSheetData()


def _make_client(
    occupancy_rows: list[list[str]] | None = None,
    bookings_rows: list[list[str]] | None = None,
    *,
    spreadsheet_error: Exception | None = None,
    worksheet_error: Exception | None = None,
    api_error_on_read: bool = False,
) -> GoogleSheetsClient:
    config = AppConfig(
        sheets=SheetsConfig(
            spreadsheet_id="test-id",
            spreadsheet_title="Апарт отель для Сергея",
        )
    )
    env = EnvSettings(google_sa_json_path="/fake/sa.json")

    mock_gspread = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_gspread.open_by_key.return_value = mock_spreadsheet

    if spreadsheet_error:
        mock_gspread.open_by_key.side_effect = spreadsheet_error

    occupancy_ws = MagicMock()
    bookings_ws = MagicMock()
    occupancy_ws.get_all_values.return_value = occupancy_rows or []
    bookings_ws.get_all_values.return_value = bookings_rows or []

    if api_error_on_read:
        occupancy_ws.get_all_values.side_effect = APIError(MagicMock())

    def worksheet_by_id(gid: int) -> MagicMock:
        if worksheet_error:
            raise worksheet_error
        if gid == config.sheets.occupancy_sheet_gid:
            return occupancy_ws
        if gid == config.sheets.bookings_sheet_gid:
            return bookings_ws
        raise WorksheetNotFound("missing")

    mock_spreadsheet.get_worksheet_by_id.side_effect = worksheet_by_id
    return GoogleSheetsClient(config=config, env=env, client=mock_gspread)


@patch("src.data_sources.sheets.Credentials.from_service_account_file")
def test_read_occupancy_integration_mock(_mock_creds: MagicMock) -> None:
    client = _make_client(occupancy_rows=OCCUPANCY_ROWS)
    data = client.read_occupancy()
    assert len(data.room_types) == 6
    assert len(data.units) == 3


@patch("src.data_sources.sheets.Credentials.from_service_account_file")
def test_read_bookings_integration_mock(_mock_creds: MagicMock) -> None:
    client = _make_client(bookings_rows=BOOKINGS_PIVOT_ROWS)
    data = client.read_bookings_stats()
    assert len(data.records) == 6


def test_read_occupancy_spreadsheet_not_found() -> None:
    client = _make_client(
        occupancy_rows=OCCUPANCY_ROWS,
        spreadsheet_error=SpreadsheetNotFound("nf"),
    )
    data = client.read_occupancy()
    assert data.is_available is False
    assert data.errors


def test_read_bookings_worksheet_not_found() -> None:
    client = _make_client(
        bookings_rows=BOOKINGS_PIVOT_ROWS,
        worksheet_error=WorksheetNotFound("nf"),
    )
    mock_spreadsheet = client._client_override.open_by_key.return_value
    mock_spreadsheet.worksheet.side_effect = WorksheetNotFound("nf")

    data = client.read_bookings_stats()
    assert data.is_available is False
    assert data.errors


def test_read_occupancy_api_error_on_read() -> None:
    client = _make_client(api_error_on_read=True)
    data = client.read_occupancy()
    assert data.is_available is False
    assert data.errors


def test_get_client_without_sa_path() -> None:
    config = AppConfig()
    env = EnvSettings(google_sa_json_path="")
    client = GoogleSheetsClient(config=config, env=env)
    with pytest.raises(SheetsReadError, match="GOOGLE_SA_JSON_PATH"):
        client._get_client()
