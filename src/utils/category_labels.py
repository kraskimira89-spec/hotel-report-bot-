"""Русские подписи категорий и типов квартир (без английских slug)."""

from __future__ import annotations

import re

# Эталон с 1apart.ru / ТЗ этапа 3.
DEFAULT_CATEGORY_SLUG_MAP: dict[str, str] = {
    "1room23": "Однокомнатные квартиры 23 м²",
    "1room": "Однокомнатные квартиры 27 м²",
    "uluchshennyie-odnokomnatnyie-kvartiryi": "Улучшенные однокомнатные квартиры",
    "family-30": "Однокомнатные квартиры с диванчиком",
    "dvuxkomnatnyie-kvartiryi-(2-krovati)": "Двухкомнатная квартира (2 кровати)",
    "dvuxkomnatnyie-kvartiryi-3": "Двухкомнатная квартира (3 кровати)",
    "80m2-apartamentyi": "Двухкомнатные квартиры люкс",
}

# Подписи типов из листа «Заселяемость» / TravelLine.
DEFAULT_ROOM_TYPE_ALIASES: dict[str, str] = {
    "luxe": "Люкс",
    "lux": "Люкс",
    "1room": "Однокомнатные квартиры",
    "1room23": "Однокомнатные квартиры 23 м²",
    "family-30": "Однокомнатные квартиры с диванчиком",
}


def _normalize_slug(value: str) -> str:
    return value.strip().strip("/").lower()


def category_label(
    slug: str,
    slug_map: dict[str, str] | None = None,
) -> str:
    """Человекочитаемое русское название категории по slug сайта."""
    key = _normalize_slug(slug)
    if not key:
        return "Категория"
    merged = {**DEFAULT_CATEGORY_SLUG_MAP, **(slug_map or {})}
    # Ключи в конфиге могут быть в исходном регистре.
    for cand in (key, slug.strip().strip("/")):
        if cand in merged:
            return merged[cand]
        for map_key, label in merged.items():
            if _normalize_slug(map_key) == key:
                return label
    # Не отдаём сырой английский slug — кратко по паттерну.
    if key.startswith("1room") or "odnokomnat" in key:
        return "Однокомнатные квартиры"
    if "dvux" in key or "2room" in key or "two" in key:
        return "Двухкомнатные квартиры"
    if "family" in key:
        return "Однокомнатные квартиры с диванчиком"
    if "lux" in key or "80m2" in key:
        return "Двухкомнатные квартиры люкс"
    return "Квартира"


def room_type_label(
    name: str,
    aliases: dict[str, str] | None = None,
) -> str:
    """Русская подпись типа квартиры (лист / TravelLine)."""
    raw = (name or "").strip()
    if not raw:
        return "Категория"
    merged = {**DEFAULT_ROOM_TYPE_ALIASES, **(aliases or {})}
    key = raw.lower()
    if key in merged:
        return merged[key]
    for alias_key, label in merged.items():
        if alias_key.lower() == key:
            return label
    # Уже по-русски (кириллица) — оставляем как есть.
    if re.search(r"[А-Яа-яЁё]", raw):
        return raw
    return category_label(raw)
