"""Парсеры сервисных отчётов из писем (TravelLine и расширяемые адаптеры)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class ParsedServiceReport(BaseModel):
    """Ключевые цифры из письма-отчёта сервиса."""

    provider: str = "unknown"
    bookings: int | None = None
    cancellations: int | None = None
    amount: float | None = None
    currency: str = "RUB"
    raw_matches: dict[str, Any] = Field(default_factory=dict)


_NUM = r"[\d\s\u00a0\u202f]+"


def _to_int(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _to_float(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = (
        raw.replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_travelline_report(subject: str, body: str) -> ParsedServiceReport | None:
    """Извлечь брони / отмены / суммы из письма TravelLine."""
    text = f"{subject}\n{body}"
    low = text.casefold()
    if "travelline" not in low and "travel line" not in low:
        # Без явного TL — всё равно пробуем по типичным меткам отчёта.
        if not any(x in low for x in ("брон", "отмен", "выручк", "загрузк")):
            return None

    bookings = None
    for pat in (
        rf"нов(?:ые|ых)?\s+брон[^\d]{{0,20}}({_NUM})",
        rf"брон(?:и|ей|ирован)[^\d]{{0,20}}({_NUM})",
        rf"bookings?[^\d]{{0,12}}({_NUM})",
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            bookings = _to_int(m.group(1))
            if bookings is not None:
                break

    cancellations = None
    for pat in (
        rf"отмен[^\d]{{0,20}}({_NUM})",
        rf"cancel(?:lation)?s?[^\d]{{0,12}}({_NUM})",
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cancellations = _to_int(m.group(1))
            if cancellations is not None:
                break

    amount = None
    for pat in (
        rf"(?:сумм[аые]|выручк[аи]|доход)[^\d]{{0,24}}({_NUM})\s*(?:₽|руб|rub)?",
        rf"({_NUM})\s*(?:₽|руб\.?)",
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            amount = _to_float(m.group(1))
            if amount is not None and amount >= 100:
                break

    if bookings is None and cancellations is None and amount is None:
        return None

    return ParsedServiceReport(
        provider="travelline",
        bookings=bookings,
        cancellations=cancellations,
        amount=amount,
        raw_matches={
            "bookings": bookings,
            "cancellations": cancellations,
            "amount": amount,
        },
    )


def parse_service_report(
    subject: str,
    body: str,
    from_addr: str = "",
) -> ParsedServiceReport | None:
    """Выбрать адаптер по отправителю/теме."""
    low_from = (from_addr or "").casefold()
    low_subj = (subject or "").casefold()
    if "travelline" in low_from or "travelline" in low_subj:
        return parse_travelline_report(subject, body)
    # Общий фолбэк — попробовать TL-парсер на типовом тексте отчёта.
    return parse_travelline_report(subject, body)
