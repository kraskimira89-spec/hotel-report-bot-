"""Запросы данных для веб-админки (только агрегаты, без PII)."""

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Any

from src.config import get_config
from src.data_sources.market_trends import (
    TREND_CATEGORIES,
    build_market_trends,
    seed_trends_if_empty,
)
from src.storage.db import (
    compare_metrics_last_week,
    db_session,
    get_competitor_prices_history,
    get_competitor_prices_latest,
    get_guest_stats,
    get_price_snapshots_by_date,
    get_reports_log,
    get_trend_idea_of_week,
    get_trends_records,
)
from src.web.market_intel import build_competitor_cards


def fetch_latest_metrics() -> dict[str, Any] | None:
    """Последние сохранённые метрики."""
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT * FROM metrics_daily
            ORDER BY report_date DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_metrics_comparison() -> dict[str, Any] | None:
    """Сравнение метрик с прошлой неделей."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT report_date FROM metrics_daily ORDER BY report_date DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    ref_date = date.fromisoformat(row["report_date"][:10])
    cmp = compare_metrics_last_week(ref_date)
    cur = cmp.reference_metrics
    prev = cmp.metrics
    if cur is None:
        return None
    return {
        "report_date": ref_date.isoformat(),
        "occupancy_pct": cur.occupancy_pct,
        "adr": cur.adr,
        "revpar": cur.revpar,
        "als": cur.als,
        "revenue": cur.revenue,
        "is_estimated": cur.is_estimated,
        "prev_occupancy_pct": prev.occupancy_pct if prev else None,
        "prev_adr": prev.adr if prev else None,
        "prev_revpar": prev.revpar if prev else None,
    }


def fetch_last_reports() -> dict[str, dict[str, Any] | None]:
    """Статус последних отправок Max и email."""
    reports = get_reports_log(limit=20)
    last_max = next((r for r in reports if r.report_type == "max"), None)
    last_email = next((r for r in reports if r.report_type == "email"), None)

    def _to_dict(item: Any) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "id": item.id,
            "status": item.status,
            "report_date": item.report_date.isoformat(),
            "dry_run": item.dry_run,
            "preview": (item.preview or "")[:120],
        }

    return {"max": _to_dict(last_max), "email": _to_dict(last_email)}


def fetch_dashboard_data() -> dict[str, Any]:
    """Сводка для дашборда."""
    latest = fetch_latest_metrics()
    comparison = fetch_metrics_comparison()
    last_reports = fetch_last_reports()
    guest_stats = get_guest_stats()

    snapshot_count = 0
    booking_count = 0
    with db_session() as conn:
        snapshot_count = conn.execute(
            "SELECT COUNT(*) AS c FROM price_snapshots"
        ).fetchone()["c"]
        booking_count = conn.execute(
            "SELECT COUNT(*) AS c FROM bookings_daily"
        ).fetchone()["c"]

    return {
        "latest_metrics": latest,
        "comparison": comparison,
        "last_reports": last_reports,
        "guest_stats": guest_stats,
        "snapshot_count": snapshot_count,
        "booking_count": booking_count,
    }


def fetch_snapshot_rows(limit: int = 200) -> list[dict[str, Any]]:
    """История snapshot цен."""
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT snapshot_date, category, price, source, is_estimated, is_fallback
            FROM price_snapshots
            ORDER BY snapshot_date DESC, category
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_snapshot_chart() -> list[dict[str, Any]]:
    """Данные для графика цен по категориям (последние 14 дней)."""
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT snapshot_date, category, AVG(price) AS avg_price
            FROM price_snapshots
            GROUP BY snapshot_date, category
            ORDER BY snapshot_date DESC
            LIMIT 84
            """
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_metrics_rows(days: int = 90) -> list[dict[str, Any]]:
    """Метрики по дням."""
    start = date.today() - timedelta(days=days)
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM metrics_daily
            WHERE report_date >= ?
            ORDER BY report_date DESC
            """,
            (start.isoformat(),),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_weekly_metrics() -> list[dict[str, Any]]:
    """Средние метрики по неделям (агрегат)."""
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-W%W', report_date) AS week,
                ROUND(AVG(occupancy_pct), 1) AS occupancy_pct,
                ROUND(AVG(adr), 0) AS adr,
                ROUND(AVG(revpar), 0) AS revpar,
                ROUND(AVG(als), 2) AS als,
                ROUND(SUM(revenue), 0) AS revenue,
                MAX(is_estimated) AS is_estimated
            FROM metrics_daily
            GROUP BY week
            ORDER BY week DESC
            LIMIT 12
            """
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_channel_aggregates(days: int = 30) -> dict[str, Any]:
    """Агрегаты бронирований по каналам (без PII)."""
    start = (date.today() - timedelta(days=days)).isoformat()
    with db_session() as conn:
        by_channel = conn.execute(
            """
            SELECT channel, COUNT(*) AS bookings_count
            FROM bookings_daily
            WHERE created_date >= ?
            GROUP BY channel
            ORDER BY bookings_count DESC
            """,
            (start,),
        ).fetchall()
        by_day = conn.execute(
            """
            SELECT created_date, channel, COUNT(*) AS bookings_count
            FROM bookings_daily
            WHERE created_date >= ?
            GROUP BY created_date, channel
            ORDER BY created_date DESC
            LIMIT 100
            """,
            (start,),
        ).fetchall()

    direct = 0
    aggregator = 0
    other = 0
    for row in by_channel:
        channel = (row["channel"] or "").lower()
        count = int(row["bookings_count"])
        if channel == "direct":
            direct += count
        elif channel == "aggregator":
            aggregator += count
        else:
            other += count

    total = direct + aggregator + other
    guest_stats = get_guest_stats()
    returning_pct = (
        round(guest_stats["returning"] / guest_stats["total"] * 100, 1)
        if guest_stats["total"]
        else None
    )

    return {
        "by_channel": [dict(r) for r in by_channel],
        "by_day": [dict(r) for r in by_day],
        "direct": direct,
        "aggregator": aggregator,
        "other": other,
        "total": total,
        "direct_pct": round(direct / total * 100, 1) if total else 0,
        "aggregator_pct": round(aggregator / total * 100, 1) if total else 0,
        "guest_stats": guest_stats,
        "returning_pct": returning_pct,
    }


def fetch_logs_bundle(limit: int = 100) -> dict[str, list[dict[str, Any]]]:
    """Запуски отчётов, ошибки и расхождения."""
    reports = get_reports_log(limit=limit)
    with db_session() as conn:
        errors = conn.execute(
            """
            SELECT * FROM errors_log
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    reconcile = [
        dict(e)
        for e in errors
        if e["error_type"] == "sheets_reconcile"
    ]
    other_errors = [
        dict(e)
        for e in errors
        if e["error_type"] != "sheets_reconcile"
    ]
    return {
        "reports": [
            {
                "id": r.id,
                "created_at": r.run_date.isoformat(),
                "report_type": r.report_type,
                "status": r.status,
                "dry_run": r.dry_run,
                "message": (r.message or "")[:200],
            }
            for r in reports
        ],
        "errors": other_errors,
        "reconcile": reconcile,
    }


def _our_latest_prices() -> dict[str, float]:
    """Последние цены 1apart по категориям."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT MAX(snapshot_date) AS d FROM price_snapshots"
        ).fetchone()
    if row is None or not row["d"]:
        return {}
    snap_date = date.fromisoformat(row["d"][:10])
    snapshots = get_price_snapshots_by_date(snap_date)
    return {s.category: s.price for s in snapshots}


def _price_status(record_date: date | None, available: bool) -> tuple[str, str]:
    """Статус сбора: emoji + label."""
    if not available or record_date is None:
        return "🔴", "недоступно"
    if record_date >= date.today():
        return "🟢", "собрано"
    return "🟡", "из кэша"


def get_competitor_latest() -> list[dict[str, Any]]:
    """Последняя запись по каждому конкуренту из config + БД."""
    cfg = get_config()
    db_latest = {r.competitor_name: r for r in get_competitor_prices_latest()}
    our_prices = _our_latest_prices()
    rows: list[dict[str, Any]] = []

    for comp in cfg.competitors:
        rec = db_latest.get(comp.name)
        mapped_slug = cfg.competitor_category_map.get(comp.name)
        our_price = our_prices.get(mapped_slug) if mapped_slug else None
        price = rec.price_from if rec else None
        available = rec.available if rec else False
        rec_date = rec.date if rec else None
        emoji, status_label = _price_status(rec_date, available and price is not None)

        delta_pct: float | None = None
        if price is not None and our_price is not None and our_price > 0:
            delta_pct = round((price - our_price) / our_price * 100, 1)

        rows.append(
            {
                "name": comp.name,
                "type": comp.type,
                "type_label": "прямой" if comp.type == "direct" else "косвенный",
                "parser": comp.parser,
                "url": comp.url,
                "price_from": price,
                "our_category_slug": mapped_slug,
                "our_price": our_price,
                "delta_pct": delta_pct,
                "updated_at": rec_date.isoformat() if rec_date else None,
                "status_emoji": emoji,
                "status_label": status_label,
                "source": rec.source if rec else comp.parser,
                "screenshot_path": rec.screenshot_path if rec else None,
                "available": available and price is not None,
            }
        )
    return rows


def get_competitor_history(name: str, days: int = 90) -> list[dict[str, Any]]:
    """История цен конкурента."""
    records = get_competitor_prices_history(name, days=days)
    return [
        {
            "date": r.date.isoformat(),
            "price_from": r.price_from,
            "available": r.available,
            "source": r.source,
            "screenshot_path": r.screenshot_path,
        }
        for r in records
    ]


def _market_vs_block(rows: list[dict[str, Any]], comp_type: str) -> dict[str, Any]:
    """Сводка «Мы vs рынок» для direct/indirect."""
    cfg = get_config()
    our_prices = _our_latest_prices()
    our_avg = round(mean(our_prices.values()), 0) if our_prices else None

    typed = [r for r in rows if r["type"] == comp_type and r.get("price_from")]
    market_avg = round(mean(r["price_from"] for r in typed), 0) if typed else None

    position: str | None = None
    position_pct: float | None = None
    if our_avg is not None and market_avg is not None and market_avg > 0:
        position_pct = round((our_avg - market_avg) / market_avg * 100, 1)
        if position_pct > 3:
            position = "выше рынка"
        elif position_pct < -3:
            position = "ниже рынка"
        else:
            position = "в рынке"

    names = [c.name for c in cfg.competitors if c.type == comp_type]
    return {
        "type": comp_type,
        "type_label": "прямые" if comp_type == "direct" else "косвенные",
        "competitor_names": names,
        "market_avg": market_avg,
        "our_avg": our_avg,
        "position": position,
        "position_pct": position_pct,
        "with_price_count": len(typed),
        "total_count": len(names),
    }


def fetch_competitors_bundle() -> dict[str, Any]:
    """Данные для страницы «Конкуренты»."""
    cfg = get_config()
    overview = get_competitor_latest()
    cards = build_competitor_cards()

    details: dict[str, dict[str, Any]] = {}
    for row in overview:
        history = get_competitor_history(row["name"], days=90)
        slug = row.get("our_category_slug")
        details[row["name"]] = {
            "history": history,
            "category_slug": slug,
            "category_label": slug or "—",
            "sparkline": [
                h["price_from"] for h in reversed(history) if h.get("price_from")
            ],
        }

    return {
        "overview": overview,
        "details": details,
        "cards": cards,
        "market_direct": _market_vs_block(overview, "direct"),
        "market_indirect": _market_vs_block(overview, "indirect"),
        "category_map": cfg.competitor_category_map,
        "our_categories": cfg.site_prices.category_urls,
    }


def get_trends(
    region: str | None,
    category: str | None,
    days: int,
) -> list[dict[str, Any]]:
    """Тренды из БД с фильтрами."""
    seed_trends_if_empty()
    records = get_trends_records(region=region, category=category, days=days)
    return [
        {
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "category": r.category,
            "region": r.region,
            "region_label": "🇷🇺 Россия" if r.region == "ru" else "🌍 Мир",
            "source_url": r.source_url,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "takeaway": r.takeaway,
            "is_idea_of_week": r.is_idea_of_week,
        }
        for r in records
    ]


def get_idea_of_week() -> dict[str, Any] | None:
    """Идея недели из БД."""
    seed_trends_if_empty()
    record = get_trend_idea_of_week()
    if record is None:
        return None
    return {
        "title": record.title,
        "summary": record.summary,
        "category": record.category,
        "region": record.region,
        "region_label": "🇷🇺 Россия" if record.region == "ru" else "🌍 Мир",
        "source_url": record.source_url,
        "published_at": record.published_at.isoformat() if record.published_at else None,
        "takeaway": record.takeaway,
    }


def fetch_trends_bundle(
    region: str | None = None,
    category: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Данные для страницы «Тренды»."""
    period_end = date.today()
    period_start = period_end - timedelta(days=days)
    prev_start = period_start - timedelta(days=days)
    prev_end = period_start

    aggregates = fetch_channel_aggregates(days=30)
    metrics_rows = fetch_metrics_rows(days=14)
    occupancy_vals = [
        r["occupancy_pct"] for r in metrics_rows if r.get("occupancy_pct") is not None
    ]
    cur_occ = sum(occupancy_vals[:7]) / min(7, len(occupancy_vals)) if occupancy_vals else None
    prev_occ = (
        sum(occupancy_vals[7:14]) / min(7, len(occupancy_vals[7:14]))
        if len(occupancy_vals) > 7
        else None
    )

    auto_trends = build_market_trends(
        period_start,
        period_end,
        occupancy_pct=cur_occ,
        prev_occupancy_pct=prev_occ,
        direct_share_pct=aggregates.get("direct_pct"),
        returning_share_pct=aggregates.get("returning_pct"),
    )

    return {
        "trends": get_trends(region, category, days),
        "idea_of_week": get_idea_of_week(),
        "auto_trends": auto_trends,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "prev_start": prev_start.isoformat(),
        "prev_end": prev_end.isoformat(),
        "aggregates": aggregates,
        "categories": TREND_CATEGORIES,
        "filters": {
            "region": region or "",
            "category": category or "",
            "days": days,
        },
    }
