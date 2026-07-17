"""Накопление metrics_daily из TravelLine для прогноза."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from src.config import AppConfig, get_config
from src.metrics.occupancy import calc_occupancy
from src.metrics.revenue import calc_adr, calc_revpar
from src.storage.db import get_metrics_for_date, save_metrics_daily
from src.storage.models import MetricsDailyRecord
from src.utils.category_labels import room_type_label

logger = logging.getLogger(__name__)

METRIC_DAILY = "daily"
METRIC_CATEGORY_PREFIX = "category:"


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


def collect_metrics_for_date(
    report_date: date,
    config: AppConfig | None = None,
    *,
    force: bool = False,
) -> int:
    """Сохранить дневные метрики объекта и по категориям из TravelLine."""
    cfg = config or get_config()
    if not force and get_metrics_for_date(report_date, METRIC_DAILY):
        return 0

    from src.data_sources.travelline import TravelLineClient, TravelLineError

    try:
        client = TravelLineClient(cfg)
        occ = client.get_stay_occupancy(report_date)
        rev = client.get_revenue(report_date, report_date, date_kind=1)
        channels = client.get_channels(report_date, report_date)
        bookings_count = sum(int(ch.get("count") or 0) for ch in channels)
    except TravelLineError as exc:
        logger.warning("metrics_history: TL недоступен на %s: %s", report_date, exc)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_history: ошибка на %s: %s", report_date, exc)
        return 0

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

    labels = sorted(
        set(occ.by_type) | set(occ.free_by_type) | set(occ.booked_by_type)
    )
    for label in labels:
        slug = tl_label_to_slug(label, cfg)
        if not slug:
            continue
        sold = occ.by_type.get(label, 0) + occ.booked_by_type.get(label, 0)
        available = _units_for_label(label, occ.by_type, occ.free_by_type, occ.booked_by_type)
        if available <= 0:
            continue
        occ_pct = calc_occupancy(sold, available)
        cat_rev = (rev.revenue * sold / occ.sold) if occ.sold > 0 and sold > 0 else 0.0
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

    logger.info("metrics_daily %s: сохранено %s записей", report_date, saved)
    return saved


def backfill_metrics_history(
    days: int = 365,
    end_date: date | None = None,
    *,
    force: bool = False,
    delay_sec: float = 0.15,
    config: AppConfig | None = None,
) -> dict[str, int]:
    """Backfill metrics_daily за N дней из TravelLine."""
    cfg = config or get_config()
    end = end_date or date.today()
    start = end - timedelta(days=max(1, days) - 1)
    stats = {"saved": 0, "skipped": 0, "errors": 0, "days": 0}
    current = start
    while current <= end:
        stats["days"] += 1
        try:
            if not force and get_metrics_for_date(current, METRIC_DAILY):
                stats["skipped"] += 1
            else:
                n = collect_metrics_for_date(current, cfg, force=force)
                if n:
                    stats["saved"] += n
                else:
                    stats["errors"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("backfill %s: %s", current, exc)
            stats["errors"] += 1
        current += timedelta(days=1)
        if delay_sec > 0:
            time.sleep(delay_sec)
    return stats
