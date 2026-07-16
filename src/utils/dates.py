"""Форматирование дат для UI и отчётов (ДД.ММ.ГГГГ)."""

from __future__ import annotations

import re
from datetime import date, datetime

_ISO_PERIOD_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s*[—\-–]\s*(\d{4}-\d{2}-\d{2})$"
)


def format_date_ru(value: date | datetime | str | None) -> str:
    """Дата в формате 02.07.2026. Пустое → ''."""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    text = str(value).strip()
    if not text:
        return ""
    # Уже ДД.ММ.ГГГГ
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
        return text
    # ISO date / datetime
    try:
        if "T" in text or (" " in text and text[:4].isdigit()):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime(
                "%d.%m.%Y"
            )
        return date.fromisoformat(text[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return text


def format_period_ru(
    start: date | datetime | str | None,
    end: date | datetime | str | None,
    sep: str = " — ",
) -> str:
    """Период: 01.07.2026 — 15.07.2026."""
    left = format_date_ru(start)
    right = format_date_ru(end)
    if left and right:
        return f"{left}{sep}{right}"
    return left or right


def format_period_label(period: str | None) -> str:
    """Преобразовать подпись периода (в т.ч. ISO) в ДД.ММ.ГГГГ — ДД.ММ.ГГГГ."""
    if not period:
        return ""
    text = str(period).strip()
    match = _ISO_PERIOD_RE.match(text)
    if match:
        return format_period_ru(match.group(1), match.group(2))
    return format_date_ru(text) or text
