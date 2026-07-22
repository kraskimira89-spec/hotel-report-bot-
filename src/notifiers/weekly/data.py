"""Сбор данных weekly email v2."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from statistics import mean

from src.config import AppConfig, get_config
from src.data_sources.industry_trends import select_industry_trends_for_email
from src.data_sources.sheets import GoogleSheetsClient, OccupancySheetData
from src.events.service import events_for_forecast
from src.metrics.guests import classify_channel
from src.metrics.occupancy import calc_occupancy, traffic_light
from src.notifiers.max_bot import aggregate_room_status
from src.notifiers.weekly.data_quality import build_data_quality
from src.notifiers.weekly.executive import build_executive_summary
from src.notifiers.weekly.formatting import (
    fmt_change,
    fmt_num,
    fmt_pct,
    fmt_pct_change_ratio,
    fmt_pct_delta,
)
from src.notifiers.weekly.models import (
    EventCard,
    ExecutiveSummary,
    ForecastBlock,
    ForecastDayPoint,
    ImpactFactor,
    KpiCard,
    MarketPosition,
    MetricsSummary,
    OccupancyTypeRow,
    RecCard,
    ReportLinks,
    WeeklyReportData,
)
from src.storage.db import get_bookings_daily, get_guests_in_period, get_metrics_daily, list_recommendations
from src.storage.models import MetricsDailyRecord

logger = logging.getLogger(__name__)

_ACTIVE_REC_STATUSES = ("new", "accepted", "in_progress", "deferred")


def _average_metrics(records: list[MetricsDailyRecord]) -> MetricsSummary | None:
    if not records:
        return None

    def _avg(values: list[float | None]) -> float | None:
        nums = [v for v in values if v is not None]
        return round(mean(nums), 2) if nums else None

    daily = [r for r in records if r.metric_type == "daily"]
    if not daily:
        daily = records
    return MetricsSummary(
        occupancy_pct=_avg([r.occupancy_pct for r in daily]),
        adr=_avg([r.adr for r in daily]),
        revpar=_avg([r.revpar for r in daily]),
        als=_avg([r.als for r in daily]),
        revenue=round(sum(r.revenue or 0 for r in daily), 2),
        bookings_count=sum(r.bookings_count or 0 for r in daily),
        is_estimated=any(r.is_estimated for r in daily),
    )


def _channel_shares(
    period_start: date,
    period_end: date,
    config: AppConfig,
) -> tuple[float | None, float | None]:
    bookings = get_bookings_daily(period_start, period_end)
    if not bookings:
        return None, None
    direct = aggregator = 0
    for booking in bookings:
        channel = booking.channel or classify_channel(booking.source, config.channels_map)
        if channel == "direct":
            direct += 1
        elif channel == "aggregator":
            aggregator += 1
    total = direct + aggregator
    if total == 0:
        return None, None
    return round(direct / total * 100, 1), round(aggregator / total * 100, 1)


def _returning_guests_pct(period_start: date, period_end: date) -> float | None:
    guests = get_guests_in_period(period_start, period_end)
    if guests:
        returning = sum(1 for g in guests if g.is_returning)
        return round(returning / len(guests) * 100, 1)
    bookings = get_bookings_daily(period_start, period_end)
    guest_ids = {b.guest_id for b in bookings if b.guest_id}
    if not guest_ids:
        return None
    from src.storage.db import get_guest

    returning = sum(1 for gid in guest_ids if (g := get_guest(gid)) and g.is_returning)
    return round(returning / len(guest_ids) * 100, 1)


def _occupancy_by_type(
    period_start: date,
    period_end: date,
    occupancy: OccupancySheetData,
    config: AppConfig,
) -> list[OccupancyTypeRow]:
    rows: list[OccupancyTypeRow] = []
    prev_start = period_start - timedelta(days=7)
    prev_end = period_end - timedelta(days=7)
    cat_records = get_metrics_daily(period_start, period_end)
    prev_records = get_metrics_daily(prev_start, prev_end)
    by_cat: dict[str, list[float]] = {}
    prev_by_cat: dict[str, list[float]] = {}
    for r in cat_records:
        if r.metric_type.startswith("category:"):
            label = r.metric_type.split(":", 1)[1]
            if r.occupancy_pct is not None:
                by_cat.setdefault(label, []).append(r.occupancy_pct)
    for r in prev_records:
        if r.metric_type.startswith("category:"):
            label = r.metric_type.split(":", 1)[1]
            if r.occupancy_pct is not None:
                prev_by_cat.setdefault(label, []).append(r.occupancy_pct)

    if by_cat:
        for label, vals in sorted(by_cat.items())[:6]:
            occ = round(mean(vals), 2)
            prev_vals = prev_by_cat.get(label)
            prev_occ = round(mean(prev_vals), 2) if prev_vals else None
            delta = fmt_pct_delta(occ, prev_occ)
            hint = ""
            if delta is not None:
                if delta >= 5:
                    hint = "можно проверить повышение цены"
                elif delta <= -5:
                    hint = "проверить спрос и скидки"
            rows.append(
                OccupancyTypeRow(
                    room_type=label,
                    occupancy_pct=occ,
                    prev_week_pct=prev_occ,
                    risk_hint=hint,
                    source="travelline",
                )
            )
        return rows

    if occupancy.is_available:
        by_type, _ = aggregate_room_status(occupancy)
        for item in by_type[:6]:
            sold = item.occupied + item.booked
            total = item.total or 1
            rows.append(
                OccupancyTypeRow(
                    room_type=item.label,
                    occupancy_pct=calc_occupancy(sold, total),
                    source="sheets",
                )
            )
    return rows


def _build_kpi_cards(
    cur: MetricsSummary | None,
    prev: MetricsSummary | None,
    direct: float | None,
    prev_direct: float | None,
    cfg: AppConfig,
) -> list[KpiCard]:
    cards: list[KpiCard] = []
    if not cur:
        return cards

    def _card(
        label: str,
        value: float | None,
        prev_val: float | None,
        *,
        unit: str = "pct",
        estimated: bool = False,
        metric: str = "occupancy",
    ) -> KpiCard:
        if value is None:
            return KpiCard(label=label, value="Нет данных")
        if unit == "pct":
            disp = fmt_pct(value)
            delta = fmt_change(fmt_pct_delta(value, prev_val))
        elif unit == "rub":
            disp = fmt_num(value, " ₽")
            delta = fmt_change(fmt_pct_change_ratio(value, prev_val), "%")
        else:
            disp = fmt_num(value)
            delta = fmt_change(
                float(value - prev_val) if prev_val is not None else None,
                "шт",
            )
        status = traffic_light(value if unit != "count" else 0, cfg.traffic_light, metric=metric)
        note = "Оценочно" if estimated else ""
        return KpiCard(
            label=label,
            value=disp,
            delta=delta,
            status=status,
            is_estimated=estimated,
            note=note,
        )

    cards.append(_card("Загрузка", cur.occupancy_pct, prev.occupancy_pct if prev else None))
    cards.append(
        _card(
            "Выручка",
            cur.revenue,
            prev.revenue if prev else None,
            unit="rub",
            estimated=cur.is_estimated,
        )
    )
    cards.append(
        _card("ADR", cur.adr, prev.adr if prev else None, unit="rub", estimated=cur.is_estimated)
    )
    cards.append(
        _card(
            "RevPAR",
            cur.revpar,
            prev.revpar if prev else None,
            unit="rub",
            estimated=cur.is_estimated,
        )
    )
    cards.append(
        _card(
            "Новые брони",
            float(cur.bookings_count),
            float(prev.bookings_count) if prev else None,
            unit="count",
            metric="new_bookings",
        )
    )
    if direct is not None:
        cards.append(
            _card("Прямые брони", direct, prev_direct, unit="pct", metric="occupancy")
        )
    return cards[:6]


def _build_forecast_block(report_date: date, cfg: AppConfig) -> ForecastBlock:
    try:
        from src.web.queries import fetch_forecast_bundle

        bundle = fetch_forecast_bundle(horizon_days=14, include_events=True)
    except Exception as exc:
        logger.debug("forecast bundle: %s", exc)
        return ForecastBlock(confidence_label="низкая")
    kpi = bundle.get("kpi") or {}
    series_raw = bundle.get("series") or []
    series: list[ForecastDayPoint] = []
    occs: list[float] = []
    for pt in series_raw[:14]:
        occ = pt.get("occupancy_pct")
        fd = pt.get("date")
        if fd and occ is not None:
            d = date.fromisoformat(str(fd)[:10])
            series.append(ForecastDayPoint(date=d, occupancy_pct=float(occ)))
            occs.append(float(occ))
    occ_min = round(min(occs), 1) if occs else None
    occ_max = round(max(occs), 1) if occs else None
    rev = kpi.get("revenue")
    occ_range = ""
    if occ_min is not None and occ_max is not None:
        occ_range = f"{occ_min:.0f}–{occ_max:.0f}%"
    rev_range = fmt_num(rev, " ₽") if rev else ""
    high_days = [p.date.strftime("%d.%m") for p in series if (p.occupancy_pct or 0) >= 75][:3]
    low_days = [p.date.strftime("%d.%m") for p in series if (p.occupancy_pct or 0) < 50][:3]
    events = bundle.get("approved_events") or []
    events_note = ""
    if events:
        events_note = "; ".join(e.get("title", "") for e in events[:2])
    return ForecastBlock(
        occupancy_range=occ_range,
        revenue_range=rev_range,
        confidence_label=str(bundle.get("confidence_label") or "средняя"),
        series=series,
        high_demand_days=high_days,
        low_risk_days=low_days,
        events_note=events_note,
    )


def _build_recommendations(cfg: AppConfig) -> list[RecCard]:
    base = cfg.staff_bot.admin_base_url.rstrip("/")
    recs = list_recommendations(statuses=list(_ACTIVE_REC_STATUSES), limit=20)
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recs.sort(key=lambda r: priority_order.get(r.priority, 9))
    cards: list[RecCard] = []
    for rec in recs[:3]:
        docx = f"{base}/recommendations/{rec.id}/export.docx" if rec.id else ""
        cards.append(
            RecCard(
                priority=rec.priority,
                deadline="—",
                title=rec.title,
                rationale=rec.summary or "",
                detail_url=f"{base}/recommendations/{rec.id}" if rec.id else "",
                docx_url=docx,
                has_docx=bool(rec.id),
            )
        )
    return cards


def _build_events(report_date: date) -> list[EventCard]:
    end = report_date + timedelta(days=13)
    events = events_for_forecast(report_date, end)
    cards: list[EventCard] = []
    for ev in events:
        if ev.status != "approved" or (ev.impact_score or 0) < 60:
            continue
        start = ev.start_at.date() if ev.start_at else report_date
        end_d = (ev.end_at or ev.start_at).date() if ev.end_at or ev.start_at else start
        if start == end_d:
            label = start.strftime("%d.%m")
        else:
            label = f"{start.strftime('%d.%m')}–{end_d.strftime('%d.%m')}"
        note = "высокий потенциал спроса" if (ev.impact_score or 0) >= 75 else "проверить цены"
        cards.append(EventCard(date_label=label, title=ev.title, note=note))
        if len(cards) >= 4:
            break
    return cards


def _build_market_position(cfg: AppConfig) -> MarketPosition:
    try:
        from src.web.queries import fetch_forecast_bundle

        bundle = fetch_forecast_bundle(horizon_days=14, include_events=False)
        median = bundle.get("competitor_median")
        count = bundle.get("competitor_count") or 0
    except Exception:
        median = None
        count = 0
    from src.web.queries import get_competitor_latest

    latest = get_competitor_latest()
    available = sum(1 for c in latest if c.get("price_from"))
    total = len(latest) or count
    freshness = f"доступны по {available} из {total} объектов" if total else "нет данных"
    our_price = None
    position_pct = None
    position_label = ""
    if median and latest:
        ours = [c["price_from"] for c in latest if c.get("price_from")]
        if ours:
            our_price = round(mean(ours), 0)
            if median:
                position_pct = round((our_price - median) / median * 100, 1)
                if position_pct < 0:
                    position_label = f"на {abs(position_pct):.0f}% ниже рынка"
                elif position_pct > 0:
                    position_label = f"на {position_pct:.0f}% выше рынка"
                else:
                    position_label = "на уровне рынка"
    return MarketPosition(
        competitor_median=median,
        our_price=our_price,
        position_pct=position_pct,
        position_label=position_label,
        freshness_label=freshness,
    )


def _build_impact_factors(
    cur: MetricsSummary | None,
    prev: MetricsSummary | None,
    direct: float | None,
    prev_direct: float | None,
    market: MarketPosition,
    events: list[EventCard],
) -> list[ImpactFactor]:
    factors: list[ImpactFactor] = []
    if cur and prev and cur.occupancy_pct is not None and prev.occupancy_pct is not None:
        delta = cur.occupancy_pct - prev.occupancy_pct
        if abs(delta) >= 3:
            direction = "Рост" if delta > 0 else "Снижение"
            factors.append(
                ImpactFactor(
                    text=f"{direction} загрузки за неделю ({delta:+.1f} п.п.).",
                    source="TravelLine",
                )
            )
    if direct is not None and prev_direct is not None:
        d = direct - prev_direct
        if abs(d) >= 3:
            factors.append(
                ImpactFactor(
                    text=f"Доля прямых бронирований изменилась на {d:+.1f} п.п.",
                    source="TravelLine",
                )
            )
    if market.position_pct is not None and market.position_pct < -3:
        factors.append(
            ImpactFactor(
                text="Цена сопоставимой категории ниже медианы рынка.",
                source="конкурентный мониторинг",
            )
        )
    for ev in events[:2]:
        factors.append(
            ImpactFactor(
                text=f"Событие Томска: {ev.title}.",
                source="события Томска",
            )
        )
    return factors[:4]


def prepare_weekly_report_data(
    period_start: date,
    period_end: date,
    config: AppConfig | None = None,
    occupancy: OccupancySheetData | None = None,
    *,
    report_date: date | None = None,
    use_llm: bool = False,
) -> WeeklyReportData:
    """Собрать данные weekly email v2."""
    cfg = config or get_config()
    run_date = report_date or date.today()
    forecast_end = run_date + timedelta(days=13)
    sheets = GoogleSheetsClient(cfg)
    warnings: list[str] = []
    critical = False

    if occupancy is None:
        try:
            occupancy = sheets.read_occupancy()
        except Exception as exc:
            logger.warning("Sheets occupancy: %s", exc)
            from src.data_sources.sheets import OccupancySheetData as OccData

            occupancy = OccData(is_available=False)

    if not occupancy.is_available:
        warnings.append("ГуглТабл недоступен: лист «Заселяемость».")

    current_records = get_metrics_daily(period_start, period_end)
    prev_start = period_start - timedelta(days=7)
    prev_end = period_end - timedelta(days=7)
    prev_records = get_metrics_daily(prev_start, prev_end)
    daily_count = len({r.report_date for r in current_records if r.metric_type == "daily"})
    period_len = (period_end - period_start).days + 1
    if daily_count < max(1, period_len - 2) and not occupancy.is_available:
        critical = True

    cur = _average_metrics(current_records)
    prev = _average_metrics(prev_records)
    direct, aggregator = _channel_shares(period_start, period_end, cfg)
    prev_direct, _ = _channel_shares(prev_start, prev_end, cfg)
    returning = _returning_guests_pct(period_start, period_end)

    base = cfg.staff_bot.admin_base_url.rstrip("/")
    links = ReportLinks(
        admin_base_url=base,
        forecast_url=f"{base}/forecast",
        recommendations_url=f"{base}/recommendations",
        trends_url=f"{base}/trends",
    )

    occ_rows = _occupancy_by_type(period_start, period_end, occupancy, cfg)
    kpi = _build_kpi_cards(cur, prev, direct, prev_direct, cfg)
    forecast = _build_forecast_block(run_date, cfg)
    recs = _build_recommendations(cfg)
    events = _build_events(run_date)
    market = _build_market_position(cfg)
    factors = _build_impact_factors(cur, prev, direct, prev_direct, market, events)
    trends = select_industry_trends_for_email(
        report_date=run_date,
        period_start=period_start,
        period_end=period_end,
        config=cfg,
        use_llm=use_llm,
        log_inclusion=False,
    )

    data = WeeklyReportData(
        period_start=period_start,
        period_end=period_end,
        forecast_end=forecast_end,
        kpi_cards=kpi,
        occupancy_by_type=occ_rows,
        impact_factors=factors,
        forecast_next_14_days=forecast,
        priority_recommendations=recs,
        city_events=events,
        market_position=market,
        industry_trends=trends,
        report_links=links,
        warnings=warnings,
        is_partial=bool(warnings) or daily_count < period_len,
        critical_error=critical,
        current_metrics=cur,
        prev_week_metrics=prev,
        direct_share_pct=direct,
        aggregator_share_pct=aggregator,
        returning_guests_pct=returning,
    )
    data.data_quality = build_data_quality(data, config=cfg)
    data.executive_summary = build_executive_summary(data, use_llm=use_llm)
    return data
