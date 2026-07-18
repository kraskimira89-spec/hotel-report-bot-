"""Парсинг HTML-афиш источников событий."""

from __future__ import annotations

import re
from datetime import date
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


def _month_number(token: str) -> int | None:
    """Сопоставить русское название месяца с номером."""
    t = token.lower()
    # «май/мая» — короткий ключ, проверяем отдельно
    if t.startswith("ма") and not t.startswith("март"):
        return 5
    for key, num in _MONTHS.items():
        if key == "ма":
            continue
        if t.startswith(key) or key.startswith(t[:4]):
            return num
    return None


def parse_time_from_text(text: str | None) -> str | None:
    """Извлечь время начала HH:MM из текста афиши."""
    if not text:
        return None
    # ISO datetime
    m = re.search(r"T(\d{1,2}):(\d{2})", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
    # 19:00 / 19.00 / 19：00
    m = re.search(r"(?<!\d)([01]?\d|2[0-3])[:.\uFF1A]([0-5]\d)(?!\d)", text)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    # «в 19 часов» / «19 ч»
    m = re.search(r"(?:в\s*)?([01]?\d|2[0-3])\s*(?:часов|часа|час|ч\.?)(?!\d)", text, re.I)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return None


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
        mo = _month_number(m.group(2))
        y = int(m.group(3))
        if mo:
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    # «27 июня» / «27 августа» без года
    if default_year:
        m3 = re.search(
            r"(\d{1,2})\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|"
            r"сентябр|октябр|ноябр|декабр)\w*",
            text.lower(),
        )
        if m3:
            d = int(m3.group(1))
            mo = _month_number(m3.group(2))
            if mo:
                try:
                    return date(default_year, mo, d)
                except ValueError:
                    return None
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
    category: str | None = None,
    source_event_id: str | None = None,
    registration_required: bool = False,
) -> ParsedEvent | None:
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) < 3:
        return None
    start, end = parse_date_range(date_text, default_year=today.year)
    if not start or not _within_horizon(start, today, horizon_end):
        return None
    if end and end < today:
        return None
    # Многодневный период: если end раньше start из-за смены года — поправить
    if end and end < start:
        try:
            end = date(start.year, end.month, end.day)
            if end < start:
                end = date(start.year + 1, end.month, end.day)
        except ValueError:
            end = start
    ev = ParsedEvent(
        title=title,
        start_at=start,
        end_at=end,
        start_time=parse_time_from_text(date_text),
        venue_name=venue,
        source_url=url,
        source_name=source_name,
        source_priority=source_priority,
        description=description,
        raw_date=date_text,
        category=category or "other",
        source_event_id=source_event_id,
        registration_required=registration_required,
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
    """Kassy: ``ul.events > li``, ``a.event_link``, ``p.venue``.

    Площадка и дата на реальной странице находятся в одном ``p.venue``:
    ``Дворец спорта, Большой зал, 2 августа 2026 19:00``.
    """
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select("ul.events > li, .event-card, .kassy-event, li.event"):
        title_el = item.select_one("a.event_link, .event-name, h3")
        venue_el = item.select_one("p.venue, .venue-name, .place")
        link_el = item.select_one("a.event_link[href], a[href]")
        date_text = venue_el.get_text(" ", strip=True) if venue_el else ""
        date_el = item.select_one(".event-date, .date, time")
        if date_el:
            date_text = date_el.get("datetime") or date_el.get_text(" ", strip=True)
        if not title_el or not date_el:
            if not title_el or not date_text:
                continue
        href = (
            urljoin(base_url, link_el["href"])
            if link_el and link_el.get("href")
            else base_url
        )
        venue = venue_el.get_text(" ", strip=True) if venue_el else None
        if venue:
            match = re.search(
                r",?\s*\d{1,2}\s+"
                r"(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|"
                r"сентябр|октябр|ноябр|декабр)\w*\s+\d{4}",
                venue,
                flags=re.I,
            )
            if match:
                venue = venue[: match.start()].rstrip(" ,")
            venue = re.sub(r"\s+([,.;:])", r"\1", venue)
        ev = _make_event(
            title=title_el.get_text(strip=True),
            date_text=date_text,
            venue=venue,
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
    """Томская филармония: карточки ``.poster__card``."""
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select(
        ".poster__card, article.event, .afisha-row, .concert-item"
    ):
        title_el = item.select_one(
            ".poster__card-title, h2, h3, .concert-title"
        )
        date_el = item.select_one(
            ".poster__card-date-date, .concert-date, .date, time"
        )
        venue_el = item.select_one(".poster__card-label, .hall, .venue")
        link_el = item.select_one("a[href]") or item.find_parent("a", href=True)
        if not title_el or not date_el:
            continue
        href = (
            urljoin(base_url, link_el["href"])
            if link_el and link_el.get("href")
            else base_url
        )
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
    """ТУСУР: календарь ``li.small.event > .interval + .title a``."""
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select("li.small.event, .news-item, article, .event-card"):
        title_el = item.select_one(".title a, h2, h3, .title, a")
        date_el = item.select_one(".interval, .date, time, .news-date")
        link_el = item.select_one(".title a[href], a[href]")
        if not title_el or not date_el:
            continue
        href = (
            urljoin(base_url, link_el["href"])
            if link_el and link_el.get("href")
            else base_url
        )
        ev = _make_event(
            title=title_el.get_text(strip=True),
            date_text=date_el.get_text(strip=True),
            venue="ТУСУР",
            url=href,
            source_name="tusur_events",
            source_priority=1,
            today=today,
            horizon_end=horizon_end,
            category="conference",
        )
        if ev:
            ev.audience_scope = "regional"
            events.append(ev)
    return events


def parse_my_business(html: str, base_url: str, today: date, horizon_end: date) -> list[ParsedEvent]:
    """Центр «Мой бизнес»: карточки ``.projects-rct-item``."""
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select(".projects-rct-item"):
        title_el = item.select_one(".projects-rct-item__title, h3")
        date_el = item.select_one(".projects-rct-item__info")
        link_el = item.select_one("a.projects-rct-item__link[href], a[href]")
        if not title_el or not date_el:
            continue
        href = (
            urljoin(base_url, link_el["href"])
            if link_el and link_el.get("href")
            else base_url
        )
        title = title_el.get_text(strip=True)
        sid = None
        m = re.search(r"ELEMENT_ID=(\d+)", href)
        if m:
            sid = m.group(1)
        low = title.lower()
        category = "business"
        if any(w in low for w in ("форум", "конферен")):
            category = "conference"
        elif "выстав" in low:
            category = "exhibition"
        ev = _make_event(
            title=title,
            date_text=date_el.get_text(" ", strip=True),
            venue="Центр «Мой бизнес»",
            url=href,
            source_name="my_business_tomsk",
            source_priority=1,
            today=today,
            horizon_end=horizon_end,
            category=category,
            source_event_id=sid,
            registration_required=True,
        )
        if ev:
            if any(w in low for w in ("межмуницип", "межрегион", "всеросс", "областн")):
                ev.audience_scope = (
                    "national"
                    if any(w in low for w in ("всеросс", "межрегион"))
                    else "regional"
                )
            events.append(ev)
    return events


def parse_sport_calendar(html: str, base_url: str, today: date, horizon_end: date) -> list[ParsedEvent]:
    """Спорткалендарь Томска: таблица ``views-table``."""
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for row in soup.select("table.views-table tr, table.view-events tr, table tr"):
        cells = row.select("td")
        if len(cells) < 2:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        title_el = cells[1].select_one("a") or cells[1]
        venue = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
        link_el = row.select_one("a[href]")
        title = title_el.get_text(strip=True)
        if not title or not date_text:
            continue
        href = (
            urljoin(base_url, link_el["href"])
            if link_el and link_el.get("href")
            else base_url
        )
        sid = None
        m = re.search(r"/calendar/(\d+)", href)
        if m:
            sid = m.group(1)
        ev = _make_event(
            title=title,
            date_text=date_text,
            venue=venue,
            url=href,
            source_name="tomsk_sport_calendar",
            source_priority=1,
            today=today,
            horizon_end=horizon_end,
            category="sport",
            source_event_id=sid,
        )
        if ev:
            low = f"{title} {venue or ''}".lower()
            if any(w in low for w in ("всеросс", "чемпионат россии", "первенство россии")):
                ev.audience_scope = "national"
            elif any(w in low for w in ("сибир", "регион", "област", "межрегион")):
                ev.audience_scope = "regional"
            events.append(ev)
    return events


def parse_library_events(html: str, base_url: str, today: date, horizon_end: date) -> list[ParsedEvent]:
    """Муниципальные библиотеки: ``.card.card-event`` (часто локальные — низкий overnight)."""
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select(".card.card-event, .card-event"):
        title_el = item.select_one(".card-title a, .card-title")
        date_el = item.select_one(".card-date")
        meta = item.select(".card-meta-item")
        link_el = item.select_one("a[href]")
        if not title_el or not date_el:
            continue
        title = title_el.get_text(strip=True)
        low = title.lower()
        # Локальные лекции/мастер-классы не тянем в прогноз-очередь
        if any(w in low for w in ("лекци", "мастер-класс", "мастер класс", "кружок", "школьн")):
            continue
        venue = None
        for m in meta:
            t = m.get_text(" ", strip=True)
            if "место" in t.lower() or "ул." in t.lower() or "пр." in t.lower():
                venue = re.sub(r"(?i)^место проведения:\s*", "", t)
        href = (
            urljoin(base_url, link_el["href"])
            if link_el and link_el.get("href")
            else base_url
        )
        cat = "festival" if "фестив" in low else "other"
        if "праздник" in low or "день" in low:
            cat = "city_holiday"
        ev = _make_event(
            title=title,
            date_text=date_el.get_text(" ", strip=True),
            venue=venue,
            url=href,
            source_name="tomsk_library_events",
            source_priority=2,
            today=today,
            horizon_end=horizon_end,
            category=cat,
            description=item.select_one(".card-excerpt").get_text(" ", strip=True)
            if item.select_one(".card-excerpt")
            else None,
        )
        if ev:
            ev.audience_scope = "local"
            events.append(ev)
    return events


def parse_region_events(html: str, base_url: str, today: date, horizon_end: date) -> list[ParsedEvent]:
    """Событийный календарь области (gosuslugi) — best-effort по разметке OMSU."""
    soup = BeautifulSoup(html, "lxml")
    events: list[ParsedEvent] = []
    for item in soup.select(
        ".tpl-component-gw-events-omsu [class*='event'], "
        ".tpl-component-gw-events-omsu article, "
        "[data-event], .event-card, .afisha-item"
    ):
        title_el = item.select_one("h1, h2, h3, .title, a")
        date_el = item.select_one(".date, time, [datetime]")
        if not title_el:
            continue
        date_text = ""
        if date_el:
            date_text = date_el.get("datetime") or date_el.get_text(" ", strip=True)
        if not date_text:
            date_text = item.get_text(" ", strip=True)
        link_el = item.select_one("a[href]")
        href = (
            urljoin(base_url, link_el["href"])
            if link_el and link_el.get("href")
            else base_url
        )
        ev = _make_event(
            title=title_el.get_text(strip=True),
            date_text=date_text,
            venue=None,
            url=href,
            source_name="tomsk_region_events",
            source_priority=1,
            today=today,
            horizon_end=horizon_end,
            category="holiday",
        )
        if ev:
            events.append(ev)
    if events:
        return events
    return parse_generic(html, base_url, today, horizon_end, "tomsk_region_events")


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
    "my_business_tomsk": parse_my_business,
    "tomsk_sport_calendar": parse_sport_calendar,
    "tomsk_library_events": parse_library_events,
    "tomsk_region_events": parse_region_events,
    "ria_tomsk_events": parse_generic,
}


def parse_events_from_html(
    html: str,
    source_name: str,
    base_url: str,
    today: date,
    horizon_end: date,
) -> list[ParsedEvent]:
    parser = PARSERS.get(source_name)
    if parser and source_name == "ria_tomsk_events":
        return parse_generic(html, base_url, today, horizon_end, source_name)
    if parser:
        return parser(html, base_url, today, horizon_end)
    return parse_generic(html, base_url, today, horizon_end, source_name)
