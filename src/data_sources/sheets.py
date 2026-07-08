"""Чтение данных из Google Sheets (gspread + сервисный аккаунт)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from pydantic import BaseModel, Field

from src.config import AppConfig, EnvSettings, get_config, get_env_settings
from src.storage.db import save_error_log
from src.storage.models import ErrorLogRecord

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y")


class RoomStatus(str, Enum):
    """Статус номера/квартиры."""

    FREE = "free"
    OCCUPIED = "occupied"
    BOOKED = "booked"
    UNKNOWN = "unknown"


_STATUS_ALIASES: dict[str, RoomStatus] = {
    "свободен": RoomStatus.FREE,
    "свободна": RoomStatus.FREE,
    "свободно": RoomStatus.FREE,
    "free": RoomStatus.FREE,
    "занят": RoomStatus.OCCUPIED,
    "занята": RoomStatus.OCCUPIED,
    "занято": RoomStatus.OCCUPIED,
    "occupied": RoomStatus.OCCUPIED,
    "забронирован": RoomStatus.BOOKED,
    "забронирована": RoomStatus.BOOKED,
    "забронировано": RoomStatus.BOOKED,
    "booked": RoomStatus.BOOKED,
}


class RoomTypeOccupancy(BaseModel):
    """Загрузка по типу квартиры."""

    room_type: str
    occupancy_pct: float | None = None
    total_rooms: int | None = None
    free_count: int | None = None
    occupied_count: int | None = None
    booked_count: int | None = None


class RoomUnit(BaseModel):
    """Статус отдельного номера."""

    room_id: str
    room_type: str
    status: RoomStatus = RoomStatus.UNKNOWN


class OccupancySheetData(BaseModel):
    """Данные листа «Заселяемость»."""

    room_types: list[RoomTypeOccupancy] = Field(default_factory=list)
    units: list[RoomUnit] = Field(default_factory=list)
    is_available: bool = True
    errors: list[str] = Field(default_factory=list)


class BookingRecord(BaseModel):
    """Запись о бронированиях за день по источнику."""

    report_date: date
    source: str
    bookings_count: int


class BookingsSheetData(BaseModel):
    """Данные листа «Брони статистика»."""

    records: list[BookingRecord] = Field(default_factory=list)
    is_available: bool = True
    errors: list[str] = Field(default_factory=list)


class SheetsReadError(Exception):
    """Ошибка чтения Google Sheets."""


class GSpreadClient(Protocol):
    def open_by_key(self, key: str) -> Any: ...

    def open(self, title: str) -> Any: ...


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _parse_int(value: str) -> int | None:
    text = value.strip().replace("\xa0", "").replace(" ", "")
    if not text or text in {"-", "—", "н/д", "n/a"}:
        return None
    try:
        return int(float(text.replace(",", ".")))
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    text = value.strip().replace("\xa0", "").replace(" ", "").replace("%", "")
    if not text or text in {"-", "—", "н/д", "n/a"}:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_status(value: str) -> RoomStatus:
    key = value.strip().lower()
    return _STATUS_ALIASES.get(key, RoomStatus.UNKNOWN)


def _row_has_keywords(row: list[str], keywords: tuple[str, ...]) -> bool:
    joined = _normalize_header(" ".join(cell for cell in row if cell))
    return all(kw in joined for kw in keywords)


def _find_header_row(rows: list[list[str]], keywords: tuple[str, ...]) -> int | None:
    for idx, row in enumerate(rows):
        if row and _row_has_keywords(row, keywords):
            return idx
    return None


def _column_index(headers: list[str], *candidates: str) -> int | None:
    normalized = [_normalize_header(h) for h in headers]
    for candidate in candidates:
        cand = candidate.lower()
        for idx, header in enumerate(normalized):
            if cand in header:
                return idx
    return None


def _cell_int(row: list[str], col: int | None) -> int | None:
    if col is None or col >= len(row):
        return None
    return _parse_int(row[col])


def _cell_float(row: list[str], col: int | None) -> float | None:
    if col is None or col >= len(row):
        return None
    return _parse_float(row[col])


def parse_occupancy_rows(rows: list[list[str]]) -> OccupancySheetData:
    """Распарсить сырые строки листа «Заселяемость»."""
    room_types: list[RoomTypeOccupancy] = []
    units: list[RoomUnit] = []

    type_header_idx = _find_header_row(rows, ("загрузка",))
    if type_header_idx is None:
        type_header_idx = _find_header_row(rows, ("тип", "%"))
    if type_header_idx is not None:
        headers = rows[type_header_idx]
        type_col = _column_index(headers, "тип", "категория", "тип квартиры") or 0
        pct_col = _column_index(headers, "загрузка", "%")
        total_col = _column_index(headers, "всего")
        free_col = _column_index(headers, "свобод")
        occupied_col = _column_index(headers, "занят")
        booked_col = _column_index(headers, "заброн")

        for row in rows[type_header_idx + 1 :]:
            if not any(cell.strip() for cell in row):
                continue
            if _row_has_keywords(row, ("номер",)) or _row_has_keywords(row, ("статус",)):
                break
            room_type = row[type_col].strip() if type_col < len(row) else ""
            if not room_type or _normalize_header(room_type) in {"тип квартиры", "итого"}:
                continue
            room_types.append(
                RoomTypeOccupancy(
                    room_type=room_type,
                    occupancy_pct=_cell_float(row, pct_col),
                    total_rooms=_cell_int(row, total_col),
                    free_count=_cell_int(row, free_col),
                    occupied_count=_cell_int(row, occupied_col),
                    booked_count=_cell_int(row, booked_col),
                )
            )

    unit_header_idx = _find_header_row(rows, ("номер", "статус"))
    if unit_header_idx is not None:
        headers = rows[unit_header_idx]
        room_col = _column_index(headers, "номер", "квартира", "№") or 0
        type_col = _column_index(headers, "тип", "категория")
        status_col = _column_index(headers, "статус")

        for row in rows[unit_header_idx + 1 :]:
            if not any(cell.strip() for cell in row):
                continue
            room_id = row[room_col].strip() if room_col < len(row) else ""
            if not room_id:
                continue
            room_type = (
                row[type_col].strip()
                if type_col is not None and type_col < len(row)
                else ""
            )
            status_raw = (
                row[status_col].strip()
                if status_col is not None and status_col < len(row)
                else ""
            )
            units.append(
                RoomUnit(
                    room_id=room_id,
                    room_type=room_type,
                    status=_parse_status(status_raw) if status_raw else RoomStatus.UNKNOWN,
                )
            )

    return OccupancySheetData(room_types=room_types, units=units)


def parse_bookings_rows(rows: list[list[str]]) -> BookingsSheetData:
    """Распарсить сырые строки листа «Брони статистика»."""
    if not rows:
        return BookingsSheetData()

    header_idx = 0
    headers = rows[header_idx]
    source_col = _column_index(headers, "источник", "канал")
    count_col = _column_index(headers, "кол", "брон", "шт")
    date_col = _column_index(headers, "дата") or 0

    records: list[BookingRecord] = []

    if source_col is not None and count_col is not None:
        for row in rows[header_idx + 1 :]:
            if not any(cell.strip() for cell in row):
                continue
            report_date = _parse_date(row[date_col]) if date_col < len(row) else None
            source = row[source_col].strip() if source_col < len(row) else ""
            count = _parse_int(row[count_col]) if count_col < len(row) else None
            if report_date is None or not source or count is None:
                logger.debug("Пропуск строки броней (long): %s", row)
                continue
            records.append(
                BookingRecord(
                    report_date=report_date,
                    source=source,
                    bookings_count=count,
                )
            )
        return BookingsSheetData(records=records)

    source_columns: list[tuple[int, str]] = []
    for idx, header in enumerate(headers):
        if idx == date_col:
            continue
        name = header.strip()
        if name:
            source_columns.append((idx, name))

    for row in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        report_date = _parse_date(row[date_col]) if date_col < len(row) else None
        if report_date is None:
            logger.debug("Пропуск строки броней (pivot): нет даты %s", row)
            continue
        for col_idx, source in source_columns:
            if col_idx >= len(row):
                continue
            count = _parse_int(row[col_idx])
            if count is None or count == 0:
                continue
            records.append(
                BookingRecord(
                    report_date=report_date,
                    source=source,
                    bookings_count=count,
                )
            )

    return BookingsSheetData(records=records)


class GoogleSheetsClient:
    """Клиент Google Sheets для листов «Заселяемость» и «Брони статистика»."""

    def __init__(
        self,
        config: AppConfig | None = None,
        env: EnvSettings | None = None,
        client: GSpreadClient | None = None,
    ) -> None:
        self.config = config or get_config()
        self._env = env or get_env_settings()
        self._client_override = client
        self._client: GSpreadClient | None = None

    def _get_client(self) -> GSpreadClient:
        if self._client_override is not None:
            return self._client_override
        if self._client is not None:
            return self._client

        sa_path = self._env.google_sa_json_path.strip()
        if not sa_path:
            raise SheetsReadError("GOOGLE_SA_JSON_PATH не задан в .env")

        credentials = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
        self._client = gspread.authorize(credentials)
        return self._client

    def _open_spreadsheet(self) -> Any:
        client = self._get_client()
        sheets_cfg = self.config.sheets
        try:
            if sheets_cfg.spreadsheet_id:
                return client.open_by_key(sheets_cfg.spreadsheet_id)
            return client.open(sheets_cfg.spreadsheet_title)
        except SpreadsheetNotFound as exc:
            logger.error("Таблица не найдена: %s", sheets_cfg.spreadsheet_title)
            raise SheetsReadError("Таблица Google Sheets не найдена") from exc
        except APIError as exc:
            logger.error("Ошибка доступа к Google Sheets: %s", exc)
            raise SheetsReadError("Нет доступа к Google Sheets") from exc

    def _get_worksheet(self, gid: int, title: str) -> Any:
        spreadsheet = self._open_spreadsheet()
        try:
            worksheet = spreadsheet.get_worksheet_by_id(gid)
            if worksheet is not None:
                return worksheet
        except WorksheetNotFound:
            logger.warning("Лист gid=%s не найден, пробуем по имени «%s»", gid, title)

        try:
            return spreadsheet.worksheet(title)
        except WorksheetNotFound as exc:
            logger.error("Лист «%s» (gid=%s) не найден", title, gid)
            raise SheetsReadError(f"Лист «{title}» не найден") from exc

    def _fetch_rows(self, gid: int, title: str) -> list[list[str]]:
        worksheet = self._get_worksheet(gid, title)
        try:
            values = worksheet.get_all_values()
        except APIError as exc:
            logger.error("Ошибка чтения листа «%s»: %s", title, exc)
            raise SheetsReadError(f"Не удалось прочитать лист «{title}»") from exc
        return values or []

    def read_occupancy(self) -> OccupancySheetData:
        """Прочитать лист «Заселяемость»."""
        sheets_cfg = self.config.sheets
        try:
            rows = self._fetch_rows(
                sheets_cfg.occupancy_sheet_gid,
                sheets_cfg.occupancy_sheet,
            )
            data = parse_occupancy_rows(rows)
            logger.info(
                "Заселяемость: %s типов, %s номеров",
                len(data.room_types),
                len(data.units),
            )
            return data
        except SheetsReadError as exc:
            save_error_log(
                ErrorLogRecord(
                    error_date=date.today(),
                    source="sheets",
                    error_type="read_occupancy",
                    message=str(exc),
                )
            )
            return OccupancySheetData(is_available=False, errors=[str(exc)])
        except Exception as exc:
            logger.exception("Неожиданная ошибка read_occupancy: %s", exc)
            save_error_log(
                ErrorLogRecord(
                    error_date=date.today(),
                    source="sheets",
                    error_type="read_occupancy",
                    message=str(exc),
                )
            )
            return OccupancySheetData(
                is_available=False,
                errors=[f"Неожиданная ошибка Google Sheets: {exc}"],
            )

    def read_bookings_stats(self) -> BookingsSheetData:
        """Прочитать лист «Брони статистика»."""
        sheets_cfg = self.config.sheets
        try:
            rows = self._fetch_rows(
                sheets_cfg.bookings_sheet_gid,
                sheets_cfg.bookings_sheet,
            )
            data = parse_bookings_rows(rows)
            logger.info("Брони статистика: %s записей", len(data.records))
            return data
        except SheetsReadError as exc:
            save_error_log(
                ErrorLogRecord(
                    error_date=date.today(),
                    source="sheets",
                    error_type="read_bookings",
                    message=str(exc),
                )
            )
            return BookingsSheetData(is_available=False, errors=[str(exc)])
        except Exception as exc:
            logger.exception("Неожиданная ошибка read_bookings_stats: %s", exc)
            save_error_log(
                ErrorLogRecord(
                    error_date=date.today(),
                    source="sheets",
                    error_type="read_bookings",
                    message=str(exc),
                )
            )
            return BookingsSheetData(
                is_available=False,
                errors=[f"Неожиданная ошибка Google Sheets: {exc}"],
            )
