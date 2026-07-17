"""Клиент TravelLine API: Universal WebPMS + Read Reservation."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field

from src.config import AppConfig, get_config, get_env_settings
from src.data_sources.sheets import BookingsSheetData, GoogleSheetsClient
from src.metrics.guests import classify_channel, hash_guest_identifiers
from src.metrics.revenue import calc_adr, calc_revpar, resolve_revenue
from src.storage.db import save_error_log
from src.storage.models import ErrorLogRecord
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {401, 403, 429, 500, 502, 503, 504}
MSK = ZoneInfo("Europe/Moscow")


class TravelLineError(Exception):
    """Ошибка TravelLine API."""


class DateWindowError(TravelLineError):
    """Превышено максимальное окно дат."""


class HttpClient(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


class AnalyticsServiceItem(BaseModel):
    """Начисление из analytics/services."""

    booking_number: str | None = None
    amount: float = 0.0
    service_date: date | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PaymentItem(BaseModel):
    """Платёж из analytics/payments."""

    booking_number: str | None = None
    amount: float = 0.0
    payment_date: date | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ReservationSummary(BaseModel):
    """Краткая информация о бронировании."""

    number: str
    status: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    source_code: str | None = None
    source_type: str | None = None
    channel_type: str = "unknown"
    raw: dict[str, Any] = Field(default_factory=dict)


class GuestProfile(BaseModel):
    """Профиль гостя из бронирования (без PII в открытом виде)."""

    guest_key: str
    phone_hash: str | None = None
    email_hash: str | None = None
    fio_hash: str | None = None
    is_returning_hint: bool = False
    booking_number: str | None = None


class DynamicPriceDay(BaseModel):
    """Цена на конкретную дату."""

    stay_date: date
    price: float
    room_type_id: str | None = None
    rate_plan_id: str | None = None


class RevenueReport(BaseModel):
    """Фактический доход за период."""

    revenue: float
    is_estimated: bool = False
    services_total: float = 0.0
    payments_total: float = 0.0
    cancelled_total: float = 0.0


class ReconciliationWarning(BaseModel):
    """Предупреждение о расхождении TravelLine vs Sheets."""

    metric: str
    tl_value: float
    sheets_value: float
    diff_pct: float
    message: str


def format_tl_date(value: date) -> str:
    """Дата для Universal WebPMS API: yyyyMMdd."""
    return value.strftime("%Y%m%d")


def parse_tl_date(value: str) -> date | None:
    """Разобрать yyyyMMdd или ISO-дату."""
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def msk_date_to_utc_start(value: date) -> datetime:
    """Начало дня MSK → UTC."""
    local = datetime(value.year, value.month, value.day, tzinfo=MSK)
    return local.astimezone(timezone.utc)


def msk_date_to_utc_end(value: date) -> datetime:
    """Конец дня MSK → UTC."""
    local = datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=MSK)
    return local.astimezone(timezone.utc)


def utc_to_msk_date(value: datetime) -> date:
    """UTC datetime → дата MSK."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MSK).date()


def ensure_date_window(
    start_date: date,
    end_date: date,
    max_days: int = 31,
) -> None:
    """Проверить окно дат (макс. 31 день)."""
    if end_date < start_date:
        raise DateWindowError("end_date раньше start_date")
    if (end_date - start_date).days + 1 > max_days:
        raise DateWindowError(f"Окно дат превышает {max_days} дней")


def split_date_ranges(
    start_date: date,
    end_date: date,
    max_days: int = 31,
) -> list[tuple[date, date]]:
    """Разбить период на окна ≤ max_days."""
    if end_date < start_date:
        raise DateWindowError("end_date раньше start_date")
    ranges: list[tuple[date, date]] = []
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=max_days - 1), end_date)
        ranges.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return ranges


def _parse_amount(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_datetime_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_list(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        items = payload.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_list(data, *keys)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _is_stay_service_row(row: dict[str, Any]) -> bool:
    """Строка «Проживание» в analytics/services (kind=0 или имя)."""
    kind = row.get("kind")
    if kind == 0 or kind == "0":
        return True
    name = str(row.get("name") or "").strip().lower()
    return name in {"проживание", "accommodation", "lodging"}


def _looks_like_booking_number(value: str) -> bool:
    """Номер вида YYYYMMDD-… (не внутренний reservationId)."""
    prefix = value.split("-", 1)[0]
    return prefix.isdigit() and len(prefix) == 8


def _parse_room_stay_dates(stay: dict[str, Any]) -> tuple[date | None, date | None]:
    """Даты заезда/выезда из WebPMS roomStay (checkIn/Out или arrival/departure)."""
    raw_in = (
        stay.get("checkInDateTime")
        or stay.get("arrivalDate")
        or stay.get("startDate")
        or ""
    )
    raw_out = (
        stay.get("checkOutDateTime")
        or stay.get("departureDate")
        or stay.get("endDate")
        or ""
    )

    def _one(raw: Any) -> date | None:
        text = str(raw or "").strip()
        if not text:
            return None
        if "T" in text:
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")[:19]).date()
            except ValueError:
                pass
        return parse_tl_date(text[:8] if len(text) >= 8 and text[:8].isdigit() else text)

    return _one(raw_in), _one(raw_out)


def _room_stay_bucket(stay: dict[str, Any]) -> str:
    """occupied / booked / skip для сводки св/зан/брон."""
    status = str(stay.get("status") or stay.get("bookingStatus") or "").strip().lower()
    if status in {
        "cancelled",
        "canceled",
        "отменена",
        "отменен",
        "noshow",
        "no-show",
        "незаезд",
        "checkedout",
        "checked_out",
    }:
        return "skip"
    if status in {"checkedin", "checked_in", "inhouse", "in-house"}:
        return "occupied"
    if status in {"new", "confirmed", "booked", "reserved"}:
        return "booked"
    # Нет статуса — считаем занятием ночи (как в analytics).
    return "occupied"


def parse_analytics_services(payload: dict[str, Any]) -> list[AnalyticsServiceItem]:
    """Разобрать ответ analytics/services."""
    items: list[AnalyticsServiceItem] = []
    for row in _extract_list(payload, "services", "items", "analyticsServices"):
        amount = _parse_amount(
            row.get("amount")
            or row.get("sum")
            or row.get("revenue")
            or row.get("serviceAmount")
        )
        service_date = parse_tl_date(str(row.get("date") or row.get("serviceDate") or ""))
        booking_number = row.get("bookingNumber") or row.get("number")
        if booking_number is not None:
            booking_number = str(booking_number)
        items.append(
            AnalyticsServiceItem(
                booking_number=booking_number,
                amount=amount,
                service_date=service_date,
                raw=row,
            )
        )
    return items


def parse_analytics_payments(payload: dict[str, Any]) -> list[PaymentItem]:
    """Разобрать ответ analytics/payments."""
    items: list[PaymentItem] = []
    for row in _extract_list(payload, "payments", "items", "analyticsPayments"):
        amount = _parse_amount(
            row.get("amount") or row.get("sum") or row.get("paymentAmount")
        )
        payment_date = parse_tl_date(str(row.get("date") or row.get("paymentDate") or ""))
        items.append(
            PaymentItem(
                booking_number=row.get("bookingNumber") or row.get("number"),
                amount=amount,
                payment_date=payment_date,
                raw=row,
            )
        )
    return items


def parse_reservation_search(
    payload: dict[str, Any],
) -> tuple[list[ReservationSummary], str | None, bool]:
    """Разобрать reservations/search."""
    reservations: list[ReservationSummary] = []
    for row in _extract_list(payload, "reservations", "bookingSummaries", "items"):
        source = row.get("source") or {}
        source_code: str | None
        source_type: str | None
        if isinstance(source, str):
            source_code, source_type = source, None
        else:
            raw_code = source.get("code") or source.get("name")
            source_code = str(raw_code) if raw_code is not None else None
            raw_type = source.get("type")
            source_type = str(raw_type) if raw_type is not None else None
        reservations.append(
            ReservationSummary(
                number=str(row.get("number") or row.get("bookingNumber") or ""),
                status=row.get("status"),
                created_at=_parse_datetime_utc(row.get("createdDateTime")),
                modified_at=_parse_datetime_utc(row.get("modifiedDateTime")),
                source_code=source_code,
                source_type=source_type,
                raw=row,
            )
        )
    next_token = payload.get("nextPageToken") or payload.get("continueToken")
    has_next = bool(payload.get("hasNextPage") or payload.get("hasMoreData"))
    return reservations, next_token, has_next


def parse_booking_details(payload: dict[str, Any]) -> dict[str, Any]:
    """Извлечь booking из детального ответа."""
    booking = payload.get("booking")
    if isinstance(booking, dict):
        return booking
    return payload


def parse_dynamic_prices(payload: dict[str, Any]) -> list[DynamicPriceDay]:
    """Разобрать цены на даты из Search API."""
    prices: list[DynamicPriceDay] = []
    stays = _extract_list(payload, "roomStays", "items")
    for stay in stays:
        room_type_id = None
        room_type = stay.get("roomType")
        if isinstance(room_type, dict):
            room_type_id = room_type.get("id")
        for rate in stay.get("dailyRates") or []:
            if not isinstance(rate, dict):
                continue
            stay_date = parse_tl_date(str(rate.get("date") or ""))
            if stay_date is None:
                continue
            prices.append(
                DynamicPriceDay(
                    stay_date=stay_date,
                    price=_parse_amount(rate.get("priceBeforeTax") or rate.get("price")),
                    room_type_id=room_type_id,
                    rate_plan_id=rate.get("ratePlanId"),
                )
            )
    return prices


class StayOccupancyResult(BaseModel):
    """Загрузка на ночь по TravelLine (dateKind=1 — даты проживания)."""

    stay_date: date
    sold: int = 0
    available: int = 0
    occupancy_pct: float = 0.0
    by_type: dict[str, int] = Field(default_factory=dict)  # label → занято (CheckedIn)
    free_by_type: dict[str, int] = Field(default_factory=dict)
    booked_by_type: dict[str, int] = Field(default_factory=dict)  # label → бронь (New)
    source: str = "travelline"


def calc_reconcile_diff_pct(tl_value: float, sheets_value: float) -> float:
    """Процент расхождения относительно Sheets."""
    if sheets_value == 0:
        return 100.0 if tl_value != 0 else 0.0
    return abs(tl_value - sheets_value) / sheets_value * 100


def booking_date_from_number(booking_number: str) -> date | None:
    """Дата создания из номера брони (YYYYMMDD-propertyId-seq)."""
    prefix = booking_number.split("-", 1)[0]
    if len(prefix) == 8 and prefix.isdigit():
        return parse_tl_date(prefix)
    return None


def parse_webpms_source_label(source: Any) -> str | None:
    """Подпись источника из WebPMS: {key, value} или {code, type}."""
    if not isinstance(source, dict):
        return str(source) if source else None
    return source.get("value") or source.get("code") or source.get("name")


class TravelLineClient:
    """REST-клиент TravelLine (Universal WebPMS + Read Reservation API)."""

    def __init__(
        self,
        config: AppConfig | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self.config = config or get_config()
        self._env = get_env_settings()
        self._http = http_client
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def property_id(self) -> str:
        return self.config.travelline.property_id

    def _client(self) -> HttpClient:
        if self._http is not None:
            return self._http
        return httpx.Client(timeout=30.0)  # type: ignore[return-value]

    def authenticate(self, force: bool = False) -> str:
        """Получить Bearer JWT для Partner API (OAuth client credentials)."""
        if (
            not force
            and self._access_token
            and time.time() < self._token_expires_at - 30
        ):
            return self._access_token

        if self._env.tl_client_id and self._env.tl_client_secret:
            response = self._client().request(
                "POST",
                self.config.travelline.auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._env.tl_client_id,
                    "client_secret": self._env.tl_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()
            token = str(payload.get("access_token", ""))
            expires_in = int(payload.get("expires_in", 900))
            self._access_token = token
            self._token_expires_at = time.time() + expires_in
            return token

        raise TravelLineError(
            "Partner API: задайте TL_CLIENT_ID и TL_CLIENT_SECRET в .env"
        )

    def _has_partner_auth(self) -> bool:
        return bool(self._env.tl_client_id.strip() and self._env.tl_client_secret.strip())

    def _webpms_headers(self) -> dict[str, str]:
        if not self._env.tl_api_key.strip():
            raise TravelLineError("TL_API_KEY не задан")
        return {
            "X-API-KEY": self._env.tl_api_key.strip(),
            "Accept": "application/json",
        }

    def _partner_headers(self) -> dict[str, str]:
        token = self.authenticate()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth_retry: bool = False,
        retry_auth: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """HTTP-запрос с backoff."""
        tl = self.config.travelline

        def _call() -> httpx.Response:
            client = self._client()
            return client.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
            )

        try:
            response = retry_with_backoff(
                _call,
                retries=tl.max_retries,
                backoff_initial=tl.backoff_initial_sec,
                backoff_max=tl.backoff_max_sec,
                retry_statuses=(429, 500, 502, 503, 504),
                log_prefix=f"travelline {method} {url}",
            )
        except httpx.HTTPError as exc:
            save_error_log(
                ErrorLogRecord(
                    error_date=date.today(),
                    source="travelline",
                    error_type="http_error",
                    message=str(exc),
                )
            )
            raise TravelLineError(str(exc)) from exc

        if response.status_code in {401, 403} and auth_retry and retry_auth:
            retry_auth()
            response = retry_with_backoff(
                _call,
                retries=tl.max_retries,
                backoff_initial=tl.backoff_initial_sec,
                backoff_max=tl.backoff_max_sec,
                retry_statuses=(429, 500, 502, 503, 504),
                log_prefix=f"travelline {method} {url}",
            )

        if response.status_code >= 400:
            raise TravelLineError(
                f"HTTP {response.status_code}: {response.text[:300]}"
            )

        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"value": data}

    def _webpms_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._http_request(
            method,
            self._webpms_url(path),
            headers=self._webpms_headers(),
            params=params,
            json=json,
        )

    def _partner_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = self._partner_headers()

        def _retry() -> None:
            self.authenticate(force=True)
            headers.update(self._partner_headers())

        return self._http_request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            auth_retry=True,
            retry_auth=_retry,
        )

    def _webpms_url(self, path: str) -> str:
        base = self.config.travelline.webpms_base_url.rstrip("/")
        return f"{base}/v1/{path.lstrip('/')}"

    def _reservation_url(self, path: str) -> str:
        base = self.config.travelline.reservation_base_url.rstrip("/")
        prop = self.property_id
        if not prop:
            raise TravelLineError("travelline.property_id не задан в settings.yaml")
        return f"{base}/v2/properties/{prop}/{path.lstrip('/')}"

    def _analytics_params(
        self,
        start_date: date,
        end_date: date,
        date_kind: int,
    ) -> dict[str, str | int]:
        ensure_date_window(
            start_date,
            end_date,
            self.config.travelline.max_date_window_days,
        )
        return {
            "startDate": format_tl_date(start_date),
            "endDate": format_tl_date(end_date),
            "dateKind": date_kind,
        }

    def _payments_params(self, start_date: date, end_date: date) -> dict[str, str]:
        return {
            "startDateTime": start_date.strftime("%Y%m%d") + "0000",
            "endDateTime": end_date.strftime("%Y%m%d") + "2359",
        }

    def get_analytics_services(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 1,
    ) -> list[AnalyticsServiceItem]:
        """Начисления/доход (analytics/services)."""
        payload = self._webpms_request(
            "GET",
            "analytics/services",
            params=self._analytics_params(start_date, end_date, date_kind),
        )
        return parse_analytics_services(payload)

    def get_analytics_payments(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 1,
    ) -> list[PaymentItem]:
        """Платежи (analytics/payments)."""
        _ = date_kind
        payload = self._webpms_request(
            "GET",
            "analytics/payments",
            params=self._payments_params(start_date, end_date),
        )
        return parse_analytics_payments(payload)

    def get_analytics_cancelled(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 1,
    ) -> list[AnalyticsServiceItem]:
        """Отменённые начисления (analytics/services/cancelled)."""
        payload = self._webpms_request(
            "GET",
            "analytics/services/cancelled",
            params=self._analytics_params(start_date, end_date, date_kind),
        )
        return parse_analytics_services(payload)

    def get_booking(self, booking_number: str) -> dict[str, Any]:
        """Детали бронирования bookings/{number}."""
        payload = self._webpms_request("GET", f"bookings/{booking_number}")
        return parse_booking_details(payload)

    def search_webpms_booking_numbers(
        self,
        start_date: date,
        end_date: date,
        *,
        state: str = "Active",
    ) -> list[str]:
        """Поиск номеров броней через WebPMS (без Partner OAuth)."""
        params = {
            "modifiedFrom": start_date.strftime("%Y-%m-%d") + "T00:00",
            "modifiedTo": end_date.strftime("%Y-%m-%d") + "T23:59",
            "state": state,
        }
        payload = self._webpms_request("GET", "bookings", params=params)
        numbers = payload.get("bookingNumbers")
        if isinstance(numbers, list):
            return [str(n) for n in numbers]
        return []

    def search_reservations(
        self,
        last_modification_utc: datetime | None = None,
        page_token: str | None = None,
        max_page_size: int | None = None,
    ) -> tuple[list[ReservationSummary], str | None, bool]:
        """Поиск бронирований (reservations/search) с пагинацией."""
        params: dict[str, Any] = {}
        if page_token:
            params["pageToken"] = page_token
        elif last_modification_utc is not None:
            if last_modification_utc.tzinfo is None:
                last_modification_utc = last_modification_utc.replace(tzinfo=timezone.utc)
            params["lastModification"] = (
                last_modification_utc.astimezone(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        params["maxPageSize"] = (
            max_page_size or self.config.travelline.reservation_page_size
        )
        payload = self._partner_request(
            "GET",
            self._reservation_url("reservations/search"),
            params=params,
        )
        return parse_reservation_search(payload)

    def iter_reservations(
        self,
        last_modification_utc: datetime | None = None,
        max_pages: int = 100,
    ) -> list[ReservationSummary]:
        """Получить все брони с пагинацией."""
        all_items: list[ReservationSummary] = []
        token: str | None = None
        for _ in range(max_pages):
            batch, token, has_next = self.search_reservations(
                last_modification_utc=last_modification_utc if token is None else None,
                page_token=token,
            )
            all_items.extend(batch)
            if not has_next or not token:
                break
        return all_items

    def _reservation_from_webpms_booking(
        self,
        booking_number: str,
        booking: dict[str, Any],
    ) -> ReservationSummary:
        source = booking.get("source") or {}
        source_code = parse_webpms_source_label(source)
        created = booking_date_from_number(booking_number)
        created_dt = (
            datetime(
                created.year,
                created.month,
                created.day,
                tzinfo=MSK,
            ).astimezone(timezone.utc)
            if created
            else None
        )
        modified_raw = booking.get("lastModified") or booking.get("modifiedDateTime")
        modified_dt = _parse_datetime_utc(str(modified_raw)) if modified_raw else None
        return ReservationSummary(
            number=booking_number,
            status=booking.get("status"),
            created_at=created_dt,
            modified_at=modified_dt,
            source_code=source_code,
            source_type=source.get("type") if isinstance(source, dict) else None,
            raw=booking,
        )

    def _get_reservations_via_webpms(
        self,
        start_date: date,
        end_date: date,
        *,
        fetch_details: bool = True,
    ) -> list[ReservationSummary]:
        """Новые брони за период через WebPMS (текущий TL_API_KEY)."""
        import calendar

        _, month_days = calendar.monthrange(start_date.year, start_date.month)
        search_start = date(start_date.year, start_date.month, 1)
        search_end = date(start_date.year, start_date.month, month_days)
        numbers = self.search_webpms_booking_numbers(search_start, search_end)
        result: list[ReservationSummary] = []
        for number in numbers:
            booking_date = booking_date_from_number(number)
            if booking_date is None or not (start_date <= booking_date <= end_date):
                continue
            if fetch_details:
                try:
                    booking = self.get_booking(number)
                except TravelLineError:
                    booking = {"number": number}
                result.append(self._reservation_from_webpms_booking(number, booking))
            else:
                created_dt = datetime(
                    booking_date.year,
                    booking_date.month,
                    booking_date.day,
                    tzinfo=MSK,
                ).astimezone(timezone.utc)
                result.append(
                    ReservationSummary(number=number, created_at=created_dt)
                )
        return self._enrich_channels(result) if fetch_details else result

    def get_reservations(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 2,
        *,
        fetch_details: bool = True,
    ) -> list[ReservationSummary]:
        """Новые брони за период.

        date_kind=2 — по дате создания.
        Без OAuth используется WebPMS (TL_API_KEY + X-API-KEY).
        """
        if date_kind == 2 and not self._has_partner_auth():
            return self._get_reservations_via_webpms(
                start_date,
                end_date,
                fetch_details=fetch_details,
            )

        if date_kind == 2:
            try:
                start_utc = msk_date_to_utc_start(start_date)
                reservations = self.iter_reservations(last_modification_utc=start_utc)
                end_utc = msk_date_to_utc_end(end_date)
                filtered: list[ReservationSummary] = []
                for item in reservations:
                    created = item.created_at
                    if created is None:
                        continue
                    if start_utc <= created <= end_utc:
                        filtered.append(item)
                return self._enrich_channels(filtered)
            except TravelLineError as exc:
                # OAuth есть, но Read Reservation недоступен (404 и т.п.) — WebPMS
                if "404" not in str(exc):
                    raise
                logger.warning(
                    "Read Reservation API недоступен (%s), сверка через WebPMS",
                    exc,
                )
                return self._get_reservations_via_webpms(
                    start_date,
                    end_date,
                    fetch_details=fetch_details,
                )

        services = self.get_analytics_services(start_date, end_date, date_kind=date_kind)
        numbers = {s.booking_number for s in services if s.booking_number}
        result: list[ReservationSummary] = []
        for number in sorted(numbers):
            try:
                booking = self.get_booking(number)
            except TravelLineError:
                continue
            source = booking.get("source") or {}
            result.append(
                ReservationSummary(
                    number=number,
                    status=booking.get("status"),
                    created_at=_parse_datetime_utc(booking.get("createdDateTime")),
                    modified_at=_parse_datetime_utc(booking.get("modifiedDateTime")),
                    source_code=parse_webpms_source_label(source),
                    source_type=source.get("type") if isinstance(source, dict) else None,
                    raw=booking,
                )
            )
        return self._enrich_channels(result)

    def _enrich_channels(self, reservations: list[ReservationSummary]) -> list[ReservationSummary]:
        for item in reservations:
            label = item.source_code or item.source_type or ""
            item.channel_type = classify_channel(label, self.config.channels_map)
        return reservations

    def get_revenue(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 1,
    ) -> RevenueReport:
        """Фактический доход: платежи + начисления − отмены."""
        payments_total = 0.0
        services_total = 0.0
        cancelled_total = 0.0

        for chunk_start, chunk_end in split_date_ranges(
            start_date,
            end_date,
            self.config.travelline.max_date_window_days,
        ):
            payments = self.get_analytics_payments(chunk_start, chunk_end, date_kind)
            services = self.get_analytics_services(chunk_start, chunk_end, date_kind)
            cancelled = self.get_analytics_cancelled(chunk_start, chunk_end, date_kind)
            payments_total += sum(p.amount for p in payments)
            services_total += sum(s.amount for s in services)
            cancelled_total += sum(c.amount for c in cancelled)

        revenue = payments_total if payments_total > 0 else services_total
        revenue = max(revenue - cancelled_total, 0.0)
        return RevenueReport(
            revenue=round(revenue, 2),
            is_estimated=False,
            services_total=round(services_total, 2),
            payments_total=round(payments_total, 2),
            cancelled_total=round(cancelled_total, 2),
        )

    def get_revenue_metrics(
        self,
        start_date: date,
        end_date: date,
        sold_unit_nights: int,
        available_unit_nights: int,
        date_kind: int = 1,
    ) -> dict[str, Any]:
        """Факт-доход → ADR/RevPAR."""
        report = self.get_revenue(start_date, end_date, date_kind=date_kind)
        resolved = resolve_revenue(report.revenue, None, sold_unit_nights)
        return {
            "revenue": resolved.revenue,
            "is_estimated": resolved.is_estimated,
            "adr": calc_adr(resolved.revenue, sold_unit_nights),
            "revpar": calc_revpar(resolved.revenue, available_unit_nights),
            "payments_total": report.payments_total,
            "services_total": report.services_total,
        }

    def get_channels(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Статистика каналов из Reservation API (эталон)."""
        reservations = self.get_reservations(start_date, end_date, date_kind=2)
        stats: dict[str, dict[str, Any]] = {}
        for item in reservations:
            key = item.source_code or item.source_type or "unknown"
            bucket = stats.setdefault(
                key,
                {"source": key, "channel_type": item.channel_type, "count": 0},
            )
            bucket["count"] += 1
        return list(stats.values())

    def get_guest_profiles(self, booking_number: str) -> list[GuestProfile]:
        """Профили гостей из деталей бронирования."""
        booking = self.get_booking(booking_number)
        profiles: list[GuestProfile] = []
        customer = booking.get("customer") or {}
        guests: list[dict[str, Any]] = []
        for stay in booking.get("roomStays") or []:
            if isinstance(stay, dict):
                guests.extend(stay.get("guests") or [])
        if customer:
            guests.append(customer)

        for index, guest in enumerate(guests):
            if not isinstance(guest, dict):
                continue
            phone = guest.get("phone") or guest.get("phoneNumber")
            email = guest.get("email")
            fio = " ".join(
                part
                for part in (
                    guest.get("lastName"),
                    guest.get("firstName"),
                    guest.get("middleName"),
                )
                if part
            ).strip()
            hashes = hash_guest_identifiers(
                phone=str(phone) if phone else None,
                email=str(email) if email else None,
                fio=fio or None,
            )
            guest_key = (
                hashes.phone_hash
                or hashes.email_hash
                or hashes.fio_hash
                or f"{booking_number}-{index}"
            )
            profiles.append(
                GuestProfile(
                    guest_key=guest_key,
                    phone_hash=hashes.phone_hash,
                    email_hash=hashes.email_hash,
                    fio_hash=hashes.fio_hash,
                    booking_number=booking_number,
                )
            )
        return profiles

    def get_dynamic_prices(
        self,
        check_in: date,
        check_out: date,
        category_id: str | None = None,
    ) -> list[DynamicPriceDay]:
        """Цены на конкретные даты (Search API)."""
        base = self.config.travelline.search_base_url.rstrip("/")
        url = f"{base}/v1/properties/{self.property_id}/room-stays"
        params: dict[str, Any] = {
            "arrivalDate": check_in.isoformat(),
            "departureDate": check_out.isoformat(),
            "includePrices": True,
        }
        if category_id:
            params["roomTypeId"] = category_id
        payload = self._partner_request(
            "GET",
            url,
            params=params,
        )
        return parse_dynamic_prices(payload)

    def get_rooms(self) -> list[dict[str, Any]]:
        """Инвентарь квартир WebPMS ``/rooms``."""
        payload = self._webpms_request("GET", "rooms")
        value = payload.get("value")
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
        return _extract_list(payload, "rooms", "items", "value")

    def _label_for_room_type_id(self, room_type_id: str | None) -> str:
        from src.utils.category_labels import room_type_label

        tid = str(room_type_id or "").strip()
        mapped = self.config.travelline.room_type_id_map.get(tid)
        if mapped:
            return mapped
        if tid:
            return room_type_label(tid, self.config.room_type_aliases)
        return "Прочее"

    def _capacity_by_label(self) -> dict[str, int]:
        capacity: dict[str, int] = {}
        try:
            rooms = self.get_rooms()
        except TravelLineError as exc:
            logger.warning("WebPMS /rooms недоступен: %s", exc)
            return capacity
        for room in rooms:
            label = self._label_for_room_type_id(str(room.get("roomTypeId") or ""))
            capacity[label] = capacity.get(label, 0) + 1
        return capacity

    def _collect_stay_ids_from_analytics(self, stay_date: date) -> set[int]:
        services = self.get_analytics_services(stay_date, stay_date, date_kind=1)
        ids: set[int] = set()
        for item in services:
            row = item.raw or {}
            if not _is_stay_service_row(row):
                continue
            rid = row.get("reservationId")
            if rid is None:
                continue
            try:
                ids.add(int(rid))
            except (TypeError, ValueError):
                continue
        return ids

    def _match_stays_by_type(
        self,
        stay_date: date,
        stay_ids: set[int],
    ) -> tuple[dict[str, int], dict[str, int], set[int]]:
        """Разнести проживания по категориям: occupied / booked.

        Ищем roomStay.id ∈ stay_ids (analytics reservationId) среди Active броней.
        """
        import calendar

        occupied: dict[str, int] = {}
        booked: dict[str, int] = {}
        matched: set[int] = set()
        if not stay_ids:
            return occupied, booked, matched

        _, month_days = calendar.monthrange(stay_date.year, stay_date.month)
        windows = [
            (date(stay_date.year, stay_date.month, 1), date(stay_date.year, stay_date.month, month_days)),
            (stay_date - timedelta(days=90), stay_date),
        ]
        seen_numbers: set[str] = set()

        def _consume(booking: dict[str, Any]) -> None:
            for stay in booking.get("roomStays") or []:
                if not isinstance(stay, dict):
                    continue
                try:
                    sid = int(stay.get("id"))
                except (TypeError, ValueError):
                    continue
                if sid not in stay_ids or sid in matched:
                    continue
                bucket = _room_stay_bucket(stay)
                if bucket == "skip":
                    continue
                label = self._label_for_room_type_id(str(stay.get("roomTypeId") or ""))
                if bucket == "booked":
                    booked[label] = booked.get(label, 0) + 1
                else:
                    occupied[label] = occupied.get(label, 0) + 1
                matched.add(sid)

        for start, end in windows:
            if matched >= stay_ids:
                break
            try:
                numbers = self.search_webpms_booking_numbers(start, end, state="Active")
            except TravelLineError as exc:
                logger.warning("Поиск броней WebPMS %s…%s: %s", start, end, exc)
                continue
            todo = [n for n in numbers if n not in seen_numbers]
            seen_numbers.update(todo)
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(self.get_booking, n): n for n in todo}
                for fut in as_completed(futures):
                    try:
                        booking = fut.result()
                    except TravelLineError:
                        continue
                    _consume(booking)
                    if matched >= stay_ids:
                        break
            if matched >= stay_ids:
                break

        return occupied, booked, matched

    def get_stay_occupancy(self, stay_date: date) -> StayOccupancyResult:
        """Загрузка на ночь stay_date с разбивкой по категориям.

        1) analytics/services (dateKind=1) — эталон числа занятых ночей;
        2) WebPMS bookings + /rooms — св / зан / брон по типам.
        """
        from src.utils.category_labels import room_type_label

        total_units = self.config.property.total_units
        stay_ids = self._collect_stay_ids_from_analytics(stay_date)
        analytics_sold = len(stay_ids)
        capacity = self._capacity_by_label()
        available = sum(capacity.values()) or total_units

        occupied_by: dict[str, int] = {}
        booked_by: dict[str, int] = {}
        if stay_ids:
            occupied_by, booked_by, matched = self._match_stays_by_type(stay_date, stay_ids)
            logger.info(
                "Загрузка по категориям на %s: analytics=%s matched=%s",
                stay_date,
                analytics_sold,
                len(matched),
            )
            missing = analytics_sold - len(matched)
            if missing > 0:
                # Не плодим строку «Прочее» (ломает сумму 44); учтём в sold ниже.
                logger.warning(
                    "Не сопоставлены %s roomStay из analytics — в разбивке не показаны",
                    missing,
                )

        # Старый путь: в analytics есть bookingNumber вида YYYYMMDD-…
        if not stay_ids:
            services = self.get_analytics_services(stay_date, stay_date, date_kind=1)
            numbers = sorted(
                {
                    s.booking_number
                    for s in services
                    if s.booking_number and _looks_like_booking_number(s.booking_number)
                }
            )
            cancelled_statuses = {
                "cancelled",
                "canceled",
                "отменена",
                "отменен",
                "noshow",
                "no-show",
                "незаезд",
            }
            for number in numbers:
                try:
                    booking = self.get_booking(number)
                except TravelLineError:
                    occupied_by["Прочее"] = occupied_by.get("Прочее", 0) + 1
                    continue
                status = str(booking.get("status") or "").strip().lower()
                if status in cancelled_statuses:
                    continue
                stays = [
                    s for s in (booking.get("roomStays") or []) if isinstance(s, dict)
                ]
                if not stays:
                    occupied_by["Прочее"] = occupied_by.get("Прочее", 0) + 1
                    continue
                for stay in stays:
                    arrival, departure = _parse_room_stay_dates(stay)
                    if arrival and departure and not (arrival <= stay_date < departure):
                        continue
                    bucket = _room_stay_bucket(stay)
                    if bucket == "skip":
                        continue
                    room_type = stay.get("roomType") or {}
                    if stay.get("roomTypeId"):
                        label = self._label_for_room_type_id(str(stay.get("roomTypeId")))
                    elif isinstance(room_type, dict):
                        raw_name = (
                            room_type.get("name")
                            or room_type.get("shortName")
                            or room_type.get("code")
                            or "Категория"
                        )
                        label = room_type_label(str(raw_name), self.config.room_type_aliases)
                    else:
                        label = room_type_label(
                            str(room_type or "Категория"),
                            self.config.room_type_aliases,
                        )
                    if bucket == "booked":
                        booked_by[label] = booked_by.get(label, 0) + 1
                    else:
                        occupied_by[label] = occupied_by.get(label, 0) + 1

        sold = sum(occupied_by.values()) + sum(booked_by.values())
        if analytics_sold and sold < analytics_sold:
            sold = analytics_sold
        if sold == 0 and analytics_sold:
            sold = analytics_sold
            occupied_by = {"Все категории": sold}

        # Свободно по типам из инвентаря /rooms.
        labels = sorted(set(capacity) | set(occupied_by) | set(booked_by))
        free_by: dict[str, int] = {}
        for label in labels:
            cap = capacity.get(label, 0)
            used = occupied_by.get(label, 0) + booked_by.get(label, 0)
            if cap:
                free_by[label] = max(cap - used, 0)
            elif label == "Прочее":
                free_by[label] = 0

        pct = round(sold / available * 100, 2) if available > 0 else 0.0
        return StayOccupancyResult(
            stay_date=stay_date,
            sold=sold,
            available=available,
            occupancy_pct=pct,
            by_type=occupied_by,
            free_by_type=free_by,
            booked_by_type=booked_by,
            source="travelline",
        )

    def get_stay_occupancy_summary(self, stay_date: date) -> StayOccupancyResult:
        """Быстрая загрузка только по analytics (без WebPMS bookings/{id}).

        Для backfill сезонного прогноза: sold = число stay из analytics/services.
        """
        stay_ids = self._collect_stay_ids_from_analytics(stay_date)
        sold = len(stay_ids)
        available = self.config.property.total_units
        pct = round(sold / available * 100, 2) if available > 0 else 0.0
        return StayOccupancyResult(
            stay_date=stay_date,
            sold=sold,
            available=available,
            occupancy_pct=pct,
            by_type={},
            free_by_type={},
            booked_by_type={},
            source="travelline_fast",
        )


def reconcile_with_sheets(
    report_date: date,
    tl_bookings_count: int,
    sheets_bookings_count: int,
    threshold_pct: float | None = None,
    config: AppConfig | None = None,
    log: Callable[[ReconciliationWarning], None] | None = None,
) -> list[ReconciliationWarning]:
    """Сверка TravelLine vs Google Sheets; лог при превышении порога.

    Если Sheets за день пуст (0), расхождение не поднимаем — таблица ещё
    не заполнена; эталон для сводки — TravelLine.
    """
    cfg = config or get_config()
    threshold = threshold_pct or cfg.travelline.sheets_reconcile_threshold_pct
    warnings: list[ReconciliationWarning] = []

    if sheets_bookings_count == 0:
        logger.info(
            "Сверка ГуглТабл пропущена за %s: ГуглТабл=0, TL=%s",
            report_date,
            tl_bookings_count,
        )
        return warnings

    diff_pct = calc_reconcile_diff_pct(
        float(tl_bookings_count),
        float(sheets_bookings_count),
    )
    if diff_pct > threshold:
        warning = ReconciliationWarning(
            metric="new_bookings",
            tl_value=float(tl_bookings_count),
            sheets_value=float(sheets_bookings_count),
            diff_pct=round(diff_pct, 2),
            message=(
                f"Расхождение новых броней за {report_date:%d.%m.%Y}: "
                f"TL={tl_bookings_count}, ГуглТабл={sheets_bookings_count} "
                f"({diff_pct:.1f}% > порога {threshold}%)"
            ),
        )
        warnings.append(warning)
        if log:
            log(warning)
        else:
            logger.warning(warning.message)
            save_error_log(
                ErrorLogRecord(
                    error_date=report_date,
                    source="travelline",
                    error_type="sheets_reconcile",
                    message=warning.message,
                    details=(
                        f"tl={tl_bookings_count}, sheets={sheets_bookings_count}, "
                        f"diff_pct={diff_pct:.2f}"
                    ),
                )
            )
    return warnings


def count_sheets_bookings_for_date(
    bookings: BookingsSheetData,
    report_date: date,
) -> int:
    """Подсчитать брони в Sheets за дату."""
    return sum(
        record.bookings_count
        for record in bookings.records
        if record.report_date == report_date
    )


def run_daily_reconciliation(
    report_date: date,
    client: TravelLineClient | None = None,
    sheets_client: GoogleSheetsClient | None = None,
    config: AppConfig | None = None,
) -> list[ReconciliationWarning]:
    """Сверка новых броней TL (dateKind=2) и Sheets за день."""
    cfg = config or get_config()
    tl = client or TravelLineClient(cfg)
    sheets = sheets_client or GoogleSheetsClient(cfg)
    tl_reservations = tl.get_reservations(
        report_date,
        report_date,
        date_kind=2,
        fetch_details=False,
    )
    sheets_data = sheets.read_bookings_stats()
    sheets_count = count_sheets_bookings_for_date(sheets_data, report_date)
    return reconcile_with_sheets(
        report_date,
        tl_bookings_count=len(tl_reservations),
        sheets_bookings_count=sheets_count,
        config=cfg,
    )
