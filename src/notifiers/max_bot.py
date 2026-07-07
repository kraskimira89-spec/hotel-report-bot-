"""Отправка ежедневной сводки через Max Bot API."""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from src.config import AppConfig, get_config, get_env_settings
from src.data_sources.sheets import (
    BookingsSheetData,
    GoogleSheetsClient,
    OccupancySheetData,
    RoomStatus,
    RoomTypeOccupancy,
)
from src.metrics.guests import classify_channel
from src.metrics.occupancy import calc_occupancy, traffic_light
from src.storage.db import compare_prices_yesterday, save_report_log
from src.storage.models import ReportLogRecord

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {401, 403, 429, 500, 502, 503, 504}


class RoomStatusSummary(BaseModel):
    """Сводка статусов номеров по типу или итого."""

    label: str
    free: int = 0
    occupied: int = 0
    booked: int = 0

    @property
    def total(self) -> int:
        return self.free + self.occupied + self.booked


class ChannelBookingLine(BaseModel):
    """Новые брони по каналу."""

    source: str
    channel_type: str
    count: int


class CategoryPriceLine(BaseModel):
    """Цена категории и отклонение к вчера."""

    category: str
    price: float
    change_pct: float | None = None
    traffic_light: str = "🟡"


class DailySummaryData(BaseModel):
    """Данные для формирования ежедневной сводки."""

    report_date: date
    room_types: list[RoomStatusSummary] = Field(default_factory=list)
    totals: RoomStatusSummary | None = None
    occupancy_pct: float = 0.0
    occupancy_light: str = "🟡"
    new_bookings_total: int = 0
    new_bookings_light: str = "🟡"
    bookings_by_channel: list[ChannelBookingLine] = Field(default_factory=list)
    prices: list[CategoryPriceLine] = Field(default_factory=list)


class HttpPoster(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...



def aggregate_room_status(
    occupancy: OccupancySheetData,
    room_types: list[RoomTypeOccupancy] | None = None,
) -> tuple[list[RoomStatusSummary], RoomStatusSummary]:
    """Агрегировать статусы по типам и итого."""
    summaries: list[RoomStatusSummary] = []

    if room_types is None:
        room_types = occupancy.room_types

    if occupancy.units:
        by_type: dict[str, RoomStatusSummary] = {}
        for unit in occupancy.units:
            summary = by_type.setdefault(
                unit.room_type,
                RoomStatusSummary(label=unit.room_type),
            )
            if unit.status == RoomStatus.FREE:
                summary.free += 1
            elif unit.status == RoomStatus.OCCUPIED:
                summary.occupied += 1
            elif unit.status == RoomStatus.BOOKED:
                summary.booked += 1
        summaries = sorted(by_type.values(), key=lambda s: s.label)
    else:
        for row in room_types:
            summaries.append(
                RoomStatusSummary(
                    label=row.room_type,
                    free=row.free_count or 0,
                    occupied=row.occupied_count or 0,
                    booked=row.booked_count or 0,
                )
            )

    totals = RoomStatusSummary(
        label="Итого",
        free=sum(s.free for s in summaries),
        occupied=sum(s.occupied for s in summaries),
        booked=sum(s.booked for s in summaries),
    )
    return summaries, totals


def prepare_daily_summary_data(
    report_date: date,
    config: AppConfig | None = None,
    occupancy: OccupancySheetData | None = None,
    bookings: BookingsSheetData | None = None,
) -> DailySummaryData:
    """Собрать данные сводки из Sheets и SQLite."""
    cfg = config or get_config()
    sheets_client = GoogleSheetsClient(cfg)

    if occupancy is None:
        occupancy = sheets_client.read_occupancy()
    if bookings is None:
        bookings = sheets_client.read_bookings_stats()

    room_types, totals = aggregate_room_status(occupancy)
    sold = totals.occupied + totals.booked
    available = totals.total or cfg.property.total_units
    occupancy_pct = calc_occupancy(sold, available)
    occupancy_light = traffic_light(
        occupancy_pct, cfg.traffic_light, metric="occupancy"
    )

    day_bookings = [
        b for b in bookings.records if b.report_date == report_date
    ]
    new_bookings_total = sum(b.bookings_count for b in day_bookings)
    new_bookings_light = traffic_light(
        float(new_bookings_total),
        cfg.traffic_light,
        metric="new_bookings",
    )

    bookings_by_channel: list[ChannelBookingLine] = []
    for record in day_bookings:
        bookings_by_channel.append(
            ChannelBookingLine(
                source=record.source,
                channel_type=classify_channel(record.source, cfg.channels_map),
                count=record.bookings_count,
            )
        )
    bookings_by_channel.sort(key=lambda x: (-x.count, x.source))

    price_lines: list[CategoryPriceLine] = []
    for item in compare_prices_yesterday(report_date):
        if item.reference_price is None:
            continue
        change = item.change_pct
        light = (
            traffic_light(change or 0.0, cfg.traffic_light, metric="price_change")
            if change is not None
            else "🟡"
        )
        price_lines.append(
            CategoryPriceLine(
                category=item.category,
                price=item.reference_price,
                change_pct=change,
                traffic_light=light,
            )
        )

    return DailySummaryData(
        report_date=report_date,
        room_types=room_types,
        totals=totals,
        occupancy_pct=occupancy_pct,
        occupancy_light=occupancy_light,
        new_bookings_total=new_bookings_total,
        new_bookings_light=new_bookings_light,
        bookings_by_channel=bookings_by_channel,
        prices=price_lines,
    )


def build_daily_summary_text(data: DailySummaryData) -> str:
    """Сформировать Markdown-текст ежедневной сводки (без сети)."""
    lines = [
        f"📊 *Сводка за {data.report_date.strftime('%d.%m.%Y')}*",
        "",
        f"*Загрузка:* {data.occupancy_light} {data.occupancy_pct:.1f}%",
        "",
        "*Статус номеров* (св / зан / брон):",
    ]

    for row in data.room_types:
        lines.append(
            f"• {row.label}: {row.free} / {row.occupied} / {row.booked}"
        )
    if data.totals:
        t = data.totals
        lines.append(
            f"*Итого:* {t.free} / {t.occupied} / {t.booked} "
            f"(всего {t.total})"
        )

    lines.extend(
        [
            "",
            f"*Новые брони:* {data.new_bookings_light} {data.new_bookings_total}",
        ]
    )
    if data.bookings_by_channel:
        for ch in data.bookings_by_channel:
            lines.append(f"  - {ch.source} ({ch.channel_type}): {ch.count}")
    else:
        lines.append("  - нет данных")

    lines.extend(["", "*Цены «от» по категориям:*"])
    if data.prices:
        for price in data.prices:
            if price.change_pct is None:
                change_txt = "н/д"
            else:
                sign = "+" if price.change_pct > 0 else ""
                change_txt = f"{sign}{price.change_pct:.1f}%"
            lines.append(
                f"{price.traffic_light} {price.category}: "
                f"{price.price:,.0f} ₽ ({change_txt})".replace(",", " ")
            )
    else:
        lines.append("  - нет snapshot")

    return "\n".join(lines)


def split_message(text: str, max_length: int) -> list[str]:
    """Разбить длинный текст на части ≤ max_length (по строкам)."""
    if len(text) <= max_length:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines():
        add_len = len(line) + (1 if current else 0)
        if current and current_len + add_len > max_length:
            parts.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += add_len

    if current:
        chunk = "\n".join(current)
        if len(chunk) > max_length:
            parts.append(chunk[: max_length - 3] + "...")
        else:
            parts.append(chunk)

    return parts or [text[: max_length - 3] + "..."]


def _resolve_chat_id(cfg: AppConfig, dry_run: bool) -> str:
    if dry_run:
        return cfg.max_bot.test_chat_id or cfg.max_bot.chat_id
    return cfg.max_bot.chat_id


def send_message(
    text: str,
    dry_run: bool | None = None,
    config: AppConfig | None = None,
    client: HttpPoster | None = None,
) -> dict[str, Any]:
    """Отправить сообщение в Max (POST /messages).

    При dry_run=True — в test_chat_id (реальная отправка, не в основной чат).
    """
    cfg = config or get_config()
    env = get_env_settings()
    is_dry = cfg.dry_run if dry_run is None else dry_run
    chat_id = _resolve_chat_id(cfg, is_dry)

    if not chat_id:
        logger.warning("chat_id не задан (dry_run=%s)", is_dry)
        return {"status": "skipped", "reason": "no_chat_id", "dry_run": is_dry}

    if not env.max_token:
        logger.warning("MAX_TOKEN не задан, отправка пропущена")
        return {"status": "skipped", "reason": "no_token", "dry_run": is_dry}

    url = f"{cfg.max_bot.api_url.rstrip('/')}/messages"
    headers = {"Authorization": env.max_token}
    payload = {"chat_id": chat_id, "text": text, "format": "markdown"}

    delay = cfg.max_bot.backoff_initial_sec
    last_response: httpx.Response | None = None

    for attempt in range(cfg.max_bot.max_retries):
        try:
            poster = client or httpx
            resp = poster.post(url, json=payload, headers=headers, timeout=30.0)
            last_response = resp

            if resp.status_code in RETRYABLE_STATUS:
                logger.warning(
                    "Max API %s, retry %s/%s",
                    resp.status_code,
                    attempt + 1,
                    cfg.max_bot.max_retries,
                )
                if attempt >= cfg.max_bot.max_retries - 1:
                    return {
                        "status": "error",
                        "http_status": resp.status_code,
                        "chat_id": chat_id,
                        "dry_run": is_dry,
                    }
                time.sleep(min(delay, cfg.max_bot.backoff_max_sec))
                delay *= 2
                continue

            resp.raise_for_status()
            body: dict[str, Any] = {
                "status": "sent",
                "chat_id": chat_id,
                "dry_run": is_dry,
            }
            try:
                body["response"] = resp.json()
            except ValueError:
                body["response"] = resp.text
            return body

        except httpx.HTTPError as exc:
            logger.error("Ошибка Max API: %s", exc)
            if attempt < cfg.max_bot.max_retries - 1:
                time.sleep(min(delay, cfg.max_bot.backoff_max_sec))
                delay *= 2
            else:
                return {
                    "status": "error",
                    "chat_id": chat_id,
                    "dry_run": is_dry,
                    "error": str(exc),
                }

    return {
        "status": "error",
        "http_status": last_response.status_code if last_response else None,
        "chat_id": chat_id,
        "dry_run": is_dry,
    }


def send_daily_summary(
    report_date: date | None = None,
    run_date: date | None = None,
    config: AppConfig | None = None,
    summary_data: DailySummaryData | None = None,
    client: HttpPoster | None = None,
) -> dict[str, Any]:
    """Собрать и отправить ежедневную сводку; записать результат в reports_log."""
    cfg = config or get_config()
    run_date = run_date or date.today()
    report_date = report_date or run_date

    data = summary_data or prepare_daily_summary_data(report_date, config=cfg)
    text = build_daily_summary_text(data)
    parts = split_message(text, cfg.max_bot.max_message_length)

    results: list[dict[str, Any]] = []
    for index, part in enumerate(parts, start=1):
        if len(parts) > 1:
            part = f"[{index}/{len(parts)}]\n{part}"
        results.append(send_message(part, config=cfg, client=client))

    success = all(r.get("status") == "sent" for r in results)
    status = "sent" if success else "error"
    preview = text[:200]

    save_report_log(
        ReportLogRecord(
            report_type="max",
            report_date=report_date,
            run_date=run_date,
            status=status,
            dry_run=cfg.dry_run,
            preview=preview,
            message=str(results),
        )
    )

    logger.info(
        "Ежедневная сводка Max: status=%s, parts=%s, dry_run=%s",
        status,
        len(parts),
        cfg.dry_run,
    )
    return {
        "status": status,
        "parts": len(parts),
        "dry_run": cfg.dry_run,
        "results": results,
        "text": text,
    }
