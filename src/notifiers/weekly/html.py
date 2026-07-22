"""HTML weekly email v2."""

from __future__ import annotations

import html

from src.notifiers.weekly.models import WeeklyReportData

_ACCENT = "#1a5276"
_MUTED = "#666"


def _section(title: str, body: str) -> str:
    return f"""
    <tr><td style="padding:16px 20px 8px;font-size:13px;font-weight:bold;color:{_ACCENT};text-transform:uppercase;">
      {html.escape(title)}
    </td></tr>
    <tr><td style="padding:0 20px 16px;">{body}</td></tr>"""


def _forecast_svg(data: WeeklyReportData) -> str:
    series = data.forecast_next_14_days.series
    if not series:
        return ""
    w, h = 560, 80
    vals = [p.occupancy_pct or 0 for p in series]
    mx = max(vals) or 1
    bars = []
    n = len(vals)
    bw = max(4, (w - 20) // max(n, 1) - 2)
    for i, v in enumerate(vals):
        bh = int(v / mx * (h - 20))
        x = 10 + i * (bw + 2)
        bars.append(
            f'<rect x="{x}" y="{h - bh - 5}" width="{bw}" height="{bh}" fill="{_ACCENT}" opacity="0.7"/>'
        )
    text_dup = ", ".join(
        f"{p.date.strftime('%d.%m')}: {p.occupancy_pct:.0f}%"
        for p in series[:14]
        if p.occupancy_pct is not None
    )
    return f"""
    <svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Прогноз загрузки">
      {''.join(bars)}
    </svg>
    <p style="font-size:12px;color:{_MUTED};margin:8px 0 0;">{html.escape(text_dup)}</p>"""


def build_weekly_report_html(data: WeeklyReportData) -> str:
    ex = data.executive_summary
    period = (
        f"{data.period_start.strftime('%d.%m.%Y')} — "
        f"{data.period_end.strftime('%d.%m.%Y')}"
    )

    kpi_html = ""
    for card in data.kpi_cards:
        delta = f' <span style="color:{_MUTED};">{html.escape(card.delta)}</span>' if card.delta else ""
        est = ' <span style="color:#c0392b;font-size:11px;">(Оценочно)</span>' if card.is_estimated else ""
        kpi_html += f"""
        <td style="width:33%;vertical-align:top;padding:8px;">
          <div style="border:1px solid #ddd;border-radius:6px;padding:10px;background:#fafafa;">
            <div style="font-size:12px;color:{_MUTED};">{html.escape(card.label)}{est}</div>
            <div style="font-size:20px;font-weight:bold;">{card.status} {html.escape(card.value)}{delta}</div>
          </div>
        </td>"""
    kpi_row = f"<tr>{kpi_html}</tr>" if kpi_html else ""

    occ_rows = ""
    for row in data.occupancy_by_type:
        delta = ""
        if row.prev_week_pct is not None:
            d = row.occupancy_pct - row.prev_week_pct
            delta = f"{d:+.1f} п.п."
        hint = f" · {html.escape(row.risk_hint)}" if row.risk_hint else ""
        occ_rows += (
            f"<tr><td>{html.escape(row.room_type)}</td>"
            f"<td>{row.occupancy_pct:.1f}%</td>"
            f"<td>{delta}</td>"
            f"<td>{hint}</td></tr>"
        )

    factors = "".join(
        f"<li>{html.escape(f.text)} <span style='color:{_MUTED};'>({html.escape(f.source)})</span></li>"
        for f in data.impact_factors
    )
    fc = data.forecast_next_14_days
    forecast_body = f"""
    <p>Прогноз загрузки: <strong>{html.escape(fc.occupancy_range or '—')}</strong><br>
    Ожидаемая выручка: <strong>{html.escape(fc.revenue_range or '—')}</strong><br>
    Уверенность: {html.escape(fc.confidence_label)}</p>
    {_forecast_svg(data)}
    """
    if fc.high_demand_days:
        forecast_body += f"<p>Дни высокого спроса: {', '.join(fc.high_demand_days)}</p>"
    if fc.low_risk_days:
        forecast_body += f"<p>Риск низкой загрузки: {', '.join(fc.low_risk_days)}</p>"

    recs_html = ""
    for rec in data.priority_recommendations:
        pri = {"critical": "🔴", "high": "🔴", "medium": "🟡", "low": "🟢"}.get(rec.priority, "🟡")
        link = f' <a href="{html.escape(rec.detail_url)}">Подробнее</a>' if rec.detail_url else ""
        docx = (
            f' · <a href="{html.escape(rec.docx_url)}">Word</a>'
            if rec.has_docx and rec.docx_url
            else ""
        )
        recs_html += f"""
        <div style="margin-bottom:12px;padding:10px;border-left:4px solid {_ACCENT};background:#f9f9f9;">
          <strong>{pri} {html.escape(rec.title)}</strong><br>
          <span style="font-size:13px;color:{_MUTED};">{html.escape(rec.rationale)}</span>{link}{docx}
        </div>"""

    events_html = "".join(
        f"<p>📅 {html.escape(e.date_label)} · {html.escape(e.title)} · {html.escape(e.note)}</p>"
        for e in data.city_events
    )
    mp = data.market_position
    market_html = f"""
    <p>Медиана прямых конкурентов: {html.escape(str(mp.competitor_median or 'Нет данных'))} ₽<br>
    Наша сопоставимая цена: {html.escape(str(mp.our_price or 'Нет данных'))} ₽<br>
    Позиция: {html.escape(mp.position_label or '—')}<br>
    Актуальность: {html.escape(mp.freshness_label or '—')}</p>"""

    trends_html = ""
    for t in data.industry_trends:
        lead = (
            "<p style='font-size:12px;color:#e67e22;'><em>Опережающий тренд: применимость к Томску требует проверки.</em></p>"
            if t.is_leading_trend
            else ""
        )
        pub = t.published_at.strftime("%d.%m.%Y") if t.published_at else "—"
        trends_html += f"""
        <div style="margin-bottom:16px;">
          <strong>{t.index}. {html.escape(t.title)}</strong><br>
          Уровень: {html.escape(t.region_label)}<br>
          Что произошло: {html.escape(t.what_happened)}<br>
          Почему важно: {html.escape(t.why_important)}<br>
          Для 1apart: {html.escape(t.for_1apart)}<br>
          Действие: {html.escape(t.action)}<br>
          <a href="{html.escape(t.source_url)}">{html.escape(t.source_name)}</a> · {pub}
          {lead}
        </div>"""

    dq = "".join(f"<li>{html.escape(line)}</li>" for line in data.data_quality.lines)
    warnings = "".join(f"<li>{html.escape(w)}</li>" for w in data.warnings)

    sections = [
        _section(
            "Главное за неделю",
            f"""<div style="background:#eef5fb;border-radius:8px;padding:14px;">
            <p><strong>Итог:</strong> {html.escape(ex.headline)}</p>
            <p><strong>Главное действие:</strong> {html.escape(ex.main_action)}</p>
            <p style="font-size:13px;color:{_MUTED};">Достоверность данных: {html.escape(ex.confidence_label)}.</p>
            </div>""",
        ),
        _section("Ключевые показатели", f"<table width='100%' cellpadding='0' cellspacing='4'>{kpi_row}</table>"),
    ]
    if occ_rows:
        sections.append(
            _section(
                "Загрузка по категориям",
                f"""<table width='100%' style='border-collapse:collapse;font-size:13px;'>
                <tr style='background:#f4f6f7;'><th>Категория</th><th>Загрузка</th><th>Δ</th><th>Риск/возможность</th></tr>
                {occ_rows}</table>""",
            )
        )
    if factors:
        sections.append(_section("Что повлияло на результат", f"<ul>{factors}</ul>"))
    sections.append(_section("План на 14 дней", forecast_body))
    if recs_html:
        sections.append(_section("Приоритетные рекомендации", recs_html))
    sections.append(_section("События и рынок", events_html + market_html))
    if trends_html:
        sections.append(_section("🌍 Тренды и новости отрасли", trends_html))
    sections.append(
        _section(
            "⚠️ Внимание к данным",
            f"<ul>{dq}</ul>{('<ul>' + warnings + '</ul>') if warnings else ''}",
        )
    )

    body = "".join(sections)
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>1apart · {html.escape(period)}</title></head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:Arial,sans-serif;color:#222;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:16px;">
<table width="640" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;max-width:640px;">
<tr><td style="padding:20px;background:{_ACCENT};color:#fff;">
<h1 style="margin:0;font-size:22px;">1apart · Итоги недели</h1>
<p style="margin:8px 0 0;opacity:0.9;">{html.escape(period)}</p>
</td></tr>
{body}
<tr><td style="padding:16px 20px;font-size:11px;color:{_MUTED};text-align:center;">
<a href="{html.escape(data.report_links.admin_base_url)}">Админка</a>
</td></tr>
</table></td></tr></table></body></html>"""
