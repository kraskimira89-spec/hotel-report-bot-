"""Форматирование чисел для weekly email."""

from __future__ import annotations


def fmt_num(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "Нет данных"
    text = f"{value:,.0f}".replace(",", " ")
    return f"{text}{suffix}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "Нет данных"
    return f"{value:.1f}%"


def fmt_change(value: float | None, unit: str = "п.п.") -> str | None:
    if value is None:
        return None
    sign = "+" if value > 0 else ""
    if unit == "%":
        return f"{sign}{value:.1f}%"
    return f"{sign}{value:.1f} {unit}"


def fmt_pct_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 2)


def fmt_pct_change_ratio(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)
