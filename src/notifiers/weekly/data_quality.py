"""Блок качества данных weekly email."""

from __future__ import annotations

from datetime import date, timedelta

from src.config import AppConfig, get_config
from src.notifiers.weekly.models import DataQualityBlock, WeeklyReportData
from src.storage.db import get_metrics_daily


def build_data_quality(
    data: WeeklyReportData,
    *,
    config: AppConfig | None = None,
) -> DataQualityBlock:
    cfg = config or get_config()
    lines: list[str] = []
    period_days = (data.period_end - data.period_start).days + 1
    metrics = get_metrics_daily(data.period_start, data.period_end)
    tl_days = len({m.report_date for m in metrics if m.metric_type == "daily"})
    if tl_days >= max(1, period_days - 1):
        lines.append("TravelLine: данные получены.")
    elif tl_days > 0:
        lines.append(f"TravelLine: данные за {tl_days} из {period_days} дней.")
    else:
        lines.append("TravelLine: нет данных за период.")

    if any("ГуглТабл" in w for w in data.warnings):
        lines.append("Google Sheets: недоступен или частично.")
    else:
        lines.append("Google Sheets: доступен.")

    mp = data.market_position
    if mp.freshness_label:
        lines.append(f"Конкурентные цены: {mp.freshness_label}.")
    else:
        lines.append("Конкурентные цены: нет актуальных данных.")

    hist = get_metrics_daily(
        date.today() - timedelta(days=365),
        date.today(),
        metric_type="daily",
    )
    hist_days = len({m.report_date for m in hist})
    rec_days = 365
    lines.append(f"Прогноз: история {hist_days} дней из рекомендуемых {rec_days}.")

    approved_trends = len(data.industry_trends)
    lines.append(f"Тренды отрасли в письме: {approved_trends}.")

    overall = "высокая"
    if data.is_partial or tl_days < period_days - 1:
        overall = "средняя"
    if data.critical_error or tl_days == 0:
        overall = "низкая"
    return DataQualityBlock(lines=lines, overall=overall)
