"""Гостевая афиша недели: отбор и форматирование для печати / public."""

from __future__ import annotations

import base64
from datetime import date, timedelta
from io import BytesIO
from urllib.parse import quote

from src.config import get_config
from src.storage.db import get_city_events
from src.storage.models import CityEventRecord

_MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

CATEGORY_ICONS = {
    "concert": "🎵",
    "festival": "🎉",
    "exhibition": "🖼️",
    "sport": "🏃",
    "holiday": "🎊",
    "city_holiday": "🎉",
    "fair": "🛍️",
    "theatre": "🎭",
    "other": "📌",
}

_THEATRE_KEYS = ("спектакл", "театр", "постановк", "драм", "балет", "опера")


def format_day_month(d: date) -> str:
    return f"{d.day} {_MONTHS_RU[d.month]}"


def format_period_headline(start: date, end: date) -> str:
    """«18–24 июля 2026» или «28 июля – 3 августа 2026»."""
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {_MONTHS_RU[start.month]} {start.year}"
    if start.year == end.year:
        return (
            f"{start.day} {_MONTHS_RU[start.month]} – "
            f"{end.day} {_MONTHS_RU[end.month]} {start.year}"
        )
    return (
        f"{start.day} {_MONTHS_RU[start.month]} {start.year} – "
        f"{end.day} {_MONTHS_RU[end.month]} {end.year}"
    )


def format_event_when(ev: CityEventRecord) -> str:
    start = ev.start_at
    end = ev.end_at or start
    if end != start:
        if start.month == end.month and start.year == end.year:
            return f"{start.day}–{end.day} {_MONTHS_RU[start.month]}"
        return f"{format_day_month(start)} – {format_day_month(end)}"
    return format_day_month(start)


def guest_display_category(ev: CityEventRecord) -> str:
    text = f"{ev.title} {ev.description or ''}".lower()
    if any(k in text for k in _THEATRE_KEYS):
        return "theatre"
    return ev.category


def is_guest_poster_category(ev: CityEventRecord, allowed: list[str]) -> bool:
    display = guest_display_category(ev)
    if display == "theatre":
        return True
    return display in allowed or ev.category in allowed


def event_qualifies_for_guest_poster(
    ev: CityEventRecord,
    *,
    today: date,
    horizon_end: date,
    allowed_categories: list[str],
) -> bool:
    """Правила отбора для вестибюльной афиши."""
    if ev.status != "approved":
        return False
    if ev.is_online:
        return False
    if not ev.source_url or not str(ev.source_url).strip().startswith("http"):
        return False
    if not (ev.venue_name or ev.venue_address):
        return False
    city = (ev.city or "Томск").strip().lower()
    if city not in ("томск", "tomsk") and not ev.location_confirmed:
        return False
    end = ev.end_at or ev.start_at
    if end < today or ev.start_at > horizon_end:
        return False
    if not is_guest_poster_category(ev, allowed_categories):
        return False
    return True


def select_guest_poster_events(
    *,
    today: date | None = None,
    days: int | None = None,
    max_cards: int | None = None,
) -> list[CityEventRecord]:
    cfg = get_config().events.guest_poster
    today = today or date.today()
    days = max(1, min(31, days if days is not None else cfg.default_days))
    limit = max(1, min(20, max_cards if max_cards is not None else cfg.max_cards))
    horizon_end = today + timedelta(days=days - 1)
    events = get_city_events(start=today, end=horizon_end, status="approved", limit=500)
    picked = [
        e
        for e in events
        if event_qualifies_for_guest_poster(
            e,
            today=today,
            horizon_end=horizon_end,
            allowed_categories=cfg.guest_categories,
        )
    ]
    picked.sort(key=lambda e: (e.start_at, e.title.lower()))
    return picked[:limit]


def qr_image_data_uri(url: str) -> str:
    """QR как data-URI (SVG). Fallback — внешний сервис в шаблоне не нужен."""
    try:
        import qrcode
        import qrcode.image.svg

        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(url, image_factory=factory, border=1, box_size=8)
        buf = BytesIO()
        img.save(buf)
        raw = buf.getvalue()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"
    except Exception:
        # Без зависимости qrcode — публичный генератор
        return (
            "https://api.qrserver.com/v1/create-qr-code/"
            f"?size=160x160&margin=8&data={quote(url, safe='')}"
        )


def build_guest_poster_bundle(
    *,
    days: int | None = None,
    public_url: str,
    today: date | None = None,
) -> dict:
    """Данные для /events/print и /events/public (без служебных полей)."""
    cfg = get_config().events.guest_poster
    today = today or date.today()
    days_n = max(1, min(31, days if days is not None else cfg.default_days))
    horizon_end = today + timedelta(days=days_n - 1)
    events = select_guest_poster_events(today=today, days=days_n)
    cards = []
    for ev in events:
        display_cat = guest_display_category(ev)
        place = ev.venue_name or ev.venue_address or ""
        if ev.venue_name and ev.venue_address and ev.venue_address not in ev.venue_name:
            place = f"{ev.venue_name} · {ev.venue_address}"
        cards.append(
            {
                "title": ev.title,
                "when": format_event_when(ev),
                "place": place,
                "icon": CATEGORY_ICONS.get(display_cat, CATEGORY_ICONS["other"]),
                "url": ev.source_url,
                "category": display_cat,
            }
        )
    return {
        "brand": cfg.brand,
        "headline": cfg.headline,
        "period_label": format_period_headline(today, horizon_end),
        "updated_label": format_day_month(today) + f" {today.year}",
        "today": today.isoformat(),
        "days": days_n,
        "cards": cards,
        "address": cfg.address,
        "wifi": cfg.wifi,
        "contacts": cfg.contacts,
        "disclaimer": cfg.disclaimer,
        "public_url": public_url,
        "qr_src": qr_image_data_uri(public_url),
        "count": len(cards),
    }
