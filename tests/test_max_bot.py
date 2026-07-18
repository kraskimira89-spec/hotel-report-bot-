"""Тесты Max Bot: сборка сводки, dry-run, отправка."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from src.config import AppConfig, EnvSettings, MaxBotConfig, StorageConfig, get_config
from src.data_sources.sheets import (
    OccupancySheetData,
    RoomStatus,
    RoomTypeOccupancy,
    RoomUnit,
)
from src.metrics.occupancy import calc_occupancy
from src.notifiers.max_bot import (
    CategoryPriceLine,
    ChannelBookingLine,
    CompetitorCategoryPrice,
    CompetitorSummaryLine,
    DailySummaryData,
    RoomStatusSummary,
    aggregate_room_status,
    build_daily_summary_sections,
    build_daily_summary_text,
    send_daily_summary,
    send_message,
    split_message,
)
from src.storage import db as storage_db
from src.storage.db import init_db


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"ok": True}
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = responses or [_FakeResponse()]
        self._index = 0

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        resp = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return resp


@pytest.fixture
def max_config() -> AppConfig:
    return AppConfig(
        dry_run=True,
        max_bot=MaxBotConfig(
            api_url="https://platform-api2.max.ru",
            chat_id="111222333",
            test_chat_id="364502022",
            max_message_length=4000,
            max_retries=3,
            backoff_initial_sec=0.01,
            backoff_max_sec=0.05,
        ),
    )


@pytest.fixture
def env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.notifiers.max_bot.get_env_settings",
        lambda: EnvSettings(max_token="test-token"),
    )


def _sample_summary() -> DailySummaryData:
    return DailySummaryData(
        report_date=date(2026, 7, 7),
        room_types=[
            RoomStatusSummary(label="1-комн. 23", free=1, occupied=4, booked=1),
            RoomStatusSummary(label="Люкс", free=0, occupied=2, booked=1),
        ],
        totals=RoomStatusSummary(label="Итого", free=1, occupied=6, booked=2),
        occupancy_pct=72.5,
        occupancy_light="🟢",
        new_bookings_total=5,
        new_bookings_light="🟢",
        bookings_by_channel=[
            ChannelBookingLine(source="1apart.ru", channel_type="direct", count=3),
            ChannelBookingLine(source="Островок", channel_type="aggregator", count=2),
        ],
        prices=[
            CategoryPriceLine(
                category="Однокомнатные квартиры 23 м²",
                price=4500.0,
                change_pct=0.0,
                traffic_light="🟢",
            ),
            CategoryPriceLine(
                category="Однокомнатные квартиры 27 м²",
                price=5000.0,
                change_pct=5.5,
                traffic_light="🟡",
            ),
        ],
        competitors=[
            CompetitorSummaryLine(
                name="Bon Apart",
                items=[
                    CompetitorCategoryPrice(label="1-КК ул.", price=5200.0),
                    CompetitorCategoryPrice(label="2-КК", price=7800.0),
                ],
            ),
            CompetitorSummaryLine(
                name="Гоголь",
                items=[CompetitorCategoryPrice(label="от", price=6100.0)],
            ),
        ],
        revenue=185000.0,
        revenue_change_pct=8.5,
    )


def test_build_daily_summary_text_contains_sections() -> None:
    text = build_daily_summary_text(_sample_summary())
    assert "07.07.2026" in text
    assert "🟢 72.5%" in text
    assert "1-КК" in text
    assert "Итого занято" in text
    assert "Новые брони" in text
    assert "1apart.ru" in text
    assert "за 4 500 ₽" not in text
    assert "4 / 1 / 1" not in text
    assert "*Занято по категориям:*" in text
    assert "выручка" not in text
    assert "к вчера" not in text
    assert "Конкурент:" in text
    assert "Bon Apart" in text
    assert "5 200 ₽" in text
    assert "Цены «от» по категориям" not in text


def test_build_daily_summary_sections_split_by_blocks() -> None:
    sections = build_daily_summary_sections(_sample_summary())
    # загрузка + брони + по сообщению на каждого конкурента
    assert len(sections) >= 4
    assert "Загрузка" in sections[0]
    assert "выручка" not in sections[0]
    assert "Новые брони" in sections[1]
    assert "Конкурент:" in sections[2]
    assert "Bon Apart" in sections[2]
    assert "Гоголь" in sections[3]


def test_occupancy_total_without_revenue() -> None:
    data = _sample_summary()
    text = build_daily_summary_sections(data)[0]
    assert "*Итого занято:* 6 из 9" in text
    assert "выручка" not in text
    assert "к вчера" not in text


def test_aggregate_room_status_from_units() -> None:
    occupancy = OccupancySheetData(
        units=[
            RoomUnit(room_id="1", room_type="A", status=RoomStatus.FREE),
            RoomUnit(room_id="2", room_type="A", status=RoomStatus.OCCUPIED),
            RoomUnit(room_id="3", room_type="B", status=RoomStatus.BOOKED),
        ]
    )
    by_type, totals = aggregate_room_status(occupancy)
    assert len(by_type) == 2
    assert totals.free == 1
    assert totals.occupied == 1
    assert totals.booked == 1


def test_aggregate_room_status_from_room_types() -> None:
    occupancy = OccupancySheetData(
        room_types=[
            RoomTypeOccupancy(
                room_type="A",
                free_count=2,
                occupied_count=3,
                booked_count=1,
            )
        ]
    )
    _, totals = aggregate_room_status(occupancy)
    assert totals.free == 2
    assert totals.occupied == 3
    assert totals.booked == 1


def test_split_message_short() -> None:
    assert split_message("hello", 4000) == ["hello"]


def test_split_message_long() -> None:
    lines = [f"line-{i}" for i in range(500)]
    text = "\n".join(lines)
    parts = split_message(text, 200)
    assert len(parts) > 1
    assert all(len(p) <= 200 for p in parts)


def test_send_message_dry_run_uses_test_chat(
    max_config: AppConfig, env_token: None
) -> None:
    client = _FakeClient()
    result = send_message("тест", config=max_config, client=client)

    assert result["status"] == "sent"
    assert result["dry_run"] is True
    assert result["chat_id"] == "364502022"
    assert client.calls[0]["params"]["chat_id"] == 364502022
    assert client.calls[0]["json"]["text"] == "тест"
    assert client.calls[0]["headers"]["Authorization"] == "test-token"


def test_send_message_production_uses_main_chat(
    max_config: AppConfig, env_token: None
) -> None:
    max_config.dry_run = False
    client = _FakeClient()
    result = send_message("тест", config=max_config, client=client)

    assert result["chat_id"] == "111222333"
    assert client.calls[0]["params"]["chat_id"] == 111222333


def test_send_message_retries_on_429(
    max_config: AppConfig, env_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.utils.retry.time.sleep", lambda _: None)
    client = _FakeClient(
        [_FakeResponse(429), _FakeResponse(429), _FakeResponse(200)]
    )
    result = send_message("тест", config=max_config, client=client)
    assert result["status"] == "sent"
    assert len(client.calls) == 3


def test_send_daily_summary_writes_reports_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_config: AppConfig,
    env_token: None,
) -> None:
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SETTINGS_PATH", "config/settings.example.yaml")

    def _patched_db_path() -> Any:
        return db_file

    cfg = get_config()
    cfg.storage = StorageConfig(db_path=str(db_file))
    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()

    client = _FakeClient()
    result = send_daily_summary(
        report_date=date(2026, 7, 7),
        config=max_config,
        summary_data=_sample_summary(),
        client=client,
    )

    assert result["status"] == "sent"
    assert result["dry_run"] is True
    assert result["parts"] == 4
    assert len(client.calls) == 4
    assert client.calls[0]["params"]["chat_id"] == 364502022
    first_text = client.calls[0]["json"]["text"]
    assert "1-КК 23: 5" in first_text
    assert "за 4 500" not in first_text
    assert "выручка" not in first_text
    assert "из 9" in first_text
    assert "Конкурент:" in client.calls[2]["json"]["text"]
    assert "брон" not in first_text
    assert any("Конкурент:" in call["json"]["text"] for call in client.calls)

    conn = storage_db.get_connection()
    try:
        row = conn.execute(
            "SELECT report_type, status, dry_run FROM reports_log"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["report_type"] == "max"
    assert row["status"] == "sent"
def test_prepare_daily_summary_prefers_travelline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.data_sources.sheets import BookingsSheetData, OccupancySheetData
    from src.data_sources.travelline import StayOccupancyResult
    from src.notifiers.max_bot import prepare_daily_summary_data
    from src.storage import db as storage_db

    db_file = tmp_path / "summary.db"

    def _patched_db_path() -> Path:
        return db_file

    monkeypatch.setattr(storage_db, "get_db_path", _patched_db_path)
    monkeypatch.setattr("src.config.get_db_path", _patched_db_path)
    init_db()

    class _FakeTL:
        def get_stay_occupancy(self, stay_date: date) -> StayOccupancyResult:
            return StayOccupancyResult(
                stay_date=stay_date,
                sold=25,
                available=44,
                occupancy_pct=round(25 / 44 * 100, 2),
                by_type={
                    "Однокомнатные квартиры 23 м²": 10,
                    "Однокомнатные квартиры 27 м²": 15,
                },
                free_by_type={
                    "Однокомнатные квартиры 23 м²": 7,
                    "Однокомнатные квартиры 27 м²": 2,
                },
                booked_by_type={
                    "Однокомнатные квартиры 23 м²": 0,
                    "Однокомнатные квартиры 27 м²": 0,
                },
            )

        def get_channels(self, start: date, end: date) -> list[dict]:
            return [
                {"source": "Сайт гостиницы", "channel_type": "direct", "count": 10},
                {"source": "Островок", "channel_type": "aggregator", "count": 3},
            ]

    monkeypatch.setattr(
        "src.data_sources.travelline.TravelLineClient",
        lambda *a, **k: _FakeTL(),
    )
    monkeypatch.setattr(
        "src.data_sources.travelline.run_daily_reconciliation",
        lambda *a, **k: [],
    )

    data = prepare_daily_summary_data(
        date(2026, 7, 16),
        occupancy=OccupancySheetData(is_available=True),
        bookings=BookingsSheetData(is_available=True, records=[]),
    )
    assert data.occupancy_source == "travelline"
    assert data.bookings_source == "travelline"
    assert data.occupancy_pct == round(25 / 44 * 100, 2)
    assert data.new_bookings_total == 13
    assert data.critical_error is False
    labels = {r.label: r for r in data.room_types}
    assert labels["Однокомнатные квартиры 23 м²"].free == 7
    assert labels["Однокомнатные квартиры 23 м²"].occupied == 10
    assert labels["Однокомнатные квартиры 27 м²"].occupied == 15
    assert data.totals is not None
    assert data.totals.free == 19  # available 44 − occupied 25
    assert data.totals.occupied == 25
    assert data.totals.total == 44


def test_prepare_reconciles_sold_vs_category_sum(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """% и «Итого занято» из sold; остаток — отдельная строка категорий."""
    from src.data_sources.sheets import BookingsSheetData, OccupancySheetData
    from src.data_sources.travelline import StayOccupancyResult
    from src.notifiers.max_bot import build_daily_summary_sections, prepare_daily_summary_data

    db_file = tmp_path / "summary_gap.db"
    monkeypatch.setattr(storage_db, "get_db_path", lambda: db_file)
    monkeypatch.setattr("src.config.get_db_path", lambda: db_file)
    init_db()

    class _FakeTL:
        def get_stay_occupancy(self, stay_date: date) -> StayOccupancyResult:
            return StayOccupancyResult(
                stay_date=stay_date,
                sold=24,
                available=44,
                occupancy_pct=round(24 / 44 * 100, 2),
                by_type={"Однокомнатные квартиры 23 м²": 10},
                free_by_type={"Однокомнатные квартиры 23 м²": 5},
                booked_by_type={"Однокомнатные квартиры 23 м²": 0},
            )

        def get_channels(self, start: date, end: date) -> list[dict]:
            return []

    monkeypatch.setattr(
        "src.data_sources.travelline.TravelLineClient",
        lambda *a, **k: _FakeTL(),
    )
    data = prepare_daily_summary_data(
        date(2026, 7, 18),
        occupancy=OccupancySheetData(is_available=True),
        bookings=BookingsSheetData(is_available=True, records=[]),
    )
    assert data.totals is not None
    assert data.totals.occupied == 24
    assert data.totals.total == 44
    assert abs(data.occupancy_pct - calc_occupancy(24, 44)) < 0.01
    assert any("Не разнесено" in r.label for r in data.room_types)
    text = build_daily_summary_sections(data)[0]
    assert "54.5%" in text or f"{data.occupancy_pct:.1f}%" in text
    assert "24 из 44" in text
