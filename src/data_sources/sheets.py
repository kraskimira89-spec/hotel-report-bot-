"""Чтение данных из Google Sheets (gspread + сервисный аккаунт)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
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
    """Загрузка по типу квартиры (суточные данные)."""

    room_type: str
    units: int | None = None
    occupancy_pct: float | None = None
    # Для совместимости с более ранними версиями логики (некоторые этапы
    # передавали вместо `units/occupancy_pct` явные статусы).
    free_count: int | None = None
    occupied_count: int | None = None
    booked_count: int | None = None


class RoomUnit(BaseModel):
    """Статус отдельного номера."""

    room_id: str
    room_type: str
    status: RoomStatus = RoomStatus.UNKNOWN


class OccupancySheetData(BaseModel):
    """Данные листа «Заселяемость» (полный лист)."""

    room_types: list[RoomTypeOccupancy] = Field(default_factory=list)
    units: list[RoomUnit] = Field(default_factory=list)
    is_available: bool = True
    errors: list[str] = Field(default_factory=list)


class OccupancyDay(BaseModel):
    """Суточная заселяемость на дату."""

    date: date
    by_type: list[RoomTypeOccupancy] = Field(default_factory=list)
    total_pct: float | None = None
    travelline_pct: float | None = None


class BookingRecord(BaseModel):
    """Запись о бронированиях за день по источнику."""

    report_date: date
    source: str
    bookings_count: int


class BookingSourceDay(BaseModel):
    """Брони по источникам за день."""

    source: str
    count: int


class BookingsSheetData(BaseModel):
    """Данные листа «Брони статистика»."""

    records: list[BookingRecord] = Field(default_factory=list)
    is_available: bool = True
    errors: list[str] = Field(default_factory=list)


class BookingsMonth(BaseModel):
    """Брони по источникам за месяц."""

    year: int
    month: int
    by_source: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class SheetsReadError(Exception):
    """Ошибка чтения Google Sheets."""


def occupancy_day_to_sheet_data(day: OccupancyDay) -> OccupancySheetData:
    """Суточный блок → формат для aggregate_room_status."""
    room_types: list[RoomTypeOccupancy] = []
    for row in day.by_type:
        occupied = int(row.occupancy_pct or 0)
        units = row.units or 0
        room_types.append(
            RoomTypeOccupancy(
                room_type=row.room_type,
                units=units,
                free_count=max(units - occupied, 0),
                occupied_count=occupied,
                booked_count=0,
            )
        )
    return OccupancySheetData(room_types=room_types)


def bookings_records_for_month(
    rows: list[list[str]],
    year: int,
    month: int,
) -> list[BookingRecord]:
    """Собрать дневные записи броней за месяц из сырых строк листа."""
    import calendar

    _, month_days = calendar.monthrange(year, month)
    records: list[BookingRecord] = []
    for day in range(1, month_days + 1):
        target = date(year, month, day)
        for item in parse_bookings_day_rows(rows, target):
            if item.count > 0:
                records.append(
                    BookingRecord(
                        report_date=target,
                        source=item.source,
                        bookings_count=item.count,
                    )
                )
    return records


class GSpreadClient(Protocol):
    def open_by_key(self, key: str) -> Any: ...

    def open(self, title: str) -> Any: ...


def _normalize_header(value: str) -> str:
    cleaned = value.replace("\ufeff", "").strip().lower()
    return re.sub(r"\s+", " ", cleaned)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


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


_MONTHS_RU = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}


def _is_month_marker(row: list[str]) -> bool:
    for cell in row:
        if _normalize_header(cell) in _MONTHS_RU:
            return True
    return False


def _find_month_row(rows: list[list[str]], month: int) -> int | None:
    month_name = next(
        (name for name, value in _MONTHS_RU.items() if value == month), None
    )
    if not month_name:
        return None
    best_idx: int | None = None
    best_non_empty = 10**9
    for idx, row in enumerate(rows):
        match = False
        for cell in row:
            normalized = _normalize_header(cell)
            if not normalized:
                continue
            if normalized == month_name or month_name in normalized:
                match = True
                break
        if not match:
            continue
        non_empty = sum(1 for cell in row if _normalize_header(cell))
        if non_empty < best_non_empty:
            best_non_empty = non_empty
            best_idx = idx
            if best_non_empty <= 2:
                break
    return best_idx


def _day_column(headers: list[str], day: int) -> int | None:
    target = str(day)
    for idx, cell in enumerate(headers):
        if cell.strip() == target:
            return idx
    return None


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
                    units=_cell_int(row, total_col),
                )
            )

    unit_header_idx = _find_header_row(rows, ("номер", "статус"))
    if unit_header_idx is not None:
        headers = rows[unit_header_idx]
        room_col = _column_index(headers, "номер", "квартира", "№") or 0
        unit_type_col = _column_index(headers, "тип", "категория")
        status_col = _column_index(headers, "статус")

        for row in rows[unit_header_idx + 1 :]:
            if not any(cell.strip() for cell in row):
                continue
            room_id = row[room_col].strip() if room_col < len(row) else ""
            if not room_id:
                continue
            room_type = (
                row[unit_type_col].strip()
                if unit_type_col is not None and unit_type_col < len(row)
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


def parse_occupancy_daily_rows(
    rows: list[list[str]],
    target_date: date,
) -> OccupancyDay:
    """Считать суточную заселяемость по маркерам месяца и дня."""
    month_idx = _find_month_row(rows, target_date.month)
    if month_idx is None:
        logger.warning("Заселяемость: не найден блок месяца %s", target_date.month)
        return OccupancyDay(date=target_date)

    header_idx = None
    for idx in range(month_idx + 1, len(rows)):
        if _row_has_keywords(rows[idx], ("тип", "квартир")):
            header_idx = idx
            break
        if _is_month_marker(rows[idx]):
            break

    if header_idx is None:
        logger.warning("Заселяемость: не найден заголовок дней для %s", target_date)
        return OccupancyDay(date=target_date)

    headers = rows[header_idx]
    day_col = _day_column(headers, target_date.day)
    units_col = _column_index(headers, "кол-во квартир", "кол-во") or 1
    if day_col is None:
        logger.warning("Заселяемость: нет колонки дня %s", target_date.day)
        return OccupancyDay(date=target_date)

    by_type: list[RoomTypeOccupancy] = []
    total_pct: float | None = None
    travelline_pct: float | None = None

    for row in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in row):
            break
        if _is_month_marker(row):
            break

        label_raw = row[0] if row else ""
        label_norm = _normalize_header(label_raw)
        if "traveline" in label_norm or "travelline" in label_norm:
            travelline_pct = _cell_float(row, day_col)
            continue
        if (
            "за день" in label_norm
            or "общее кол-во" in label_norm
            or "общее количество" in label_norm
        ):
            total_pct = _cell_float(row, day_col)
            continue

        room_type = _normalize_name(label_raw)
        if not room_type:
            continue
        by_type.append(
            RoomTypeOccupancy(
                room_type=room_type,
                units=_cell_int(row, units_col),
                occupancy_pct=_cell_float(row, day_col),
            )
        )

    return OccupancyDay(
        date=target_date,
        by_type=by_type,
        total_pct=total_pct,
        travelline_pct=travelline_pct,
    )


def _row_has_day_numbers(row: list[str]) -> bool:
    return any(cell.strip().isdigit() for cell in row if cell.strip())


def parse_bookings_day_rows(
    rows: list[list[str]],
    target_date: date,
) -> list[BookingSourceDay]:
    """Считать брони по источникам за день из месячного блока."""
    month_idx = _find_month_row(rows, target_date.month)
    if month_idx is None:
        logger.warning("Брони: не найден блок месяца %s", target_date.month)
        return []

    header_idx = None
    for idx in range(month_idx + 1, len(rows)):
        if _row_has_keywords(rows[idx], ("источник", "брони")):
            header_idx = idx
            break
        if _is_month_marker(rows[idx]):
            break

    if header_idx is None:
        logger.warning("Брони: не найден заголовок источников для %s", target_date)
        return []

    headers = rows[header_idx]
    source_col = _column_index(headers, "источник бронирования", "источник") or 1
    day_col = _day_column(headers, target_date.day)
    if day_col is None:
        logger.warning("Брони: нет колонки дня %s", target_date.day)
        return []

    start_idx = header_idx + 1
    if start_idx < len(rows) and not _row_has_day_numbers(rows[start_idx]):
        start_idx += 1

    results: list[BookingSourceDay] = []
    for row in rows[start_idx:]:
        if not any(cell.strip() for cell in row):
            continue
        source_raw = row[source_col] if source_col < len(row) else ""
        if _normalize_header(source_raw).startswith("итого"):
            break
        source = _normalize_name(source_raw)
        if not source:
            continue
        count = _cell_int(row, day_col)
        if count is None or count == 0:
            continue
        results.append(BookingSourceDay(source=source, count=count))

    return results


def parse_bookings_month_rows(
    rows: list[list[str]],
    year: int,
    month: int,
) -> BookingsMonth:
    """Считать итоги за месяц по источникам."""
    month_idx = _find_month_row(rows, month)
    if month_idx is None:
        logger.warning("Брони: не найден блок месяца %s", month)
        return BookingsMonth(year=year, month=month)

    header_idx = None
    for idx in range(month_idx + 1, len(rows)):
        if _row_has_keywords(rows[idx], ("источник", "брони")):
            header_idx = idx
            break
        if _is_month_marker(rows[idx]):
            break

    if header_idx is None:
        logger.warning("Брони: не найден заголовок источников для %s-%s", year, month)
        return BookingsMonth(year=year, month=month)

    headers = rows[header_idx]
    source_col = _column_index(headers, "источник бронирования", "источник") or 1
    total_col = _column_index(headers, "всего")
    if total_col is None:
        logger.warning("Брони: нет колонки ВСЕГО для %s-%s", year, month)
        return BookingsMonth(year=year, month=month)

    start_idx = header_idx + 1
    if start_idx < len(rows) and not _row_has_day_numbers(rows[start_idx]):
        start_idx += 1

    by_source: dict[str, int] = {}
    total = 0
    for row in rows[start_idx:]:
        if not any(cell.strip() for cell in row):
            continue
        source_raw = row[source_col] if source_col < len(row) else ""
        source_norm = _normalize_header(source_raw)
        if source_norm.startswith("итого"):
            total_val = _cell_int(row, total_col)
            total = total_val or total
            break
        source = _normalize_name(source_raw)
        if not source:
            continue
        count = _cell_int(row, total_col)
        if count is None or count == 0:
            continue
        by_source[source] = count

    if total == 0 and by_source:
        total = sum(by_source.values())

    return BookingsMonth(year=year, month=month, by_source=by_source, total=total)


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

    def read_bookings_stats(
        self,
        reference_date: date | None = None,
    ) -> BookingsSheetData:
        """Прочитать лист «Брони статистика» (помесячные блоки по маркерам)."""
        sheets_cfg = self.config.sheets
        ref = reference_date or date.today()
        try:
            rows = self._fetch_rows(
                sheets_cfg.bookings_sheet_gid,
                sheets_cfg.bookings_sheet,
            )
            records = bookings_records_for_month(rows, ref.year, ref.month)
            logger.info(
                "Брони статистика: %s записей за %s-%02d",
                len(records),
                ref.year,
                ref.month,
            )
            return BookingsSheetData(records=records)
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

    def read_occupancy_daily(self, target_date: date) -> OccupancyDay:
        """Суточная заселяемость на дату (блок месяца 2026)."""
        sheets_cfg = self.config.sheets
        try:
            rows = self._fetch_rows(
                sheets_cfg.occupancy_sheet_gid,
                sheets_cfg.occupancy_sheet,
            )
            return parse_occupancy_daily_rows(rows, target_date)
        except SheetsReadError as exc:
            logger.warning("read_occupancy_daily: %s", exc)
            return OccupancyDay(date=target_date)

    def read_occupancy_range(self, start: date, end: date) -> list[OccupancyDay]:
        """Заселяемость по дням [start..end] — один запрос к листу."""
        if end < start:
            return []
        sheets_cfg = self.config.sheets
        try:
            rows = self._fetch_rows(
                sheets_cfg.occupancy_sheet_gid,
                sheets_cfg.occupancy_sheet,
            )
        except SheetsReadError as exc:
            logger.warning("read_occupancy_range: %s", exc)
            return []
        days: list[OccupancyDay] = []
        cursor = start
        while cursor <= end:
            days.append(parse_occupancy_daily_rows(rows, cursor))
            cursor += timedelta(days=1)
        return days

    def read_bookings_for_date(self, target_date: date) -> list[BookingSourceDay]:
        """Брони по источникам за день."""
        sheets_cfg = self.config.sheets
        try:
            rows = self._fetch_rows(
                sheets_cfg.bookings_sheet_gid,
                sheets_cfg.bookings_sheet,
            )
            return parse_bookings_day_rows(rows, target_date)
        except SheetsReadError as exc:
            logger.warning("read_bookings_for_date: %s", exc)
            return []

    def read_bookings_records_range(
        self,
        start: date,
        end: date,
    ) -> list[BookingRecord]:
        """Дневные записи броней за период (по месячным блокам листа)."""
        if end < start:
            return []
        sheets_cfg = self.config.sheets
        try:
            rows = self._fetch_rows(
                sheets_cfg.bookings_sheet_gid,
                sheets_cfg.bookings_sheet,
            )
        except SheetsReadError as exc:
            logger.warning("read_bookings_records_range: %s", exc)
            return []

        months: set[tuple[int, int]] = set()
        cursor = start
        while cursor <= end:
            months.add((cursor.year, cursor.month))
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)

        records: list[BookingRecord] = []
        for year, month in sorted(months):
            for rec in bookings_records_for_month(rows, year, month):
                if start <= rec.report_date <= end:
                    records.append(rec)
        return records

    def read_bookings_month(self, year: int, month: int) -> BookingsMonth:
        """Брони по источникам за месяц."""
        sheets_cfg = self.config.sheets
        try:
            rows = self._fetch_rows(
                sheets_cfg.bookings_sheet_gid,
                sheets_cfg.bookings_sheet,
            )
            return parse_bookings_month_rows(rows, year, month)
        except SheetsReadError as exc:
            logger.warning("read_bookings_month: %s", exc)
            return BookingsMonth(year=year, month=month)
