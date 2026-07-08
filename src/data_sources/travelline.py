"""Клиент TravelLine API: Universal WebPMS + Read Reservation."""

from __future__ import annotations

import logging
import time
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
        items.append(
            AnalyticsServiceItem(
                booking_number=row.get("bookingNumber") or row.get("number"),
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
        if isinstance(source, str):
            source_code, source_type = source, None
        else:
            source_code = source.get("code") or source.get("name")
            source_type = source.get("type")
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


def calc_reconcile_diff_pct(tl_value: float, sheets_value: float) -> float:
    """Процент расхождения относительно Sheets."""
    if sheets_value == 0:
        return 100.0 if tl_value != 0 else 0.0
    return abs(tl_value - sheets_value) / sheets_value * 100


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
        return httpx.Client(timeout=30.0)

    def authenticate(self, force: bool = False) -> str:
        """Получить Bearer-токен: OAuth или ключ из .env."""
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

        if not self._env.tl_api_key:
            raise TravelLineError("TL_API_KEY не задан")
        self._access_token = self._env.tl_api_key
        self._token_expires_at = time.time() + 3600
        return self._access_token

    def _headers(self) -> dict[str, str]:
        token = self.authenticate()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth_retry: bool = True,
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
                headers=self._headers(),
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

        if response.status_code in {401, 403} and auth_retry:
            self.authenticate(force=True)
            response = retry_with_backoff(
                _call,
                retries=tl.max_retries,
                backoff_initial=tl.backoff_initial_sec,
                backoff_max=tl.backoff_max_sec,
                retry_statuses=(429, 500, 502, 503, 504),
                log_prefix=f"travelline {method} {url}",
            )

        if not response.content:
            return {}
        return response.json()

    def _webpms_url(self, path: str) -> str:
        base = self.config.travelline.webpms_base_url.rstrip("/")
        prop = self.property_id
        return f"{base}/v1/properties/{prop}/{path.lstrip('/')}"

    def _reservation_url(self, path: str) -> str:
        base = self.config.travelline.reservation_base_url.rstrip("/")
        prop = self.property_id
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

    def get_analytics_services(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 1,
    ) -> list[AnalyticsServiceItem]:
        """Начисления/доход (analytics/services)."""
        payload = self._request(
            "GET",
            self._webpms_url("analytics/services"),
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
        payload = self._request(
            "GET",
            self._webpms_url("analytics/payments"),
            params=self._analytics_params(start_date, end_date, date_kind),
        )
        return parse_analytics_payments(payload)

    def get_analytics_cancelled(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 1,
    ) -> list[AnalyticsServiceItem]:
        """Отменённые начисления (analytics/services/cancelled)."""
        payload = self._request(
            "GET",
            self._webpms_url("analytics/services/cancelled"),
            params=self._analytics_params(start_date, end_date, date_kind),
        )
        return parse_analytics_services(payload)

    def get_booking(self, booking_number: str) -> dict[str, Any]:
        """Детали бронирования bookings/{number}."""
        payload = self._request(
            "GET",
            self._webpms_url(f"bookings/{booking_number}"),
        )
        return parse_booking_details(payload)

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
        payload = self._request(
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

    def get_reservations(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 2,
    ) -> list[ReservationSummary]:
        """Новые брони за период.

        date_kind=2 — фильтр по дате создания (MSK → UTC для search).
        """
        if date_kind == 2:
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
                    source_code=source.get("code") if isinstance(source, dict) else None,
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
        payload = self._request("GET", url, params=params)
        return parse_dynamic_prices(payload)


def reconcile_with_sheets(
    report_date: date,
    tl_bookings_count: int,
    sheets_bookings_count: int,
    threshold_pct: float | None = None,
    config: AppConfig | None = None,
    log: Callable[[ReconciliationWarning], None] | None = None,
) -> list[ReconciliationWarning]:
    """Сверка TravelLine vs Google Sheets; лог при превышении порога."""
    cfg = config or get_config()
    threshold = threshold_pct or cfg.travelline.sheets_reconcile_threshold_pct
    warnings: list[ReconciliationWarning] = []

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
                f"TL={tl_bookings_count}, Sheets={sheets_bookings_count} "
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
    tl_reservations = tl.get_reservations(report_date, report_date, date_kind=2)
    sheets_data = sheets.read_bookings_stats()
    sheets_count = count_sheets_bookings_for_date(sheets_data, report_date)
    return reconcile_with_sheets(
        report_date,
        tl_bookings_count=len(tl_reservations),
        sheets_bookings_count=sheets_count,
        config=cfg,
    )
