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
from src.notifiers.max_bot import (
    CategoryPriceLine,
    ChannelBookingLine,
    DailySummaryData,
    RoomStatusSummary,
    aggregate_room_status,
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
                category="1room23",
                price=4500.0,
                change_pct=0.0,
                traffic_light="🟢",
            ),
            CategoryPriceLine(
                category="1room",
                price=5000.0,
                change_pct=5.5,
                traffic_light="🟡",
            ),
        ],
    )


def test_build_daily_summary_text_contains_sections() -> None:
    text = build_daily_summary_text(_sample_summary())
    assert "07.07.2026" in text
    assert "🟢 72.5%" in text
    assert "1-комн. 23" in text
    assert "Итого" in text
    assert "Новые брони" in text
    assert "1apart.ru" in text
    assert "1room23" in text
    assert "4 500" in text or "4500" in text


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
    assert client.calls[0]["params"]["chat_id"] == 364502022

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
    assert row["dry_run"] == 1
