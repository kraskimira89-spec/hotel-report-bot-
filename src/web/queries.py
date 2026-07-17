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
    get_competitor_category_prices,
    get_competitor_prices_history,
    get_competitor_prices_latest,
    get_guest_stats,
    get_insights_records,
    get_metrics_daily,
    get_price_snapshots_by_date,
    get_reports_log,
    get_trend_idea_of_week,
    get_trends_records,
    insights_count,
)
from src.web.market_intel import build_competitor_cards
from src.utils.category_labels import category_label
from src.utils.dates import format_date_ru, format_period_label, format_period_ru
from src.utils.metric_labels import expand_metric_abbrs, expand_metric_abbrs_list


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
        "report_date": format_date_ru(ref_date),
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
            "report_date": format_date_ru(item.report_date),
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
    """История снимков цен с русскими названиями категорий."""
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
    slug_map = get_config().category_slug_map
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        item["category_label"] = category_label(str(item.get("category") or ""), slug_map)
        item["snapshot_date"] = format_date_ru(item.get("snapshot_date"))
        out.append(item)
    return out


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
    slug_map = get_config().category_slug_map
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        label = category_label(str(item.get("category") or ""), slug_map)
        item["category_label"] = label
        item["category_short"] = (label[:9] + "…") if len(label) > 10 else label
        item["snapshot_date"] = format_date_ru(item.get("snapshot_date"))
        out.append(item)
    return out


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
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        item["report_date"] = format_date_ru(item.get("report_date"))
        out.append(item)
    return out


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
                "created_at": format_date_ru(r.run_date),
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


def _price_status(
    record_date: date | None,
    available: bool,
    price_kind: str | None = None,
) -> tuple[str, str]:
    """Статус сбора: emoji + label."""
    if not available or record_date is None:
        return "🔴", "недоступно"
    kind = price_kind or "dynamic"
    if kind == "cached":
        return "🟡", "цена из кэша"
    if kind == "public_from":
        return "🟠", "базовая цена «от», не по дате"
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
        price_kind = rec.price_kind if rec else None
        emoji, status_label = _price_status(
            rec_date, available and price is not None, price_kind
        )

        delta_pct: float | None = None
        market_position: str | None = None
        if price is not None and our_price is not None and our_price > 0:
            delta_pct = round((price - our_price) / our_price * 100, 1)
            our_vs_comp = round((our_price / price - 1) * 100, 1)
            threshold = 10.0
            if our_vs_comp > threshold:
                market_position = "above"
            elif our_vs_comp < -threshold:
                market_position = "below"
            else:
                market_position = "in_market"

        rows.append(
            {
                "name": comp.name,
                "type": comp.type,
                "type_label": "прямой" if comp.type == "direct" else "косвенный",
                "parser": comp.parser,
                "url": comp.url,
                "price_from": price,
                "price_kind": price_kind,
                "booking_engine": rec.booking_engine if rec else None,
                "our_category_slug": mapped_slug,
                "our_price": our_price,
                "delta_pct": delta_pct,
                "market_position": market_position,
                "updated_at": format_date_ru(rec_date) if rec_date else None,
                "status_emoji": emoji,
                "status_label": status_label,
                "source": rec.source if rec else comp.parser,
                "screenshot_path": rec.screenshot_path if rec else None,
                "raw_url": rec.raw_url if rec else None,
                "available": available and price is not None,
            }
        )
    return rows


def get_competitor_history(name: str, days: int = 90) -> list[dict[str, Any]]:
    """История цен конкурента."""
    records = get_competitor_prices_history(name, days=days)
    return [
        {
            "date": format_date_ru(r.date),
            "price_from": r.price_from,
            "available": r.available,
            "source": r.source,
            "price_kind": r.price_kind,
            "screenshot_path": r.screenshot_path,
        }
        for r in records
    ]


def _demand_signal(history: list[dict[str, Any]]) -> str:
    """Индикатор спроса по недельной динамике цены (Xander / премиум)."""
    prices = [h["price_from"] for h in history if h.get("price_from")]
    if len(prices) < 2:
        return "нет данных"
    latest = prices[0]
    week_ago = prices[min(7, len(prices) - 1)]
    if week_ago and latest >= week_ago * 1.2:
        return "высокий"
    return "обычный"


def _build_featured_competitor(
    name: str,
    overview: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
    *,
    role: str,
) -> dict[str, Any] | None:
    row = next((r for r in overview if r["name"] == name), None)
    if row is None:
        return None
    det = details.get(name, {})
    our_price = row.get("our_price")
    comp_price = row.get("price_from")
    premium_index: float | None = None
    if comp_price and our_price and our_price > 0:
        premium_index = round(float(comp_price) / float(our_price), 2)
    history_30 = get_competitor_history(name, days=30)
    return {
        **row,
        "role": role,
        "products": det.get("products", []),
        "history_30": history_30,
        "premium_index": premium_index,
        "demand_signal": _demand_signal(history_30) if role == "premium" else None,
    }


def _market_vs_block(rows: list[dict[str, Any]], comp_type: str) -> dict[str, Any]:
    """Сводка «Мы vs рынок» для direct/indirect.

    Сравниваем только пары «конкурент ↔ наша категория» из competitor_category_map.
    """
    cfg = get_config()
    our_prices = _our_latest_prices()

    typed = [r for r in rows if r["type"] == comp_type and r.get("price_from")]
    market_avg = round(mean(r["price_from"] for r in typed), 0) if typed else None

    comparable_ours: list[float] = []
    for row in typed:
        our_price = row.get("our_price")
        if our_price is not None:
            comparable_ours.append(float(our_price))
    if not comparable_ours and our_prices:
        # Фолбэк: средняя по всем нашим категориям, если карта пуста.
        comparable_ours = list(our_prices.values())
    our_avg = round(mean(comparable_ours), 0) if comparable_ours else None

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
        our_label = (
            cfg.category_slug_map.get(slug, slug) if slug else None
        )
        products = get_competitor_category_prices(row["name"])
        details[row["name"]] = {
            "history": history,
            "category_slug": slug,
            "category_label": our_label or slug or "—",
            "our_price": row.get("our_price"),
            "products": [
                {
                    "name": p.category,
                    "price_from": p.price_from,
                }
                for p in products
            ],
            "sparkline": [
                h["price_from"] for h in reversed(history) if h.get("price_from")
            ],
        }

    return {
        "overview": overview,
        "details": details,
        "cards": cards,
        "featured": {
            "central": _build_featured_competitor(
                "Центральный", overview, details, role="direct"
            ),
            "xander": _build_featured_competitor(
                "Xander Hotel", overview, details, role="premium"
            ),
        },
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
        "period_start": format_date_ru(period_start),
        "period_end": format_date_ru(period_end),
        "prev_start": format_date_ru(prev_start),
        "prev_end": format_date_ru(prev_end),
        "aggregates": aggregates,
        "categories": TREND_CATEGORIES,
        "filters": {
            "region": region or "",
            "category": category or "",
            "days": days,
        },
    }


_SEVERITY_RANK = {"action": 0, "attention": 1, "info": 2}

_TOPIC_LABELS = {
    "occupancy": "Загрузка и динамика",
    "revenue": "Доход / ADR (средняя цена) / RevPAR (доход на номер)",
    "channels": "Каналы продаж",
    "returning_guests": "Повторные гости",
    "cancellations": "Отмены",
    "als": "Средний срок проживания",
    "competitors": "Конкуренты",
    "market_trends": "Тренды рынка",
    "regional_demand": "Спрос в регионе",
    "regulation": "Регулирование",
}


def _localize_detail_dates(payload: dict[str, Any]) -> dict[str, Any]:
    """Даты в detail_payload → ДД.ММ.ГГГГ (series / sources)."""
    if not payload:
        return {}
    out = dict(payload)
    series = out.get("series")
    if isinstance(series, list):
        fixed = []
        for point in series:
            if isinstance(point, dict) and "date" in point:
                item = dict(point)
                item["date"] = format_date_ru(item.get("date"))
                fixed.append(item)
            else:
                fixed.append(point)
        out["series"] = fixed
    sources = out.get("sources")
    if isinstance(sources, list):
        fixed_src = []
        for src in sources:
            if isinstance(src, dict) and src.get("date"):
                item = dict(src)
                item["date"] = format_date_ru(item.get("date"))
                fixed_src.append(item)
            else:
                fixed_src.append(src)
        out["sources"] = fixed_src
    return out


def get_insights(
    source: str | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    """Карточки аналитики с сортировкой action → attention → info."""
    records = get_insights_records(source=source, topic=topic)
    rows: list[dict[str, Any]] = []
    for r in records:
        rows.append(
            {
                "id": r.id,
                "topic": r.topic,
                "topic_label": _TOPIC_LABELS.get(r.topic, r.topic),
                "title": expand_metric_abbrs(r.title),
                "summary": expand_metric_abbrs(r.summary),
                "recommendations": expand_metric_abbrs_list(r.recommendations),
                "severity": r.severity,
                "source": r.source,
                "source_label": {
                    "travelline": "TravelLine",
                    "web": "Интернет",
                    "mixed": "Смешанный",
                }.get(r.source, r.source),
                "period": format_period_label(r.period),
                "detail_payload": _localize_detail_dates(r.detail_payload or {}),
                "updated_at": (
                    r.updated_at.strftime("%d.%m.%Y %H:%M") if r.updated_at else ""
                ),
            }
        )
    rows.sort(
        key=lambda x: (
            _SEVERITY_RANK.get(x["severity"], 9),
            x["updated_at"] or "",
        )
    )
    return rows


def get_top_insights(limit: int = 2) -> list[dict[str, Any]]:
    """Главное сегодня — карточки с severity=action, иначе первые по приоритету."""
    all_cards = get_insights()
    action = [c for c in all_cards if c["severity"] == "action"]
    if action:
        return action[:limit]
    return all_cards[:limit]


# Пресеты периода аналитики (дней).
ANALYTICS_PERIOD_OPTIONS: list[dict[str, Any]] = [
    {"days": 7, "label": "7 дней"},
    {"days": 14, "label": "2 недели"},
    {"days": 30, "label": "30 дней"},
    {"days": 60, "label": "60 дней"},
    {"days": 90, "label": "90 дней"},
]


def normalize_period_days(value: int | str | None, default: int = 14) -> int:
    """Нормализовать период: 1…365 дней, по умолчанию 14."""
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"", "custom", "none"}:
        return default
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(days, 365))


def fetch_analytics_bundle(
    source: str | None = None,
    topic: str | None = None,
    period_days: int | None = None,
) -> dict[str, Any]:
    """Данные для страницы «Аналитика»."""
    if source == "all":
        source = None
    if not topic:
        topic = None
    days = normalize_period_days(period_days, default=14)
    if insights_count() == 0:
        from src.analytics.ai_insights import run_insights_refresh

        run_insights_refresh(period_days=days)
    cards = get_insights(source=source, topic=topic)
    preset_days = {o["days"] for o in ANALYTICS_PERIOD_OPTIONS}
    return {
        "top": get_top_insights(2),
        "cards": cards,
        "topics": [{"id": k, "label": v} for k, v in _TOPIC_LABELS.items()],
        "period_options": ANALYTICS_PERIOD_OPTIONS,
        "filters": {
            "source": source or "all",
            "topic": topic or "",
            "period_days": days,
            "period_is_custom": days not in preset_days,
        },
        "count": len(cards),
    }


FORECAST_HORIZON_OPTIONS = [
    {"days": 7, "label": "7 дней"},
    {"days": 14, "label": "14 дней"},
    {"days": 30, "label": "Месяц"},
    {"days": 180, "label": "Полгода"},
]

_SCENARIO_LABELS = {
    "conservative": "Консервативный",
    "base": "Базовый",
    "optimistic": "Оптимистичный",
}

_CONFIDENCE_LABELS = {
    "high": "Высокий",
    "medium": "Средний",
    "low": "Низкий",
}

_RECO_TYPE_LABELS = {
    "increase": "Повысить",
    "hold": "Оставить",
    "decrease": "Снизить",
    "restrict_discounts": "Ограничить скидки",
    "manual_review": "Ручная проверка",
}


def _room_type_label(slug: str) -> str:
    if not slug:
        return "Весь объект"
    cfg = get_config()
    return cfg.category_slug_map.get(slug, slug)


def fetch_forecast_bundle(
    horizon_days: int = 7,
    scenario: str = "base",
    room_type: str | None = None,
    include_events: bool = True,
) -> dict[str, Any]:
    """Данные для страницы «Прогноз»."""
    from src.forecast.quality import calc_forecast_errors, should_warn_quality
    from src.forecast.service import run_forecast_refresh
    from src.storage.db import (
        get_competitor_prices_latest,
        get_forecast_daily,
        get_latest_forecast_run,
        get_price_recommendations,
    )

    cfg = get_config()
    valid_horizons = {o["days"] for o in FORECAST_HORIZON_OPTIONS}
    horizon = horizon_days if horizon_days in valid_horizons else 7
    if scenario not in _SCENARIO_LABELS:
        scenario = "base"

    run = get_latest_forecast_run(horizon)
    if run is None and cfg.forecast.enabled:
        run_forecast_refresh(horizons=[horizon])
        run = get_latest_forecast_run(horizon)

    rt_filter = room_type if room_type else ""
    series: list[dict[str, Any]] = []
    approved_events: list = []
    events_by_date: dict[str, list[dict]] = {}
    kpi = {
        "occupancy_pct": None,
        "adr": None,
        "revpar": None,
        "revenue": None,
        "confidence": "medium",
        "data_quality": run.data_quality if run else "unknown",
    }
    factors_sample: dict = {}
    if run and run.id:
        rows = get_forecast_daily(run.id, scenario=scenario, room_type=rt_filter)
        if include_events and cfg.events.enabled:
            from src.events.impact import impact_level
            from src.events.service import events_for_forecast

            end_d = date.today() + timedelta(days=horizon)
            approved_events = events_for_forecast(date.today(), end_d)
            for ev in approved_events:
                d = ev.start_at
                while d <= (ev.end_at or ev.start_at):
                    if d > end_d:
                        break
                    key = d.isoformat()
                    events_by_date.setdefault(key, []).append(
                        {
                            "title": ev.title,
                            "impact_score": ev.impact_score,
                            "level": impact_level(ev.impact_score),
                            "category": ev.category,
                        }
                    )
                    d += timedelta(days=1)
        if rows:
            occ_vals = [r.occupancy_pct for r in rows if r.occupancy_pct is not None]
            rev_vals = [r.revenue for r in rows if r.revenue is not None]
            adr_vals = [r.adr for r in rows if r.adr is not None]
            revpar_vals = [r.revpar for r in rows if r.revpar is not None]
            kpi["occupancy_pct"] = round(sum(occ_vals) / len(occ_vals), 1) if occ_vals else None
            kpi["revenue"] = round(sum(rev_vals), 0) if rev_vals else None
            kpi["adr"] = round(sum(adr_vals) / len(adr_vals), 0) if adr_vals else None
            kpi["revpar"] = round(sum(revpar_vals) / len(revpar_vals), 0) if revpar_vals else None
            confidences = [r.confidence for r in rows]
            if confidences:
                kpi["confidence"] = min(
                    confidences,
                    key=lambda c: {"high": 3, "medium": 2, "low": 1}.get(c, 2),
                )
            factors_sample = rows[0].factors_json or {}
        for r in rows:
            day_events = events_by_date.get(r.forecast_date.isoformat(), [])
            series.append(
                {
                    "date": r.forecast_date.isoformat(),
                    "date_label": r.forecast_date.strftime("%d.%m"),
                    "occupancy": r.occupancy_pct,
                    "lower": r.lower_bound,
                    "upper": r.upper_bound,
                    "actual": r.actual_occupancy_pct,
                    "booked_hint": r.sold_unit_nights,
                    "events": day_events,
                }
            )

    recs_raw = get_price_recommendations(
        status=None,
        room_type=room_type or None,
        horizon_days=horizon,
        limit=100,
    )
    recs = []
    for r in recs_raw:
        if r.target_date < date.today():
            continue
        recs.append(
            {
                "id": r.id,
                "room_type": r.room_type,
                "room_label": _room_type_label(r.room_type),
                "target_date": r.target_date.isoformat(),
                "current_price": r.current_price,
                "rec_min": r.recommended_price_min,
                "rec_max": r.recommended_price_max,
                "type": r.recommendation_type,
                "type_label": _RECO_TYPE_LABELS.get(r.recommendation_type, r.recommendation_type),
                "reason": r.reason,
                "confidence": r.confidence,
                "confidence_label": _CONFIDENCE_LABELS.get(r.confidence, r.confidence),
                "status": r.status,
            }
        )

    errors_30 = calc_forecast_errors(30)
    errors_90 = calc_forecast_errors(90)
    quality_warn = should_warn_quality(
        errors_30, cfg.forecast.max_mae_occupancy, cfg.forecast.max_mape_revenue
    )

    competitors = get_competitor_prices_latest()
    comp_median = None
    comp_prices = [c.price_from for c in competitors if c.price_from and c.price_from > 0]
    if comp_prices:
        comp_median = round(sorted(comp_prices)[len(comp_prices) // 2], 0)

    room_types = [{"slug": "", "label": "Весь объект"}]
    for slug in cfg.site_prices.category_urls or []:
        room_types.append({"slug": slug, "label": _room_type_label(slug)})

    bundle = {
        "horizon_options": FORECAST_HORIZON_OPTIONS,
        "scenario_options": [{"id": k, "label": v} for k, v in _SCENARIO_LABELS.items()],
        "room_types": room_types,
        "filters": {
            "horizon_days": horizon,
            "scenario": scenario,
            "room_type": room_type or "",
        },
        "run": {
            "calculated_at": run.calculated_at.isoformat() if run else None,
            "data_quality": run.data_quality if run else "unknown",
            "horizon_days": run.horizon_days if run else horizon,
        },
        "kpi": kpi,
        "confidence_label": _CONFIDENCE_LABELS.get(kpi["confidence"], kpi["confidence"]),
        "series": series,
        "recommendations": recs[:50],
        "factors": factors_sample,
        "quality": {
            "warn": quality_warn,
            "errors_30": errors_30,
            "errors_90": errors_90,
        },
        "history_days": len(
            {
                m.report_date
                for m in get_metrics_daily(
                    date.today() - timedelta(days=cfg.storage.retention_days),
                    date.today(),
                )
            }
        ),
        "competitor_median": comp_median,
        "competitor_count": len(comp_prices),
        "approved_events": [
            {
                "id": e.id,
                "title": e.title,
                "start_at": e.start_at.isoformat(),
                "end_at": (e.end_at or e.start_at).isoformat(),
                "impact_score": e.impact_score,
                "category": e.category,
                "status": e.status,
                "in_forecast": e.status == "approved" and e.impact_score >= 30,
            }
            for e in (approved_events if include_events else [])
        ],
        "include_events": include_events,
        "events_calibrated": False,
    }

    from src.analytics.forecast_insights import (
        forecast_period_label,
        generate_forecast_commentary,
    )

    commentary = generate_forecast_commentary(bundle, use_llm=False)
    bundle["commentary"] = {
        "text": commentary.get("text", ""),
        "source": commentary.get("source", "rules"),
        "period_label": forecast_period_label(bundle),
    }
    return bundle


_EVENT_CATEGORY_LABELS = {
    "conference": "Конференция",
    "concert": "Концерт",
    "sport": "Спорт",
    "festival": "Фестиваль",
    "exhibition": "Выставка",
    "holiday": "Праздник",
    "other": "Другое",
}

_EVENT_STATUS_LABELS = {
    "candidate": "Кандидат",
    "approved": "Подтверждено",
    "rejected": "Отклонено",
    "cancelled": "Отменено",
    "expired": "Прошло",
}


def fetch_events_bundle(
    *,
    status: str | None = None,
    category: str | None = None,
    min_impact: float | None = None,
    event_id: int | None = None,
) -> dict[str, Any]:
    """Данные для страницы «События Томска»."""
    from src.events.impact import impact_level
    from src.events.service import event_detail_bundle
    from src.storage.db import get_city_events

    cfg = get_config()
    today = date.today()
    end = today + timedelta(days=cfg.events.horizon_days)
    events = get_city_events(
        start=today,
        end=end,
        status=status or None,
        category=category or None,
        min_impact=min_impact,
    )
    calendar: dict[str, list[dict]] = {}
    rows = []
    for ev in events:
        level = impact_level(ev.impact_score)
        item = {
            "id": ev.id,
            "title": ev.title,
            "start_at": ev.start_at.isoformat(),
            "end_at": (ev.end_at or ev.start_at).isoformat(),
            "category": ev.category,
            "category_label": _EVENT_CATEGORY_LABELS.get(ev.category, ev.category),
            "status": ev.status,
            "status_label": _EVENT_STATUS_LABELS.get(ev.status, ev.status),
            "impact_score": ev.impact_score,
            "impact_level": level,
            "venue_name": ev.venue_name,
            "source_name": ev.source_name,
            "source_url": ev.source_url,
            "confidence": ev.confidence,
            "in_forecast": ev.status == "approved" and ev.impact_score >= 30,
            "needs_approval": ev.status == "candidate" and ev.impact_score >= cfg.events.require_approval_score,
        }
        rows.append(item)
        d = ev.start_at
        while d <= (ev.end_at or ev.start_at):
            if d > end:
                break
            calendar.setdefault(d.isoformat(), []).append(item)
            d += timedelta(days=1)

    detail = event_detail_bundle(event_id) if event_id else None
    if detail:
        ev = detail["event"]
        detail["event_dict"] = {
            "id": ev.id,
            "title": ev.title,
            "start_at": ev.start_at.isoformat(),
            "end_at": (ev.end_at or ev.start_at).isoformat(),
            "impact_score": ev.impact_score,
            "status": ev.status,
            "category": ev.category,
            "venue_name": ev.venue_name,
            "audience_scope": ev.audience_scope,
            "estimated_capacity": ev.estimated_capacity,
            "description": ev.description,
        }

    return {
        "horizon_days": cfg.events.horizon_days,
        "events": rows,
        "calendar": calendar,
        "calendar_days": [
            (today + timedelta(days=i)).isoformat() for i in range(cfg.events.horizon_days + 1)
        ],
        "filters": {
            "status": status or "",
            "category": category or "",
            "min_impact": min_impact,
        },
        "categories": [{"id": k, "label": v} for k, v in _EVENT_CATEGORY_LABELS.items()],
        "statuses": [{"id": k, "label": v} for k, v in _EVENT_STATUS_LABELS.items()],
        "require_approval_score": cfg.events.require_approval_score,
        "detail": detail,
        "selected_id": event_id,
        "pending_high": len([e for e in rows if e["needs_approval"]]),
    }
