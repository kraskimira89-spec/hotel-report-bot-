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


# Короткие подписи для сводки Max (slug / длинное имя → компактно).
DEFAULT_CATEGORY_SHORT_MAP: dict[str, str] = {
    "1room23": "1-КК 23",
    "1room": "1-КК 27",
    "uluchshennyie-odnokomnatnyie-kvartiryi": "1-КК ул.",
    "family-30": "1-КК диван",
    "dvuxkomnatnyie-kvartiryi-(2-krovati)": "2-КК (2кр)",
    "dvuxkomnatnyie-kvartiryi-3": "2-КК (3кр)",
    "80m2-apartamentyi": "2-КК люкс",
    "luxe": "Люкс",
    "lux": "Люкс",
}


def category_short_label(
    name_or_slug: str,
    short_map: dict[str, str] | None = None,
) -> str:
    """Короткая подпись категории для сводки Max (1-КК / 2-КК)."""
    raw = (name_or_slug or "").strip()
    if not raw:
        return "—"
    # Служебные строки сводки — не трогаем.
    if raw.casefold() in {"итого", "все категории", "прочее"}:
        return raw
    if raw.casefold() in {"люкс", "luxe", "lux"}:
        return "Люкс"

    merged = {**DEFAULT_CATEGORY_SHORT_MAP, **(short_map or {})}
    key = _normalize_slug(raw)
    for cand in (key, raw, raw.strip().strip("/")):
        if cand in merged:
            return merged[cand]
        for map_key, short in merged.items():
            if _normalize_slug(map_key) == key:
                return short

    # Эвристики по русскому / slug тексту.
    low = raw.casefold()
    if "диван" in low or "family" in low:
        return "1-КК диван"
    if "улучш" in low or "uluchsh" in low:
        return "1-КК ул."
    if "люкс" in low or "80m2" in low:
        return "2-КК люкс"
    if "3 кроват" in low or "3кроват" in low or re.search(r"\b3\b", low) and "двух" in low:
        return "2-КК (3кр)"
    if "2 кроват" in low or "2кроват" in low or "(2" in low and "двух" in low:
        return "2-КК (2кр)"
    if "двухкомнат" in low or "dvux" in low or "2room" in low or "2-кк" in low:
        return "2-КК"
    m23 = re.search(r"23\s*м", low) or "1room23" in key
    m27 = re.search(r"27\s*м", low) or (key == "1room")
    if "однокомнат" in low or "1room" in key or "1-кк" in low or "1-комн" in low:
        if m23 or re.search(r"\b23\b", low):
            return "1-КК 23"
        if m27 or re.search(r"\b27\b", low):
            return "1-КК 27"
        return "1-КК"
    # Уже короткое (латиница/цифры без «квартир»).
    if len(raw) <= 12 and "квартир" not in low:
        return raw
    return raw
