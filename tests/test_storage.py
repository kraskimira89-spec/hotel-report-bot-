"""Тесты SQLite-хранилища: запись, чтение, сравнение периодов."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.config import StorageConfig, get_config
from src.storage import db as storage_db
from src.storage.db import (
    compare_metrics_yesterday,
    compare_prices_last_week,
    compare_prices_yesterday,
    get_bookings_daily,
    get_errors_log,
    get_guest,
    get_metrics_daily,
    get_price_snapshots,
    init_db,
    save_booking_daily,
    save_error_log,
    save_metrics_daily,
    save_price_snapshots,
    save_report_log,
    upsert_guest,
)
from src.storage.models import (
    BookingDailyRecord,
    ErrorLogRecord,
    GuestRecord,
    MetricsDailyRecord,
    PriceSnapshotRecord,
    ReportLogRecord,
)


@pytest.fixture
def test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированная БД для тестов."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _patched_db_path() -> Path:
        return db_file

    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)

    init_db()
    return db_file


def test_init_db_creates_tables(test_db: Path) -> None:
    assert test_db.exists()
    init_db()


def test_save_and_read_price_snapshots(test_db: Path) -> None:
    now = datetime(2026, 7, 7, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    snapshots = [
        PriceSnapshotRecord(
            snapshot_at=now,
            category="1room23",
            price=4500.0,
            source="site",
            url="https://1apart.ru/1room23",
        ),
        PriceSnapshotRecord(
            snapshot_at=now,
            category="1room",
            price=5000.0,
            source="site",
        ),
    ]
    assert save_price_snapshots(snapshots) == 2

    rows = get_price_snapshots(date(2026, 7, 7), date(2026, 7, 7))
    assert len(rows) == 2
    assert rows[0].category in {"1room23", "1room"}


def test_price_snapshots_upsert(test_db: Path) -> None:
    now = datetime(2026, 7, 7, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    save_price_snapshots(
        [PriceSnapshotRecord(snapshot_at=now, category="1room", price=5000.0)]
    )
    save_price_snapshots(
        [PriceSnapshotRecord(snapshot_at=now, category="1room", price=5200.0)]
    )
    rows = get_price_snapshots(date(2026, 7, 7), date(2026, 7, 7), category="1room")
    assert len(rows) == 1
    assert rows[0].price == 5200.0


def test_compare_prices_yesterday_and_week(test_db: Path) -> None:
    base = datetime(2026, 7, 7, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    save_price_snapshots(
        [PriceSnapshotRecord(snapshot_at=base, category="1room", price=5000.0)]
    )
    save_price_snapshots(
        [
            PriceSnapshotRecord(
                snapshot_at=base.replace(day=6),
                category="1room",
                price=4800.0,
            )
        ]
    )
    save_price_snapshots(
        [
            PriceSnapshotRecord(
                snapshot_at=base.replace(day=30, month=6),
                category="1room",
                price=4500.0,
            )
        ]
    )

    yesterday = compare_prices_yesterday(date(2026, 7, 7))
    assert yesterday[0].reference_price == 5000.0
    assert yesterday[0].compare_price == 4800.0
    assert yesterday[0].change_pct == pytest.approx(4.17)

    week = compare_prices_last_week(date(2026, 7, 7))
    assert week[0].compare_price == 4500.0


def test_save_and_read_metrics(test_db: Path) -> None:
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=date(2026, 7, 7),
            occupancy_pct=68.0,
            adr=5000.0,
            revpar=3400.0,
            revenue=100000.0,
            bookings_count=12,
        )
    )
    rows = get_metrics_daily(date(2026, 7, 1), date(2026, 7, 31))
    assert len(rows) == 1
    assert rows[0].bookings_count == 12


def test_compare_metrics_yesterday(test_db: Path) -> None:
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=date(2026, 7, 7),
            occupancy_pct=70.0,
            revenue=100000.0,
        )
    )
    save_metrics_daily(
        MetricsDailyRecord(
            report_date=date(2026, 7, 6),
            occupancy_pct=60.0,
            revenue=80000.0,
        )
    )
    cmp = compare_metrics_yesterday(date(2026, 7, 7))
    assert cmp.reference_metrics is not None
    assert cmp.reference_metrics.occupancy_pct == 70.0
    assert cmp.metrics is not None
    assert cmp.metrics.occupancy_pct == 60.0


def test_bookings_guests_reports_errors(test_db: Path) -> None:
    guest = GuestRecord(
        guest_id="hash_phone_abc",
        phone_hash="abc123",
        first_seen=date(2026, 7, 1),
        last_seen=date(2026, 7, 7),
        is_returning=True,
    )
    upsert_guest(guest)
    assert get_guest("hash_phone_abc") is not None

    save_booking_daily(
        BookingDailyRecord(
            created_date=date(2026, 7, 7),
            source="1apart.ru",
            channel="direct",
            amount=15000.0,
            guest_id="hash_phone_abc",
        )
    )
    bookings = get_bookings_daily(date(2026, 7, 7), date(2026, 7, 7))
    assert len(bookings) == 1
    assert bookings[0].guest_id == "hash_phone_abc"

    save_report_log(
        ReportLogRecord(
            report_type="max",
            report_date=date(2026, 7, 7),
            run_date=date(2026, 7, 7),
            status="sent",
            dry_run=True,
            preview="Сводка за день",
        )
    )

    save_error_log(
        ErrorLogRecord(
            error_date=date(2026, 7, 7),
            source="site_prices",
            error_type="HTTPError",
            message="403 Forbidden",
            resolved=False,
        )
    )
    errors = get_errors_log(resolved=False)
    assert len(errors) == 1
    assert errors[0].message == "403 Forbidden"


def test_get_history_period(test_db: Path) -> None:
    for day in range(1, 4):
        save_metrics_daily(
            MetricsDailyRecord(
                report_date=date(2026, 7, day),
                occupancy_pct=50.0 + day,
            )
        )
    rows = get_metrics_daily(date(2026, 7, 1), date(2026, 7, 3))
    assert len(rows) == 3
