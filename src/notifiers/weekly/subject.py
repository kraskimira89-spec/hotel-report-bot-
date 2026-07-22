"""Тема письма weekly email v2."""

from __future__ import annotations

from datetime import timedelta

from src.notifiers.weekly.models import WeeklyReportData


def _fmt_short(d) -> str:
    return d.strftime("%d.%m")


def build_weekly_subject(data: WeeklyReportData) -> str:
    ps, pe = data.period_start, data.period_end
    fs = data.period_end + timedelta(days=1)
    fe = data.forecast_end or (fs + timedelta(days=13))
    if data.is_partial:
        return f"⚠️ 1apart · Неполные данные за {_fmt_short(ps)}–{_fmt_short(pe)}"
    return (
        f"1apart · Итоги {_fmt_short(ps)}–{_fmt_short(pe)} "
        f"и план на {_fmt_short(fs)}–{_fmt_short(fe)}"
    )
