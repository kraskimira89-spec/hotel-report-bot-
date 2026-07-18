"""Накопление metrics_daily из TravelLine для прогноза."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Literal, NamedTuple

from src.config import AppConfig, get_config
from src.metrics.occupancy import calc_occupancy
from src.metrics.revenue import calc_adr, calc_revpar
from src.storage.db import (
    count_category_metrics_for_date,
    get_metrics_for_date,
    resolve_errors_log,
    save_metrics_daily,
)
from src.storage.models import MetricsDailyRecord
from src.utils.category_labels import room_type_label

logger = logging.getLogger(__name__)

METRIC_DAILY = "daily"
METRIC_CATEGORY_PREFIX = "category:"

CollectKind = Literal["full", "categories", "daily_only", "skipped", "error"]


class CollectOutcome(NamedTuple):
    saved: int
    kind: CollectKind


def category_metric_type(slug: str) -> str:
    return f"{METRIC_CATEGORY_PREFIX}{slug}"


def tl_label_to_slug(label: str, config: AppConfig | None = None) -> str | None:
    """Сопоставить подпись TravelLine со slug категории сайта."""
    cfg = config or get_config()
    normalized = room_type_label(label, cfg.room_type_aliases)
    for slug, name in cfg.category_slug_map.items():
        if name == normalized or name in normalized or normalized in name:
            return slug
    for slug in cfg.site_prices.category_urls or []:
        if category_metric_type(slug) and slug in label.lower().replace(" ", ""):
            return slug
    return None


def expected_category_slugs(config: AppConfig | None = None) -> list[str]:
    cfg = config or get_config()
    slugs = list(cfg.category_slug_map.keys())
    if slugs:
        return slugs
    return list((cfg.site_prices.category_urls or {}).keys())


def needs_category_fill(report_date: date, config: AppConfig | None = None) -> bool:
    """True, если по дате нет категорий или их меньше ожидаемого числа slug'ов."""
    cfg = config or get_config()
    present = count_category_metrics_for_date(report_date)
    expected = len(expected_category_slugs(cfg))
    if expected <= 0:
        return present == 0
    return present < expected


def _units_for_label(
    label: str,
    occ_by: dict[str, int],
    free_by: dict[str, int],
    book_by: dict[str, int],
) -> int:
    return (
        occ_by.get(label, 0)
        + free_by.get(label, 0)
        + book_by.get(label, 0)
    )


def _save_category_rows(
    report_date: date,
    cfg: AppConfig,
    occ: object,
    rev: object,
) -> int:
    """Записать category:* из StayOccupancyResult + revenue. Возвращает число записей."""
    saved = 0
    labels = sorted(
        set(occ.by_type) | set(occ.free_by_type) | set(occ.booked_by_type)  # type: ignore[attr-defined]
    )
    sold_total = getattr(occ, "sold", 0) or 0
    revenue = getattr(rev, "revenue", 0.0) or 0.0
    for label in labels:
        slug = tl_label_to_slug(label, cfg)
        if not slug:
            continue
        sold = occ.by_type.get(label, 0) + occ.booked_by_type.get(label, 0)  # type: ignore[attr-defined]
        available = _units_for_label(
            label, occ.by_type, occ.free_by_type, occ.booked_by_type  # type: ignore[attr-defined]
        )
        if available <= 0:
            continue
        occ_pct = calc_occupancy(sold, available)
        cat_rev = (revenue * sold / sold_total) if sold_total > 0 and sold > 0 else 0.0
        save_metrics_daily(
            MetricsDailyRecord(
                report_date=report_date,
                metric_type=category_metric_type(slug),
                occupancy_pct=occ_pct,
                adr=calc_adr(cat_rev, sold),
                revpar=calc_revpar(cat_rev, available),
                revenue=round(cat_rev, 2),
                bookings_count=None,
                is_estimated=True,
            )
        )
        saved += 1
    return saved


def _resolve_tl_errors_after_success(report_date: date) -> None:
    """Снять http_error за день отчёта и за сегодня (дата лога при backfill старых дней)."""
    try:
        total = 0
        for d in {report_date, date.today()}:
            total += resolve_errors_log(
                source="travelline",
                error_type="http_error",
                error_date=d,
            )
        if total:
            logger.info(
                "metrics_history: resolved %s travelline/http_error (report=%s)",
                total,
                report_date,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_errors_log: %s", exc)


def collect_metrics_for_date(
    report_date: date,
    config: AppConfig | None = None,
    *,
    force: bool = False,
    daily_only: bool = False,
    fill_categories: bool = True,
) -> CollectOutcome:
    """Сохранить дневные метрики объекта и по категориям из TravelLine.

    ``daily_only=True`` — быстрый режим: только metric_type=daily.
    ``fill_categories=True`` — если daily уже есть, но категорий мало/нет,
    дописать только category:* без перезаписи daily.
    """
    cfg = config or get_config()
    has_daily = get_metrics_for_date(report_date, METRIC_DAILY) is not None
    need_cats = (not daily_only) and fill_categories and needs_category_fill(
        report_date, cfg
    )

    if daily_only:
        if has_daily and not force:
            return CollectOutcome(0, "skipped")
    elif has_daily and not force and not need_cats:
        return CollectOutcome(0, "skipped")

    categories_only = (
        not daily_only and has_daily and not force and need_cats
    )

    from src.data_sources.travelline import TravelLineClient, TravelLineError

    try:
        client = TravelLineClient(cfg)
        if daily_only:
            occ = client.get_stay_occupancy_summary(report_date)
            rev = client.get_revenue(report_date, report_date, date_kind=1)
            bookings_count = None
        else:
            occ = client.get_stay_occupancy(report_date)
            rev = client.get_revenue(report_date, report_date, date_kind=1)
            channels = client.get_channels(report_date, report_date)
            bookings_count = sum(int(ch.get("count") or 0) for ch in channels)
    except TravelLineError as exc:
        logger.warning("metrics_history: TL недоступен на %s: %s", report_date, exc)
        return CollectOutcome(0, "error")
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_history: ошибка на %s: %s", report_date, exc)
        return CollectOutcome(0, "error")

    saved = 0
    if not categories_only:
        adr = calc_adr(rev.revenue, occ.sold)
        revpar = calc_revpar(rev.revenue, occ.available)
        save_metrics_daily(
            MetricsDailyRecord(
                report_date=report_date,
                metric_type=METRIC_DAILY,
                occupancy_pct=occ.occupancy_pct,
                adr=adr,
                revpar=revpar,
                revenue=rev.revenue,
                bookings_count=bookings_count,
                is_estimated=rev.is_estimated,
            )
        )
        saved = 1

    if daily_only:
        logger.info("metrics_daily %s: fast daily-only, 1 запись", report_date)
        _resolve_tl_errors_after_success(report_date)
        return CollectOutcome(saved, "daily_only")

    cat_n = _save_category_rows(report_date, cfg, occ, rev)
    saved += cat_n
    kind: CollectKind = "categories" if categories_only else "full"
    logger.info(
        "metrics_daily %s: сохранено %s записей (mode=%s, categories=%s)",
        report_date,
        saved,
        kind,
        cat_n,
    )
    if saved > 0:
        _resolve_tl_errors_after_success(report_date)
    return CollectOutcome(saved, kind)


def backfill_metrics_history(
    days: int = 365,
    end_date: date | None = None,
    *,
    force: bool = False,
    delay_sec: float = 0.15,
    daily_only: bool = False,
    fill_categories: bool = True,
    config: AppConfig | None = None,
) -> dict[str, int]:
    """Backfill metrics_daily за N дней из TravelLine."""
    cfg = config or get_config()
    end = end_date or date.today()
    start = end - timedelta(days=max(1, days) - 1)
    stats = {
        "saved": 0,
        "skipped": 0,
        "errors": 0,
        "days": 0,
        "filled_categories": 0,
    }
    current = start
    while current <= end:
        stats["days"] += 1
        try:
            outcome = collect_metrics_for_date(
                current,
                cfg,
                force=force,
                daily_only=daily_only,
                fill_categories=fill_categories and not daily_only,
            )
            if outcome.kind == "skipped":
                stats["skipped"] += 1
            elif outcome.kind == "error":
                stats["errors"] += 1
            elif outcome.kind == "categories":
                if outcome.saved > 0:
                    stats["filled_categories"] += 1
                    stats["saved"] += outcome.saved
                else:
                    stats["errors"] += 1
            else:
                stats["saved"] += outcome.saved
                if outcome.saved == 0:
                    stats["errors"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("backfill %s: %s", current, exc)
            stats["errors"] += 1
        current += timedelta(days=1)
        if delay_sec > 0:
            time.sleep(delay_sec)
    return stats
