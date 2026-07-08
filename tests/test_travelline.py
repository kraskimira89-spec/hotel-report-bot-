"""Тесты TravelLine API (моки httpx, без сети)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from src.config import AppConfig, EnvSettings, StorageConfig, TravelLineConfig, get_config
from src.data_sources.sheets import BookingRecord, BookingsSheetData
from src.data_sources.travelline import (
    TravelLineClient,
    calc_reconcile_diff_pct,
    ensure_date_window,
    format_tl_date,
    msk_date_to_utc_start,
    parse_analytics_payments,
    parse_analytics_services,
    parse_reservation_search,
    reconcile_with_sheets,
    run_daily_reconciliation,
    utc_to_msk_date,
)
from src.storage import db as storage_db
from src.storage.db import init_db


@pytest.fixture
def tl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.data_sources.travelline.get_env_settings",
        lambda: EnvSettings(tl_api_key="test-key"),
    )


FIXTURES = Path(__file__).parent / "fixtures" / "travelline"


class MockTransport(httpx.BaseTransport):
    """Маршрутизация ответов по URL-паттерну."""

    def __init__(self, routes: dict[str, dict]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        for pattern, payload in self.routes.items():
            if pattern in url:
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def tl_config() -> AppConfig:
    return AppConfig(
        travelline=TravelLineConfig(
            property_id="7291",
            webpms_base_url="https://partner.tlintegration.com/api/webpms",
            reservation_base_url="https://partner.tlintegration.com/api/read-reservation",
            search_base_url="https://partner.tlintegration.com/api/search",
            sheets_reconcile_threshold_pct=10.0,
            backoff_initial_sec=0.01,
            backoff_max_sec=0.05,
            max_retries=2,
        )
    )


def test_format_tl_date_and_window() -> None:
    assert format_tl_date(date(2026, 7, 7)) == "20260707"
    ensure_date_window(date(2026, 7, 1), date(2026, 7, 31), max_days=31)
    with pytest.raises(Exception):
        ensure_date_window(date(2026, 7, 1), date(2026, 8, 5), max_days=31)


def test_msk_utc_conversion() -> None:
    utc_start = msk_date_to_utc_start(date(2026, 7, 7))
    assert utc_start.tzinfo == timezone.utc
    assert utc_to_msk_date(datetime(2026, 7, 6, 21, 0, tzinfo=timezone.utc)) == date(
        2026, 7, 7
    )


def test_parse_analytics_fixtures() -> None:
    services = json.loads((FIXTURES / "analytics_services.json").read_text(encoding="utf-8"))
    payments = json.loads((FIXTURES / "analytics_payments.json").read_text(encoding="utf-8"))
    parsed_services = parse_analytics_services(services)
    parsed_payments = parse_analytics_payments(payments)
    assert len(parsed_services) == 2
    assert parsed_services[0].amount == 15000.0
    assert len(parsed_payments) == 1
    assert parsed_payments[0].amount == 12000.0


def test_get_revenue_from_payments(
    tl_config: AppConfig,
    tl_env: None,
) -> None:
    routes = {
        "analytics/payments": json.loads(
            (FIXTURES / "analytics_payments.json").read_text(encoding="utf-8")
        ),
        "analytics/services": {"services": []},
        "analytics/services/cancelled": {"services": []},
    }
    transport = MockTransport(routes)
    client = TravelLineClient(
        tl_config,
        http_client=httpx.Client(transport=transport),
    )
    report = client.get_revenue(date(2026, 7, 7), date(2026, 7, 7))
    assert report.revenue == 12000.0
    assert report.is_estimated is False


def test_get_reservations_date_kind_2(
    tl_config: AppConfig,
    tl_env: None,
) -> None:
    search_payload = json.loads(
        (FIXTURES / "reservations_search.json").read_text(encoding="utf-8")
    )
    transport = MockTransport({"reservations/search": search_payload})
    client = TravelLineClient(tl_config, http_client=httpx.Client(transport=transport))
    items = client.get_reservations(date(2026, 7, 7), date(2026, 7, 7), date_kind=2)
    assert len(items) == 1
    assert items[0].number == "20260707-7291-100"
    assert items[0].channel_type in {"direct", "aggregator", "unknown"}


def test_search_reservations_pagination(
    tl_config: AppConfig,
    tl_env: None,
) -> None:
    page1 = {
        "reservations": [{"number": "A-1", "createdDateTime": "2026-07-07T10:00:00Z"}],
        "hasNextPage": True,
        "nextPageToken": "token-2",
    }
    page2 = {
        "reservations": [{"number": "A-2", "createdDateTime": "2026-07-07T11:00:00Z"}],
        "hasNextPage": False,
    }

    def route_handler(request: httpx.Request) -> httpx.Response:
        if "pageToken=token-2" in str(request.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    transport = httpx.MockTransport(route_handler)
    client = TravelLineClient(tl_config, http_client=httpx.Client(transport=transport))
    items, token, has_next = client.search_reservations()
    assert len(items) == 1
    assert token == "token-2"
    assert has_next is True

    batch, _, _ = client.search_reservations(page_token="token-2")
    assert len(batch) == 1
    assert batch[0].number == "A-2"


def test_parse_reservation_search_channel() -> None:
    payload = json.loads((FIXTURES / "reservations_search.json").read_text(encoding="utf-8"))
    items, token, has_next = parse_reservation_search(payload)
    assert items[0].source_code == "1apart.ru"
    assert has_next is False
    assert token is None


def test_reconcile_logs_warning(
    tl_config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _patched_db_path() -> Path:
        return db_file

    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()

    warnings = reconcile_with_sheets(
        date(2026, 7, 7),
        tl_bookings_count=10,
        sheets_bookings_count=5,
        config=tl_config,
    )
    assert len(warnings) == 1
    assert warnings[0].diff_pct == pytest.approx(100.0)

    conn = storage_db.get_connection()
    try:
        row = conn.execute(
            "SELECT source, error_type FROM errors_log"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["source"] == "travelline"
    assert row["error_type"] == "sheets_reconcile"


def test_calc_reconcile_diff_pct() -> None:
    assert calc_reconcile_diff_pct(11, 10) == pytest.approx(10.0)
    assert calc_reconcile_diff_pct(0, 0) == 0.0


def test_run_daily_reconciliation_mocked(
    tl_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.data_sources.travelline.save_error_log",
        lambda record: 1,
    )

    class FakeTL:
        def get_reservations(self, start: date, end: date, date_kind: int = 2) -> list:
            return [object(), object(), object()]

    class FakeSheets:
        def read_bookings_stats(self) -> BookingsSheetData:
            return BookingsSheetData(
                records=[
                    BookingRecord(
                        report_date=date(2026, 7, 7),
                        source="1apart.ru",
                        bookings_count=2,
                    )
                ]
            )

    warnings = run_daily_reconciliation(
        date(2026, 7, 7),
        client=FakeTL(),  # type: ignore[arg-type]
        sheets_client=FakeSheets(),  # type: ignore[arg-type]
        config=tl_config,
    )
    assert len(warnings) == 1
