"""Тесты Google Sheets (фикстуры без сети)."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

from src.config import AppConfig, EnvSettings, SheetsConfig
from src.data_sources.sheets import (
    BookingsMonth,
    GoogleSheetsClient,
    OccupancyDay,
    SheetsReadError,
    parse_bookings_day_rows,
    parse_bookings_month_rows,
    parse_occupancy_daily_rows,
)


def _load_rows(filename: str) -> list[list[str]]:
    path = Path(__file__).parent / "fixtures" / "sheets" / filename
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return [row for row in reader]


def test_parse_occupancy_daily_from_fixture() -> None:
    rows = _load_rows("zaselyaemost_2026_sample.csv")
    data = parse_occupancy_daily_rows(rows, date(2026, 7, 1))
    assert isinstance(data, OccupancyDay)
    room = next(r for r in data.by_type if r.room_type.startswith("1-комн. 23 кв.м."))
    assert room.occupancy_pct == 5.0
    assert data.total_pct == 24.0
    assert data.travelline_pct == 51.2


def test_parse_bookings_for_day_from_fixture() -> None:
    rows = _load_rows("broni_iyul_sample.csv")
    day_one = parse_bookings_day_rows(rows, date(2026, 7, 1))
    day_one_map = {item.source: item.count for item in day_one}
    assert day_one_map["Сайт"] == 3

    day_two = parse_bookings_day_rows(rows, date(2026, 7, 2))
    day_two_map = {item.source: item.count for item in day_two}
    assert day_two_map["Уже проживали (по звонку)"] == 4


def test_parse_bookings_month_from_fixture() -> None:
    rows = _load_rows("broni_iyul_sample.csv")
    data = parse_bookings_month_rows(rows, 2026, 7)
    assert isinstance(data, BookingsMonth)
    assert data.by_source["Сайт"] == 12
    assert data.by_source["Уже проживали (по звонку)"] == 15
    assert data.by_source["Островок"] == 1
    assert data.total == 38


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
def test_read_occupancy_daily_mock(_mock_creds: MagicMock) -> None:
    rows = _load_rows("zaselyaemost_2026_sample.csv")
    client = _make_client(occupancy_rows=rows)
    data = client.read_occupancy_daily(date(2026, 7, 1))
    assert data.total_pct == 24.0


@patch("src.data_sources.sheets.Credentials.from_service_account_file")
def test_read_bookings_for_date_mock(_mock_creds: MagicMock) -> None:
    rows = _load_rows("broni_iyul_sample.csv")
    client = _make_client(bookings_rows=rows)
    data = client.read_bookings_for_date(date(2026, 7, 1))
    assert any(item.source == "Сайт" and item.count == 3 for item in data)


@patch("src.data_sources.sheets.Credentials.from_service_account_file")
def test_read_bookings_month_mock(_mock_creds: MagicMock) -> None:
    rows = _load_rows("broni_iyul_sample.csv")
    client = _make_client(bookings_rows=rows)
    data = client.read_bookings_month(2026, 7)
    assert data.total == 38


def test_read_occupancy_spreadsheet_not_found() -> None:
    rows = _load_rows("zaselyaemost_2026_sample.csv")
    client = _make_client(occupancy_rows=rows, spreadsheet_error=SpreadsheetNotFound("nf"))
    data = client.read_occupancy_daily(date(2026, 7, 1))
    assert data == OccupancyDay(date=date(2026, 7, 1))


def test_read_bookings_worksheet_not_found() -> None:
    rows = _load_rows("broni_iyul_sample.csv")
    client = _make_client(bookings_rows=rows, worksheet_error=WorksheetNotFound("nf"))
    mock_spreadsheet = client._client_override.open_by_key.return_value
    mock_spreadsheet.worksheet.side_effect = WorksheetNotFound("nf")

    data = client.read_bookings_for_date(date(2026, 7, 1))
    assert data == []


def test_read_occupancy_api_error_on_read() -> None:
    client = _make_client(api_error_on_read=True)
    data = client.read_occupancy_daily(date(2026, 7, 1))
    assert data == OccupancyDay(date=date(2026, 7, 1))


def test_get_client_without_sa_path() -> None:
    config = AppConfig()
    env = EnvSettings(google_sa_json_path="")
    client = GoogleSheetsClient(config=config, env=env)
    with pytest.raises(SheetsReadError, match="GOOGLE_SA_JSON_PATH"):
        client._get_client()
