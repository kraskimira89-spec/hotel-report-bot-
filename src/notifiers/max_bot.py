"""Отправка ежедневной сводки через Max Bot API."""

from __future__ import annotations

import logging
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
    occupancy_day_to_sheet_data,
)
from src.metrics.guests import classify_channel
from src.metrics.occupancy import calc_occupancy, traffic_light
from src.notifiers.max_api import build_max_api_client
from src.storage.db import (
    compare_prices_yesterday,
    get_price_snapshots_by_date,
    save_error_log,
    save_report_log,
)
from src.storage.models import ErrorLogRecord, ReportLogRecord
from src.utils.category_labels import (
    category_label,
    category_short_label,
    room_type_label,
)
from src.utils.retry import retry_with_backoff

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
    occupancy_source: str = "none"
    new_bookings_total: int = 0
    new_bookings_light: str = "🟡"
    bookings_source: str = "none"
    bookings_by_channel: list[ChannelBookingLine] = Field(default_factory=list)
    prices: list[CategoryPriceLine] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    is_partial: bool = False
    critical_error: bool = False


class HttpPoster(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class MessageSender(Protocol):
    def send_message(
        self,
        text: str,
        *,
        chat_id: int | str | None = None,
        user_id: int | str | None = None,
        format: str = "markdown",
    ) -> dict[str, Any]: ...



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
    """Собрать данные сводки: TravelLine основной, ГуглТабл — фолбэк."""
    cfg = config or get_config()
    sheets_client = GoogleSheetsClient(cfg)
    occ_day = None
    sheets_occupancy_ok = True
    sheets_bookings_ok = True

    if occupancy is None:
        try:
            occ_day = sheets_client.read_occupancy_daily(report_date)
            if occ_day.by_type:
                occupancy = occupancy_day_to_sheet_data(occ_day)
            else:
                occupancy = sheets_client.read_occupancy()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ГуглТабл загрузка недоступна: %s", exc)
            sheets_occupancy_ok = False
            occupancy = OccupancySheetData(is_available=False)
    if bookings is None:
        try:
            bookings = sheets_client.read_bookings_stats(report_date)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ГуглТабл брони недоступны: %s", exc)
            sheets_bookings_ok = False
            bookings = BookingsSheetData(is_available=False)

    warnings: list[str] = []
    if occupancy is not None and not occupancy.is_available:
        sheets_occupancy_ok = False
        warnings.append("ГуглТабл недоступен: лист «Заселяемость».")
    if bookings is not None and not bookings.is_available:
        sheets_bookings_ok = False
        warnings.append("ГуглТабл недоступен: лист «Брони статистика».")

    room_types, totals = aggregate_room_status(occupancy)
    sold = totals.occupied + totals.booked
    available = totals.total or cfg.property.total_units
    occupancy_pct = calc_occupancy(sold, available)
    occupancy_source = "sheets"

    # 1) Живые данные TravelLine (эталон «Доходность и загрузка»).
    try:
        from src.data_sources.travelline import TravelLineClient, TravelLineError

        tl_occ = TravelLineClient(cfg).get_stay_occupancy(report_date)
        # Если API пустой, а в ГуглТабл уже есть ненулевая загрузка — не затираем.
        sheets_hint = 0.0
        if occ_day and occ_day.travelline_pct is not None:
            sheets_hint = float(occ_day.travelline_pct)
        elif occ_day and occ_day.total_pct is not None:
            sheets_hint = float(occ_day.total_pct)
        elif sold > 0:
            sheets_hint = float(sold)

        if tl_occ.sold == 0 and sheets_hint > 0:
            warnings.append(
                "TravelLine вернул 0 занятых при ненулевых данных ГуглТабл — "
                "используем ГуглТабл."
            )
        else:
            free_total = max(tl_occ.available - tl_occ.sold, 0)
            labels = sorted(
                set(tl_occ.by_type)
                | set(tl_occ.free_by_type)
                | set(tl_occ.booked_by_type)
            )
            room_types = [
                RoomStatusSummary(
                    label=label,
                    free=int(tl_occ.free_by_type.get(label, 0)),
                    occupied=int(tl_occ.by_type.get(label, 0)),
                    booked=int(tl_occ.booked_by_type.get(label, 0)),
                )
                for label in labels
                if label != "Прочее"
                and (
                    tl_occ.by_type.get(label, 0)
                    or tl_occ.free_by_type.get(label, 0)
                    or tl_occ.booked_by_type.get(label, 0)
                )
            ]
            if not room_types:
                room_types = [
                    RoomStatusSummary(
                        label="Все категории",
                        free=free_total,
                        occupied=tl_occ.sold,
                        booked=0,
                    )
                ]
            occ_total = sum(r.occupied for r in room_types)
            book_total = sum(r.booked for r in room_types)
            # Свободные = инвентарь − (зан+брон); эталон фонда — total_units /rooms.
            free_total = max(tl_occ.available - occ_total - book_total, 0)
            totals = RoomStatusSummary(
                label="Итого",
                free=free_total,
                occupied=occ_total,
                booked=book_total,
            )
            occupancy_pct = tl_occ.occupancy_pct
            occupancy_source = "travelline"
            logger.info(
                "Загрузка из TravelLine на %s: %.1f%% (%s/%s)",
                report_date,
                occupancy_pct,
                tl_occ.sold,
                tl_occ.available,
            )
    except TravelLineError as exc:
        warnings.append(f"Загрузка TravelLine недоступна, берём ГуглТабл: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Загрузка TravelLine пропущена: %s", exc)
        warnings.append("Загрузка TravelLine недоступна, используются данные ГуглТабл.")

    # 2) Фолбэк ГуглТабл: строка «% из Traveline», иначе счётчики / общее кол-во.
    if occupancy_source != "travelline":
        room_types, totals = aggregate_room_status(occupancy)
        room_types = [
            RoomStatusSummary(
                label=room_type_label(r.label, cfg.room_type_aliases),
                free=r.free,
                occupied=r.occupied,
                booked=r.booked,
            )
            for r in room_types
        ]
        sold = totals.occupied + totals.booked
        available = totals.total or cfg.property.total_units
        if occ_day and occ_day.travelline_pct is not None:
            occupancy_pct = occ_day.travelline_pct
            occupancy_source = "sheets_travelline_row"
        elif occ_day and occ_day.total_pct is not None and occ_day.total_pct >= 0:
            # В суточном блоке «общее кол-во» — число занятых квартир, не %.
            total_occupied = int(round(occ_day.total_pct))
            if total_occupied <= cfg.property.total_units:
                occupancy_pct = calc_occupancy(
                    total_occupied,
                    cfg.property.total_units,
                )
            else:
                # Иногда туда попадает уже процент.
                occupancy_pct = float(occ_day.total_pct)
            occupancy_source = "sheets_total"
        else:
            occupancy_pct = calc_occupancy(sold, available)
            occupancy_source = "sheets_calc"

    occupancy_light = traffic_light(
        occupancy_pct, cfg.traffic_light, metric="occupancy"
    )
    if occupancy_source == "travelline":
        logger.info("Загрузка и статусы номеров — по TravelLine (source=%s).", occupancy_source)
    elif occupancy_source == "sheets_travelline_row":
        warnings.append("Загрузка — строка «% из Traveline» из ГуглТабл.")

    # 3) Новые брони: TL (WebPMS) основной, ГуглТабл — фолбэк.
    day_bookings = [b for b in bookings.records if b.report_date == report_date]
    sheets_bookings_total = sum(b.bookings_count for b in day_bookings)
    new_bookings_total = sheets_bookings_total
    bookings_by_channel: list[ChannelBookingLine] = []
    for record in day_bookings:
        bookings_by_channel.append(
            ChannelBookingLine(
                source=record.source,
                channel_type=classify_channel(record.source, cfg.channels_map),
                count=record.bookings_count,
            )
        )
    bookings_source = "sheets" if day_bookings else "none"

    try:
        from src.data_sources.travelline import TravelLineClient, TravelLineError

        tl_channels = TravelLineClient(cfg).get_channels(report_date, report_date)
        tl_total = sum(int(ch.get("count") or 0) for ch in tl_channels)
        if tl_total > 0 or (tl_channels is not None and sheets_bookings_total == 0):
            # Не затираем ненулевые ГуглТабл, если TL вернул 0.
            if tl_total == 0 and sheets_bookings_total > 0:
                warnings.append(
                    "TravelLine вернул 0 новых броней при ненулевых ГуглТабл — "
                    "используем ГуглТабл."
                )
                bookings_source = "sheets"
            else:
                new_bookings_total = tl_total
                bookings_by_channel = [
                    ChannelBookingLine(
                        source=str(ch.get("source") or "unknown"),
                        channel_type=str(ch.get("channel_type") or "unknown"),
                        count=int(ch.get("count") or 0),
                    )
                    for ch in tl_channels
                    if int(ch.get("count") or 0) > 0
                ]
                bookings_source = "travelline"
                logger.info(
                    "Новые брони из TravelLine на %s: %s (source=travelline)",
                    report_date,
                    new_bookings_total,
                )
                if sheets_bookings_total and sheets_bookings_total != tl_total:
                    logger.info(
                        "Брони: TL=%s, ГуглТабл=%s (в сводке — TravelLine).",
                        tl_total,
                        sheets_bookings_total,
                    )
        elif sheets_bookings_total > 0:
            bookings_source = "sheets"
            warnings.append("TravelLine без броней — используем ГуглТабл.")
    except TravelLineError as exc:
        warnings.append(f"Брони TravelLine недоступны, берём ГуглТабл: {exc}")
        bookings_source = "sheets" if sheets_bookings_total else bookings_source
    except Exception as exc:  # noqa: BLE001
        logger.warning("Брони TravelLine пропущены: %s", exc)
        warnings.append("Брони TravelLine недоступны, используются данные ГуглТабл.")
        bookings_source = "sheets" if sheets_bookings_total else bookings_source

    bookings_by_channel.sort(key=lambda x: (-x.count, x.source))
    new_bookings_light = traffic_light(
        float(new_bookings_total),
        cfg.traffic_light,
        metric="new_bookings",
    )

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
                category=category_label(item.category, cfg.category_slug_map),
                price=item.reference_price,
                change_pct=change,
                traffic_light=light,
            )
        )

    snapshots = get_price_snapshots_by_date(report_date)
    if any(s.is_fallback for s in snapshots):
        warnings.append("Часть данных по ценам из последнего снимка.")

    try:
        from src.data_sources.travelline import TravelLineError, run_daily_reconciliation

        recon_warnings = run_daily_reconciliation(report_date, config=cfg)
        for warning in recon_warnings:
            warnings.append(warning.message)
    except TravelLineError as exc:
        warnings.append(f"Сверка TravelLine: {exc}")
    except Exception as exc:
        logger.warning("Сверка TravelLine пропущена: %s", exc)

    # Критично только если нет ни TL, ни ГуглТабл по обоим метрикам.
    critical = (
        occupancy_source.startswith("sheets")
        and not sheets_occupancy_ok
        and bookings_source in {"sheets", "none"}
        and not sheets_bookings_ok
    )
    if occupancy_source == "travelline" or bookings_source == "travelline":
        critical = False

    return DailySummaryData(
        report_date=report_date,
        room_types=room_types,
        totals=totals,
        occupancy_pct=occupancy_pct,
        occupancy_light=occupancy_light,
        occupancy_source=occupancy_source,
        new_bookings_total=new_bookings_total,
        new_bookings_light=new_bookings_light,
        bookings_source=bookings_source,
        bookings_by_channel=bookings_by_channel,
        prices=price_lines,
        warnings=warnings,
        is_partial=bool(warnings),
        critical_error=critical,
    )


def build_daily_summary_sections(data: DailySummaryData) -> list[str]:
    """Сформировать сводку в виде отдельных разделов."""
    sections: list[str] = []

    section_occupancy = [
        f"📊 *Сводка за {data.report_date.strftime('%d.%m.%Y')}*",
        f"*Загрузка:* {data.occupancy_light} {data.occupancy_pct:.1f}%",
        "",
        "*Статус номеров* (св / зан / брон):",
    ]
    for row in data.room_types:
        section_occupancy.append(
            f"• {category_short_label(row.label)}: "
            f"{row.free} / {row.occupied} / {row.booked}"
        )
    if data.totals:
        t = data.totals
        section_occupancy.append(
            f"*Итого:* {t.free} / {t.occupied} / {t.booked} "
            f"(всего {t.total})"
        )
    sections.append("\n".join(section_occupancy))

    section_bookings = [f"*Новые брони:* {data.new_bookings_light} {data.new_bookings_total}"]
    if data.bookings_by_channel:
        for ch in data.bookings_by_channel:
            section_bookings.append(f"- {ch.source} ({ch.channel_type}): {ch.count}")
    else:
        section_bookings.append("- нет данных")
    sections.append("\n".join(section_bookings))

    section_prices = ["*Цены «от» по категориям:*"]
    if data.prices:
        for price in data.prices:
            if price.change_pct is None:
                change_txt = "н/д"
            else:
                sign = "+" if price.change_pct > 0 else ""
                change_txt = f"{sign}{price.change_pct:.1f}%"
            section_prices.append(
                f"{price.traffic_light} {category_short_label(price.category)}: "
                f"{price.price:,.0f} ₽ ({change_txt})".replace(",", " ")
            )
    else:
        section_prices.append("- нет snapshot")
    sections.append("\n".join(section_prices))

    if data.warnings:
        section_notes = ["*Примечания:*"]
        section_notes.extend(f"- {note}" for note in data.warnings)
        sections.append("\n".join(section_notes))

    return sections


def build_daily_summary_text(data: DailySummaryData) -> str:
    """Сформировать Markdown-текст ежедневной сводки (без сети)."""
    return "\n\n".join(build_daily_summary_sections(data))


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
    api: MessageSender | None = None,
) -> dict[str, Any]:
    """Отправить сообщение в Max (POST /messages).

    При dry_run=True — в test_chat_id (реальная отправка, не в основной чат).
    См. https://dev.max.ru/docs-api/methods/POST/messages
    """
    cfg = config or get_config()
    is_dry = cfg.dry_run if dry_run is None else dry_run
    chat_id = _resolve_chat_id(cfg, is_dry)

    if not chat_id:
        logger.warning("chat_id не задан (dry_run=%s)", is_dry)
        return {"status": "skipped", "reason": "no_chat_id", "dry_run": is_dry}

    if api is None and client is None:
        api = build_max_api_client(cfg)
    if api is None and client is None:
        logger.warning("MAX_TOKEN не задан, отправка пропущена")
        return {"status": "skipped", "reason": "no_token", "dry_run": is_dry}

    try:
        if api is not None:
            response = api.send_message(text, chat_id=int(chat_id), format="markdown")
        else:
            url = f"{cfg.max_bot.api_url.rstrip('/')}/messages"
            headers = {"Authorization": get_env_settings().max_token}
            resp = retry_with_backoff(
                lambda: client.post(  # type: ignore[union-attr]
                    url,
                    params={"chat_id": int(chat_id)},
                    json={"text": text, "format": "markdown"},
                    headers=headers,
                    timeout=30.0,
                ),
                retries=cfg.max_bot.max_retries,
                backoff_initial=cfg.max_bot.backoff_initial_sec,
                backoff_max=cfg.max_bot.backoff_max_sec,
                retry_statuses=RETRYABLE_STATUS,
                log_prefix="max_bot",
            )
            response = resp.json()
    except httpx.HTTPError as exc:
        logger.error("Ошибка Max API: %s", exc)
        save_error_log(
            ErrorLogRecord(
                error_date=date.today(),
                source="max_bot",
                error_type="send_message",
                message=str(exc),
            )
        )
        return {
            "status": "error",
            "chat_id": chat_id,
            "dry_run": is_dry,
            "error": str(exc),
        }

    return {
        "status": "sent",
        "chat_id": chat_id,
        "dry_run": is_dry,
        "response": response,
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
    if data.critical_error:
        from src.notifiers.incidents import send_incident

        send_incident(
            "Критическая ошибка источника",
            "\n".join(data.warnings) or "ГуглТабл недоступен.",
            config=cfg,
            source="max_bot",
        )
        save_report_log(
            ReportLogRecord(
                report_type="max",
                report_date=report_date,
                run_date=run_date,
                status="skipped",
                dry_run=cfg.dry_run,
                preview="; ".join(data.warnings)[:200],
                message="critical_error",
            )
        )
        return {
            "status": "skipped",
            "reason": "critical_error",
            "dry_run": cfg.dry_run,
            "warnings": data.warnings,
        }

    sections = build_daily_summary_sections(data)
    text = "\n\n".join(sections)

    if data.warnings:
        from src.notifiers.incidents import send_incident

        send_incident(
            "Неполные данные сводки",
            "\n".join(data.warnings),
            config=cfg,
            source="max_bot",
        )

    results: list[dict[str, Any]] = []
    sent_parts = 0
    for section in sections:
        parts = split_message(section, cfg.max_bot.max_message_length)
        for index, part in enumerate(parts, start=1):
            if len(parts) > 1:
                part = f"[{index}/{len(parts)}]\n{part}"
            results.append(send_message(part, config=cfg, client=client))
            sent_parts += 1

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
        sent_parts,
        cfg.dry_run,
    )
    return {
        "status": status,
        "parts": sent_parts,
        "dry_run": cfg.dry_run,
        "results": results,
        "text": text,
    }
