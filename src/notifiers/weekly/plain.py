"""Plain-text weekly email v2."""

from __future__ import annotations

from src.notifiers.weekly.models import WeeklyReportData


def build_weekly_report_plain(data: WeeklyReportData) -> str:
    ex = data.executive_summary
    lines = [
        f"1apart · {data.period_start:%d.%m.%Y} — {data.period_end:%d.%m.%Y}",
        "",
        "=== Главное за неделю ===",
        ex.headline,
        f"Действие: {ex.main_action}",
        f"Достоверность: {ex.confidence_label}",
        "",
        "=== KPI ===",
    ]
    for c in data.kpi_cards:
        delta = f" ({c.delta})" if c.delta else ""
        est = " [Оценочно]" if c.is_estimated else ""
        lines.append(f"{c.status} {c.label}: {c.value}{delta}{est}")

    if data.occupancy_by_type:
        lines.extend(["", "=== Загрузка по категориям ==="])
        for row in data.occupancy_by_type:
            lines.append(f"- {row.room_type}: {row.occupancy_pct:.1f}%")

    if data.impact_factors:
        lines.extend(["", "=== Факторы ==="])
        for f in data.impact_factors:
            lines.append(f"- {f.text} ({f.source})")

    fc = data.forecast_next_14_days
    lines.extend(
        [
            "",
            "=== Прогноз 14 дней ===",
            f"Загрузка: {fc.occupancy_range or '—'}",
            f"Выручка: {fc.revenue_range or '—'}",
            f"Уверенность: {fc.confidence_label}",
        ]
    )

    if data.priority_recommendations:
        lines.extend(["", "=== Рекомендации ==="])
        for r in data.priority_recommendations:
            lines.append(f"- [{r.priority}] {r.title}")

    if data.city_events:
        lines.extend(["", "=== События ==="])
        for e in data.city_events:
            lines.append(f"- {e.date_label} {e.title}")

    mp = data.market_position
    lines.extend(
        [
            "",
            "=== Рынок ===",
            f"Медиана: {mp.competitor_median or '—'} ₽",
            f"Позиция: {mp.position_label or '—'}",
        ]
    )

    if data.industry_trends:
        lines.extend(["", "=== Тренды отрасли ==="])
        for t in data.industry_trends:
            lines.append(f"{t.index}. {t.title} ({t.region_label})")
            lines.append(f"   {t.source_name} · {t.published_at:%d.%m.%Y}" if t.published_at else f"   {t.source_name}")

    if data.data_quality.lines:
        lines.extend(["", "=== Качество данных ==="])
        lines.extend(f"- {l}" for l in data.data_quality.lines)

    if data.warnings:
        lines.extend(["", "Примечания:"])
        lines.extend(f"- {w}" for w in data.warnings)

    return "\n".join(lines)
