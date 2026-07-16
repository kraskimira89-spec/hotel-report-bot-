"""Тесты формата дат ДД.ММ.ГГГГ."""

from __future__ import annotations

from datetime import date

from src.utils.dates import format_date_ru, format_period_label, format_period_ru


def test_format_date_ru() -> None:
    assert format_date_ru(date(2026, 7, 2)) == "02.07.2026"
    assert format_date_ru("2026-07-02") == "02.07.2026"
    assert format_date_ru("02.07.2026") == "02.07.2026"


def test_format_period_ru() -> None:
    assert format_period_ru(date(2026, 7, 1), date(2026, 7, 15)) == "01.07.2026 — 15.07.2026"


def test_format_period_label_from_iso() -> None:
    assert format_period_label("2026-07-01 — 2026-07-15") == "01.07.2026 — 15.07.2026"
    assert format_period_label("2026-07-01 - 2026-07-15") == "01.07.2026 — 15.07.2026"
