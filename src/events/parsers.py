"""Парсинг HTML-афиш источников событий."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.events.impact import enrich_parsed_event
from src.events.types import ParsedEvent

_DATE_PATTERNS = (
    re.compile(r"(\d{1,2})[\./](\d{1,2})[\./](\d{4})"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    re.compile(
        r"(\d{1,2})\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*\s+(\d{4})",
        re.I,
    ),
)

_MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}


def parse_russian_date(text: str, default_year: int | None = None) -> date | None:
    """Разобрать дату из текста."""
    text = text.strip()
    if not text:
        return None
    m = _DATE_PATTERNS[0].search(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = _DATE_PATTERNS[1].search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _DATE_PATTERNS[2].search(text.lower())
    if m:
        d = int(m.group(1))
        month_key = m.group(2)[:5]
        y = int(m.group(3))
        mo = next((v for k, v in _MONTHS.items() if month_key.startswith(k)), None)
        if mo:
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    if default_year:
        m2 = re.search(r"(\d{1,2})[\./](\d{1,2})", text)
        if m2:
            try:
                return date(default_year, int(m2.group(2)), int(m2.group(1)))
            except ValueError:
                return None
    return None


def parse_date_range(text: str, default_year: int | None = None) -> tuple[date | None, date | None]:
    """Разобрать диапазон дат «12–14 сентября 2026»."""
    parts = re.split(r"\s*[–—-]\s*", text, maxsplit=1)
    if len(parts) == 2:
        end = parse_russian_date(parts[1], default_year=default_year)
        start = parse_russian_date(parts[0], default_year=end.year if end else default_year)
        if start and not end:
            end = start
        return start, end
    single = parse_russian_date(text, default_year=default_year)
    return single, single


def _within_horizon(d: date, today: date, horizon_end: date) -> bool:
    return today <= d <= horizon_end


def _make_event(
    *,
    title: str,
    date_text: str,
    venue: str | None,
    url: str,
    source_name: str,
    source_priority: int,
    today: date,
    horizon_end: date,
    description: str | None = None,
) -> ParsedEvent | None:
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) < 3:
        return None
    start, end = parse_date_range(date_text, default_year=today.year)
    if not start or not _within_horizon(start, today, horizon_end):
        return None
    if end and end < today:
        return None
    ev = ParsedEvent(
        title=title,
        start_at=start,
        end_at=end,
        venue_name=venue,
        source_url=url,
        source_name=source_name,
        source_priority=source_priority,
        description=description,
        raw_date=date_text,
    )
    return enrich_parsed_event(ev)


def parse_ticketland(html: str, base_url: str, today: date, horizon_end: date) -> list[ParsedEvent]:
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select(".event-item, .afisha-item, article.event"):
        title_el = item.select_one("h2, h3, .title, .event-title")
        date_el = item.select_one(".date, .event-date, time")
        venue_el = item.select_one(".venue, .place, .location")
        link_el = item.select_one("a[href]")
        if not title_el or not date_el:
            continue
        href = urljoin(base_url, link_el["href"]) if link_el and link_el.get("href") else base_url
        ev = _make_event(
            title=title_el.get_text(strip=True),
            date_text=date_el.get("datetime") or date_el.get_text(strip=True),
            venue=venue_el.get_text(strip=True) if venue_el else None,
            url=href,
            source_name="ticketland_tomsk",
            source_priority=1,
            today=today,
            horizon_end=horizon_end,
        )
        if ev:
            events.append(ev)
    return events


def parse_kassy(html: str, base_url: str, today: date, horizon_end: date) -> list[ParsedEvent]:
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select(".event-card, .kassy-event, li.event"):
        title_el = item.select_one(".event-name, h3, a")
        date_el = item.select_one(".event-date, .date")
        venue_el = item.select_one(".venue-name, .place")
        link_el = item.select_one("a[href]")
        if not title_el or not date_el:
            continue
        href = urljoin(base_url, link_el["href"]) if link_el and link_el.get("href") else base_url
        ev = _make_event(
            title=title_el.get_text(strip=True),
            date_text=date_el.get_text(strip=True),
            venue=venue_el.get_text(strip=True) if venue_el else None,
            url=href,
            source_name="tomsk_kassy",
            source_priority=1,
            today=today,
            horizon_end=horizon_end,
        )
        if ev:
            events.append(ev)
    return events


def parse_philharmonic(html: str, base_url: str, today: date, horizon_end: date) -> list[ParsedEvent]:
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select("article.event, .afisha-row, .concert-item"):
        title_el = item.select_one("h2, h3, .concert-title")
        date_el = item.select_one(".concert-date, .date, time")
        venue_el = item.select_one(".hall, .venue")
        link_el = item.select_one("a[href]")
        if not title_el or not date_el:
            continue
        href = urljoin(base_url, link_el["href"]) if link_el and link_el.get("href") else base_url
        ev = _make_event(
            title=title_el.get_text(strip=True),
            date_text=date_el.get_text(strip=True),
            venue=venue_el.get_text(strip=True) if venue_el else "Томская филармония",
            url=href,
            source_name="tomsk_philharmonic",
            source_priority=1,
            today=today,
            horizon_end=horizon_end,
        )
        if ev:
            events.append(ev)
    return events


def parse_tusur(html: str, base_url: str, today: date, horizon_end: date) -> list[ParsedEvent]:
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select(".news-item, article, .event-card"):
        title_el = item.select_one("h2, h3, .title, a")
        date_el = item.select_one(".date, time, .news-date")
        link_el = item.select_one("a[href]")
        if not title_el or not date_el:
            continue
        href = urljoin(base_url, link_el["href"]) if link_el and link_el.get("href") else base_url
        ev = _make_event(
            title=title_el.get_text(strip=True),
            date_text=date_el.get_text(strip=True),
            venue="ТУСУР",
            url=href,
            source_name="tusur_events",
            source_priority=1,
            today=today,
            horizon_end=horizon_end,
        )
        if ev:
            ev.category = "conference"
            ev.audience_scope = "regional"
            events.append(ev)
    return events


def parse_generic(html: str, base_url: str, today: date, horizon_end: date, source_name: str) -> list[ParsedEvent]:
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select("[data-event], .event, article"):
        title_el = item.select_one("h1, h2, h3, .title")
        date_el = item.select_one(".date, time")
        if not title_el or not date_el:
            continue
        ev = _make_event(
            title=title_el.get_text(strip=True),
            date_text=date_el.get_text(strip=True),
            venue=None,
            url=base_url,
            source_name=source_name,
            source_priority=3,
            today=today,
            horizon_end=horizon_end,
        )
        if ev:
            events.append(ev)
    return events


PARSERS = {
    "ticketland_tomsk": parse_ticketland,
    "tomsk_kassy": parse_kassy,
    "tomsk_philharmonic": parse_philharmonic,
    "tusur_events": parse_tusur,
}


def parse_events_from_html(
    html: str,
    source_name: str,
    base_url: str,
    today: date,
    horizon_end: date,
) -> list[ParsedEvent]:
    parser = PARSERS.get(source_name)
    if parser:
        return parser(html, base_url, today, horizon_end)
    return parse_generic(html, base_url, today, horizon_end, source_name)
