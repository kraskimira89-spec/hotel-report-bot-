"""Еженедельный email-отчёт v2."""

from __future__ import annotations

from typing import Any

__all__ = [
    "WeeklyReportData",
    "prepare_weekly_report_data",
    "build_weekly_report_html",
    "build_weekly_report_plain",
    "build_weekly_subject",
]


def __getattr__(name: str) -> Any:
    if name == "WeeklyReportData":
        from src.notifiers.weekly.models import WeeklyReportData

        return WeeklyReportData
    if name == "prepare_weekly_report_data":
        from src.notifiers.weekly.data import prepare_weekly_report_data

        return prepare_weekly_report_data
    if name == "build_weekly_report_html":
        from src.notifiers.weekly.html import build_weekly_report_html

        return build_weekly_report_html
    if name == "build_weekly_report_plain":
        from src.notifiers.weekly.plain import build_weekly_report_plain

        return build_weekly_report_plain
    if name == "build_weekly_subject":
        from src.notifiers.weekly.subject import build_weekly_subject

        return build_weekly_subject
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
