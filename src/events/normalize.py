"""Нормализация названий и дедупликация событий."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from src.events.types import ParsedEvent
from src.storage.models import CityEventRecord

_STOP_WORDS = frozenset({"в", "на", "и", "the", "of", "tomsk", "томск"})


def normalize_title(title: str) -> str:
    """Привести название к виду для сравнения."""
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    tokens = [t for t in text.split() if t and t not in _STOP_WORDS]
    return " ".join(tokens)


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def venues_match(
    parsed: ParsedEvent | None,
    existing: CityEventRecord,
    *,
    parsed_venue: str | None = None,
) -> bool:
    v1 = (parsed_venue or (parsed.venue_name if parsed else None) or "").strip().lower()
    v2 = (existing.venue_name or existing.venue_address or "").strip().lower()
    if not v1 or not v2:
        return True
    return title_similarity(v1, v2) >= 0.7


def find_matching_event(
    parsed: ParsedEvent,
    existing_events: list[CityEventRecord],
    *,
    min_similarity: float = 0.85,
) -> CityEventRecord | None:
    """Найти существующее событие для дедупликации."""
    for ev in existing_events:
        p_city = (parsed.city or "Томск").strip().lower()
        e_city = (ev.city or "Томск").strip().lower()
        if p_city != e_city:
            continue
        if title_similarity(parsed.title, ev.title) < min_similarity:
            continue
        if abs((parsed.start_at - ev.start_at).days) > 1:
            continue
        if not venues_match(parsed, ev):
            continue
        return ev
    return None


def infer_category(title: str, description: str | None = None) -> str:
    text = f"{title} {description or ''}".lower()
    rules = (
        ("business", ("мой бизнес", "семинар", "обучающ", "предпринимат", "бизнес-форум")),
        ("conference", ("конферен", "форум", "сессия", "олимпиад", "хакатон", "защит", "круглый стол")),
        ("concert", ("концерт", "филармон", "оркестр", "dj", "stand-up", "стендап")),
        ("sport", ("матч", "чемпион", "турнир", "спорт", "хоккей", "футбол", "марафон", "забег", "вело")),
        ("festival", ("фестив", "сабантуй", "праздник топора")),
        ("fair", ("ярмарк",)),
        ("exhibition", ("выстав", "экspo", "экспо")),
        ("city_holiday", ("день города", "маслениц", "день победы", "новый год", "новогодн")),
        ("holiday", ("праздник", "выходн")),
    )
    for cat, keys in rules:
        if any(k in text for k in keys):
            return cat
    return "other"


def infer_audience_scope(title: str, description: str | None = None) -> str:
    text = f"{title} {description or ''}".lower()
    if any(w in text for w in ("международ", "international", "world")):
        return "international"
    if any(w in text for w in ("всеросс", "российск", "national", "межрегион")):
        return "national"
    if any(w in text for w in ("межмуницип", "регион", "сибир", "област")):
        return "regional"
    if any(w in text for w in ("томск", "городск", "муницип")):
        return "local"
    return "unknown"


_NON_TOMSK_CITIES = (
    "колпашево",
    "стрежевой",
    "асино",
    "северск",
    "кедровый",
    "кожевниково",
    "парабель",
    "каргасок",
    "молчаново",
    "подгорное",
    "белый яр",
)


def is_online_event(text: str) -> bool:
    low = text.lower()
    return any(
        w in low
        for w in ("онлайн", "online", "вебинар", "zoom", "дистанцион", "в сети", "трансляц")
    )


def infer_city(text: str, default: str = "Томск") -> str:
    """Определить город проведения; вне Томска — для ручного подтверждения."""
    low = text.lower()
    for name in _NON_TOMSK_CITIES:
        if name in low:
            return name.title() if name != "белый яр" else "Белый Яр"
    if "томск" in low or default == "Томск":
        return "Томск"
    return default

