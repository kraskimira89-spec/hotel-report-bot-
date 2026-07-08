"""Отправка HTML email-отчётов через smtplib."""

from __future__ import annotations

import html
import logging
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from statistics import mean
from typing import Any, Callable, Protocol

from pydantic import BaseModel, Field

from src.config import AppConfig, get_config, get_env_settings
from src.data_sources.market_trends import (
    CompetitorPriceSeries,
    build_market_trends,
    fetch_competitor_prices,
)
from src.data_sources.sheets import GoogleSheetsClient, OccupancySheetData
from src.metrics.guests import classify_channel
from src.metrics.occupancy import calc_occupancy
from src.notifiers.max_bot import aggregate_room_status
from src.storage.db import (
    get_bookings_daily,
    get_guests_in_period,
    get_metrics_daily,
    save_report_log,
)
from src.storage.models import MetricsDailyRecord, ReportLogRecord

logger = logging.getLogger(__name__)


class SmtpSender(Protocol):
    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> Any: ...


class OccupancyTypeRow(BaseModel):
    """Загрузка по типу номера."""

    room_type: str
    occupancy_pct: float
    prev_week_pct: float | None = None


class MetricsSummary(BaseModel):
    """Агрегированные метрики за период."""

    occupancy_pct: float | None = None
    adr: float | None = None
    revpar: float | None = None
    als: float | None = None
    revenue: float | None = None
    bookings_count: int = 0
    is_estimated: bool = False


class WeeklyReportData(BaseModel):
    """Данные еженедельного HTML-отчёта."""

    period_start: date
    period_end: date
    occupancy_by_type: list[OccupancyTypeRow] = Field(default_factory=list)
    current_metrics: MetricsSummary | None = None
    prev_week_metrics: MetricsSummary | None = None
    direct_share_pct: float | None = None
    aggregator_share_pct: float | None = None
    returning_guests_pct: float | None = None
    market_trends: list[str] = Field(default_factory=list)
    competitor_prices: list[CompetitorPriceSeries] = Field(default_factory=list)


def _average_metrics(records: list[MetricsDailyRecord]) -> MetricsSummary | None:
    if not records:
        return None

    def _avg(values: list[float | None]) -> float | None:
        nums = [v for v in values if v is not None]
        return round(mean(nums), 2) if nums else None

    return MetricsSummary(
        occupancy_pct=_avg([r.occupancy_pct for r in records]),
        adr=_avg([r.adr for r in records]),
        revpar=_avg([r.revpar for r in records]),
        als=_avg([r.als for r in records]),
        revenue=round(sum(r.revenue or 0 for r in records), 2),
        bookings_count=sum(r.bookings_count or 0 for r in records),
        is_estimated=any(r.is_estimated for r in records),
    )


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 2)


def _occupancy_from_sheets(occupancy: OccupancySheetData) -> list[OccupancyTypeRow]:
    by_type, _ = aggregate_room_status(occupancy)
    rows: list[OccupancyTypeRow] = []
    for item in by_type:
        sold = item.occupied + item.booked
        total = item.total or 1
        rows.append(
            OccupancyTypeRow(
                room_type=item.label,
                occupancy_pct=calc_occupancy(sold, total),
            )
        )
    return rows


def _channel_shares(
    period_start: date,
    period_end: date,
    config: AppConfig,
) -> tuple[float | None, float | None]:
    bookings = get_bookings_daily(period_start, period_end)
    if not bookings:
        return None, None

    direct = 0
    aggregator = 0
    for booking in bookings:
        channel = booking.channel or classify_channel(
            booking.source, config.channels_map
        )
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
    if not guests:
        bookings = get_bookings_daily(period_start, period_end)
        guest_ids = {b.guest_id for b in bookings if b.guest_id}
        if not guest_ids:
            return None
        returning = sum(
            1 for gid in guest_ids if (g := _guest_is_returning(gid)) and g
        )
        return round(returning / len(guest_ids) * 100, 1)

    returning = sum(1 for g in guests if g.is_returning)
    return round(returning / len(guests) * 100, 1)


def _guest_is_returning(guest_id: str) -> bool:
    from src.storage.db import get_guest

    guest = get_guest(guest_id)
    return bool(guest and guest.is_returning)


def prepare_weekly_report_data(
    period_start: date,
    period_end: date,
    config: AppConfig | None = None,
    occupancy: OccupancySheetData | None = None,
) -> WeeklyReportData:
    """Собрать данные отчёта из Sheets, metrics/storage и market_trends."""
    cfg = config or get_config()
    sheets = GoogleSheetsClient(cfg)

    if occupancy is None:
        occupancy = sheets.read_occupancy()

    occupancy_by_type = _occupancy_from_sheets(occupancy)
    current_records = get_metrics_daily(period_start, period_end)
    prev_start = period_start - timedelta(days=7)
    prev_end = period_end - timedelta(days=7)
    prev_records = get_metrics_daily(prev_start, prev_end)

    current_metrics = _average_metrics(current_records)
    prev_week_metrics = _average_metrics(prev_records)

    direct_share, aggregator_share = _channel_shares(period_start, period_end, cfg)
    returning_pct = _returning_guests_pct(period_start, period_end)
    trends = build_market_trends(
        period_start,
        period_end,
        occupancy_pct=current_metrics.occupancy_pct if current_metrics else None,
        prev_occupancy_pct=(
            prev_week_metrics.occupancy_pct if prev_week_metrics else None
        ),
        direct_share_pct=direct_share,
        returning_share_pct=returning_pct,
    )
    competitors = fetch_competitor_prices(period_start, period_end)

    return WeeklyReportData(
        period_start=period_start,
        period_end=period_end,
        occupancy_by_type=occupancy_by_type,
        current_metrics=current_metrics,
        prev_week_metrics=prev_week_metrics,
        direct_share_pct=direct_share,
        aggregator_share_pct=aggregator_share,
        returning_guests_pct=returning_pct,
        market_trends=trends,
        competitor_prices=competitors,
    )


def _fmt_num(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    text = f"{value:,.0f}".replace(",", " ")
    return f"{text}{suffix}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%"


def _fmt_change(value: float | None, unit: str = "п.п.") -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f} {unit}"


def _estimated_badge(is_estimated: bool) -> str:
    return ' <span class="estimated">(оценочный)</span>' if is_estimated else ""


def build_weekly_report_html(data: WeeklyReportData) -> str:
    """Сформировать HTML еженедельного отчёта (без сети)."""
    period = (
        f"{data.period_start.strftime('%d.%m.%Y')} — "
        f"{data.period_end.strftime('%d.%m.%Y')}"
    )
    cur = data.current_metrics
    prev = data.prev_week_metrics

    occ_rows = ""
    for row in data.occupancy_by_type:
        occ_rows += (
            f"<tr><td>{html.escape(row.room_type)}</td>"
            f"<td>{_fmt_pct(row.occupancy_pct)}</td>"
            f"<td>{_fmt_change(_pct_change(row.occupancy_pct, row.prev_week_pct))}</td>"
            f"</tr>"
        )

    overall_occ = cur.occupancy_pct if cur else None
    prev_occ = prev.occupancy_pct if prev else None
    estimated = cur.is_estimated if cur else False

    metrics_rows = ""
    if cur:
        metrics_rows = f"""
        <tr><td>Occupancy</td><td>{_fmt_pct(cur.occupancy_pct)}</td>
            <td>{_fmt_change(_pct_change(cur.occupancy_pct, prev_occ))}</td></tr>
        <tr><td>ADR{_estimated_badge(estimated)}</td><td>{_fmt_num(cur.adr, ' ₽')}</td>
            <td>{_fmt_change(_pct_change(cur.adr, prev.adr if prev else None), '₽')}</td></tr>
        <tr><td>RevPAR{_estimated_badge(estimated)}</td><td>{_fmt_num(cur.revpar, ' ₽')}</td>
            <td>{_fmt_change(_pct_change(cur.revpar, prev.revpar if prev else None), '₽')}</td></tr>
        <tr><td>ALS</td><td>{_fmt_num(cur.als, ' дн.')}</td>
            <td>{_fmt_change(_pct_change(cur.als, prev.als if prev else None), 'дн.')}</td></tr>
        """

    trends_html = "".join(
        f"<li>{html.escape(item)}</li>" for item in data.market_trends
    )

    competitor_html = ""
    if data.competitor_prices:
        dates = sorted(
            {day for item in data.competitor_prices for day in item.prices}
        )
        header = "".join(f"<th>{html.escape(d[5:])}</th>" for d in dates)
        body = ""
        for item in data.competitor_prices:
            cells = "".join(
                f"<td>{_fmt_num(item.prices.get(d), ' ₽')}</td>" for d in dates
            )
            body += (
                f"<tr><td>{html.escape(item.name)}</td>"
                f"<td>{html.escape(item.category)}</td>{cells}</tr>"
            )
        competitor_html = f"""
        <table>
          <thead><tr><th>Источник</th><th>Категория</th>{header}</tr></thead>
          <tbody>{body}</tbody>
        </table>
        """
    else:
        competitor_html = "<p>Нет публичных данных за период.</p>"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Еженедельный отчёт {html.escape(period)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; color: #222; line-height: 1.4; }}
    h1, h2 {{ color: #1a5276; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
    th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; }}
    th {{ background: #f4f6f7; }}
    .estimated {{ color: #c0392b; font-size: 0.9em; }}
    .summary {{ background: #f9f9f9; padding: 10px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Еженедельный отчёт 1apart</h1>
  <p class="summary"><strong>Период:</strong> {html.escape(period)}</p>

  <h2>Загрузка (Occupancy)</h2>
  <table>
    <thead><tr><th>Тип</th><th>Текущая</th><th>Δ к прошлой неделе</th></tr></thead>
    <tbody>{occ_rows}</tbody>
  </table>
  <p><strong>Итого:</strong> {_fmt_pct(overall_occ)}
     ({_fmt_change(_pct_change(overall_occ, prev_occ))} к прошлой неделе)</p>

  <h2>Ключевые метрики</h2>
  <table>
    <thead><tr><th>Показатель</th><th>За неделю</th><th>Δ к прошлой неделе</th></tr></thead>
    <tbody>{metrics_rows or '<tr><td colspan="3">Нет данных в БД</td></tr>'}</tbody>
  </table>

  <h2>Каналы и гости</h2>
  <ul>
    <li>Прямые: {_fmt_pct(data.direct_share_pct)}</li>
    <li>Агрегаторы: {_fmt_pct(data.aggregator_share_pct)}</li>
    <li>Повторные гости: {_fmt_pct(data.returning_guests_pct)}</li>
  </ul>

  <h2>Тренды рынка</h2>
  <ul>{trends_html}</ul>

  <h2>Конкуренты (публичные цены)</h2>
  {competitor_html}
</body>
</html>"""


def build_weekly_report_plain(data: WeeklyReportData) -> str:
    """Текстовый дубль ключевых цифр."""
    cur = data.current_metrics
    prev = data.prev_week_metrics
    lines = [
        f"Еженедельный отчёт 1apart: "
        f"{data.period_start} — {data.period_end}",
        "",
        "Загрузка по типам:",
    ]
    for row in data.occupancy_by_type:
        lines.append(
            f"  - {row.room_type}: {row.occupancy_pct:.1f}% "
            f"(Δ {_fmt_change(_pct_change(row.occupancy_pct, row.prev_week_pct))})"
        )

    if cur:
        est = " (оценочный)" if cur.is_estimated else ""
        lines.extend(
            [
                "",
                f"Occupancy: {_fmt_pct(cur.occupancy_pct)}",
                f"ADR: {_fmt_num(cur.adr, ' руб.')}{est}",
                f"RevPAR: {_fmt_num(cur.revpar, ' руб.')}{est}",
                f"ALS: {_fmt_num(cur.als, ' дн.')}",
            ]
        )
    if prev and cur:
        lines.append(
            f"Δ Occupancy к прошлой неделе: "
            f"{_fmt_change(_pct_change(cur.occupancy_pct, prev.occupancy_pct))}"
        )

    lines.extend(
        [
            "",
            f"Прямые: {_fmt_pct(data.direct_share_pct)}",
            f"Агрегаторы: {_fmt_pct(data.aggregator_share_pct)}",
            f"Повторные гости: {_fmt_pct(data.returning_guests_pct)}",
            "",
            "Тренды:",
        ]
    )
    lines.extend(f"  - {t}" for t in data.market_trends)
    return "\n".join(lines)


def _resolve_recipients(cfg: AppConfig, dry_run: bool) -> list[str]:
    if dry_run:
        return cfg.email.test_addresses
    return cfg.email.to_addresses


def send_html_report(
    subject: str,
    html_body: str,
    text_plain: str,
    dry_run: bool | None = None,
    config: AppConfig | None = None,
    smtp_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Отправить HTML-письмо с текстовым дублем."""
    cfg = config or get_config()
    env = get_env_settings()
    is_dry = cfg.dry_run if dry_run is None else dry_run
    recipients = _resolve_recipients(cfg, is_dry)
    full_subject = f"{cfg.email.subject_prefix} {subject}"

    if not recipients:
        reason = "no_test_addresses" if is_dry else "no_recipients"
        logger.warning("Email пропущен: %s (dry_run=%s)", reason, is_dry)
        return {"status": "skipped", "reason": reason, "dry_run": is_dry}

    if is_dry:
        logger.info(
            "[DRY-RUN] Email → %s: %s (%s bytes HTML)",
            recipients,
            full_subject,
            len(html_body),
        )

    if not env.smtp_host:
        logger.warning("SMTP не настроен")
        return {"status": "skipped", "reason": "no_smtp", "dry_run": is_dry}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = full_subject
    msg["From"] = cfg.email.from_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if smtp_factory:
        server = smtp_factory()
        server.sendmail(cfg.email.from_address, recipients, msg.as_string())
    else:
        with smtplib.SMTP(env.smtp_host, env.smtp_port) as server:
            if env.smtp_use_tls:
                server.starttls()
            if env.smtp_user:
                server.login(env.smtp_user, env.smtp_password)
            server.sendmail(cfg.email.from_address, recipients, msg.as_string())

    logger.info("Email отправлен: %s → %s", full_subject, recipients)
    return {"status": "sent", "recipients": recipients, "dry_run": is_dry}


def send_weekly_report(
    period_start: date | None = None,
    period_end: date | None = None,
    run_date: date | None = None,
    report_date: date | None = None,
    config: AppConfig | None = None,
    report_data: WeeklyReportData | None = None,
    smtp_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Собрать и отправить еженедельный отчёт; записать в reports_log."""
    cfg = config or get_config()
    run_date = run_date or date.today()
    report_date = report_date or run_date
    period_end = period_end or (report_date - timedelta(days=1))
    period_start = period_start or (period_end - timedelta(days=6))

    data = report_data or prepare_weekly_report_data(period_start, period_end, cfg)
    html_body = build_weekly_report_html(data)
    plain = build_weekly_report_plain(data)
    subject = f"{period_start.strftime('%d.%m.%Y')} — {period_end.strftime('%d.%m.%Y')}"

    result = send_html_report(
        subject=subject,
        html_body=html_body,
        text_plain=plain,
        config=cfg,
        smtp_factory=smtp_factory,
    )

    status = "sent" if result.get("status") == "sent" else result.get("status", "error")
    save_report_log(
        ReportLogRecord(
            report_type="email",
            report_date=report_date,
            run_date=run_date,
            period_start=period_start,
            period_end=period_end,
            status=status,
            dry_run=cfg.dry_run,
            preview=plain[:200],
            message=str(result),
        )
    )
    return {**result, "period_start": period_start, "period_end": period_end}
