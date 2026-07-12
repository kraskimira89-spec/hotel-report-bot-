"""Запросы данных для веб-админки (только агрегаты, без PII)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.data_sources.market_trends import build_market_trends, fetch_competitor_prices
from src.storage.db import (
    compare_metrics_last_week,
    db_session,
    get_guest_stats,
    get_reports_log,
)


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


def fetch_competitors_bundle() -> dict[str, Any]:
    """Данные для страницы «Конкуренты»."""
    from src.web.market_intel import build_competitor_cards, competitor_summary

    period_end = date.today()
    period_start = period_end - timedelta(days=7)
    prices = fetch_competitor_prices(period_start, period_end)
    cards = build_competitor_cards(prices=prices)
    return {
        "cards": cards,
        "summary": competitor_summary(cards),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


def fetch_trends_bundle() -> dict[str, Any]:
    """Данные для страницы «Тренды»."""
    from src.web.market_intel import get_all_trends

    period_end = date.today()
    period_start = period_end - timedelta(days=7)
    prev_start = period_start - timedelta(days=7)
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
        "auto_trends": auto_trends,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "prev_start": prev_start.isoformat(),
        "prev_end": prev_end.isoformat(),
        "aggregates": aggregates,
        **get_all_trends(),
    }
