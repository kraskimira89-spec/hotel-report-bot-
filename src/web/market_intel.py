"""Справочник конкурентов и трендов рынка апарт-отелей (Томск + мир)."""

from __future__ import annotations

from typing import Any

from src.config import AppConfig, get_config
from src.data_sources.market_trends import CompetitorPriceInfo

# Подробные карточки конкурентов 1apart (Томск, аудит этап 6/7).
_COMPETITOR_INTEL: dict[str, dict[str, Any]] = {
    "Апартаменты Петровские": {
        "district": "Томск, центр",
        "segment": "Апартаменты",
        "units_approx": "Каталог Tilda",
        "price_hint": "от 12 000 ₽/сутки",
        "engine": "Tilda + Bnovo",
        "parser_note": "Static HTML — авто-сбор",
        "description": (
            "Прямой конкурент: посуточные апартаменты с ценами в статическом HTML. "
            "Виджет Bnovo на сайте, но минимум виден в каталоге."
        ),
        "strengths": [
            "Цены открыты в HTML — удобно для мониторинга",
            "Сильная витрина на Tilda",
        ],
        "weaknesses": [
            "Разброс тарифов по срокам проживания",
            "Нет единого стандарта как у 1apart (44 кв.)",
        ],
        "vs_1apart": (
            "1apart — единый апарт-отель с 6 категориями и ресепшен; "
            "Петровские — каталог отдельных апартаментов."
        ),
    },
    "Bon Apart": {
        "district": "Томск",
        "segment": "Апарт-отель",
        "units_approx": "Сеть / несколько объектов",
        "price_hint": "в виджете TL",
        "engine": "Bitrix + TravelLine",
        "parser_note": "TravelLine-виджет — автоцена недоступна",
        "description": (
            "Прямой конкурент по формату апарт-отеля. "
            "Цены только после выбора дат в виджете TravelLine."
        ),
        "strengths": [
            "Онлайн-бронирование через TL",
            "Узнаваемый бренд в Томске",
        ],
        "weaknesses": [
            "Нет публичной «цены от» в HTML",
            "Зависимость от OTA",
        ],
        "vs_1apart": (
            "Сопоставимый формат; 1apart выигрывает прозрачностью категорий "
            "и единым объектом на 44 квартиры."
        ),
    },
    "Центральный": {
        "district": "Томск, центр",
        "segment": "Апарт-отель / гостиница",
        "units_approx": "30+",
        "price_hint": "в виджете TL",
        "engine": "TravelLine-виджет",
        "parser_note": "TravelLine-виджет — автоцена недоступна",
        "description": (
            "Прямой конкурент в центре города. "
            "Сайт на HTTP; цены в JS-виджете бронирования."
        ),
        "strengths": [
            "Центральная локация",
            "Привычный формат для командировочных",
        ],
        "weaknesses": [
            "Устаревший сайт (http)",
            "Цены не в статике",
        ],
        "vs_1apart": (
            "1apart — современный апарт-формат с кухней; "
            "Центральный — классическая гостиница/апарт в центре."
        ),
    },
    "Гоголь": {
        "district": "Томск",
        "segment": "Отель",
        "units_approx": "20–30 номеров",
        "price_hint": "от 3 600 ₽",
        "engine": "Самописный HTML",
        "parser_note": "Regex «Цена от N руб» — авто-сбор",
        "description": (
            "Прямой конкурент по ценовому сегменту. "
            "Минимальная цена в тексте страницы — удобна для парсинга."
        ),
        "strengths": [
            "Низкий порог входа по цене",
            "Простая вёрстка — стабильный парсинг",
        ],
        "weaknesses": [
            "Не апарт-формат (нет кухни)",
            "Меньше привлекательности для длительного проживания",
        ],
        "vs_1apart": (
            "1apart — апартаменты с кухней и стиркой; "
            "Гоголь — отельный stay по более низкой цене."
        ),
    },
    "Xander Hotel": {
        "district": "Томск",
        "segment": "Отель 4* (косвенный)",
        "units_approx": "50+",
        "price_hint": "в iframe-виджете",
        "engine": "WuBook / iframe",
        "parser_note": "WuBook-виджет — автоцена недоступна",
        "description": (
            "Косвенный конкурент: полноценный отель. "
            "Забирает деловых и туристических гостей, не ищущих апарт-формат."
        ),
        "strengths": [
            "Сильный бренд и сервис отеля",
            "Крупный номерной фонд",
        ],
        "weaknesses": [
            "Нет формата квартиры",
            "Цены только в виджете",
        ],
        "vs_1apart": (
            "1apart — для семей и 3+ ночей с кухней; "
            "Xander — классический отельный сервис."
        ),
    },
    "Кухтерин": {
        "district": "Томск",
        "segment": "Гостиница (косвенный)",
        "units_approx": "Каталог номеров",
        "price_hint": "от 4 500 ₽",
        "engine": "Tilda-подобный + TravelLine",
        "parser_note": "Static .price в каталоге — авто-сбор",
        "description": (
            "Косвенный конкурент. Цены размещения в каталоге `/catalog/` "
            "доступны в статическом HTML."
        ),
        "strengths": [
            "Публичные цены в каталоге",
            "Широкий выбор категорий номеров",
        ],
        "weaknesses": [
            "Не апарт-формат",
            "Часть тарифов в TL-виджете",
        ],
        "vs_1apart": (
            "1apart — апарт-отель; Кухтерин — гостиница с номерным фондом."
        ),
    },
    "Скандинавия": {
        "district": "Томск",
        "segment": "Отель 3–4* (косвенный)",
        "units_approx": "80+",
        "price_hint": "в виджете TL",
        "engine": "Bitrix + TravelLine",
        "parser_note": "TravelLine-виджет — автоцена недоступна",
        "description": (
            "Крупный отель — косвенный конкурент по цене за ночь "
            "для командировочных и туристов."
        ),
        "strengths": [
            "Большой фонд и парковка",
            "Корпоративные контракты",
        ],
        "weaknesses": [
            "Нет кухни в номере",
            "Цены в JS-виджете",
        ],
        "vs_1apart": (
            "1apart — длительное проживание и семьи; "
            "Скандинавия — массовый hotel stay."
        ),
    },
    "Парад Парк": {
        "district": "Томск",
        "segment": "Отель (косвенный)",
        "units_approx": "40+",
        "price_hint": "в виджете TL/Bnovo",
        "engine": "Bitrix + TravelLine/Bnovo",
        "parser_note": "Виджет бронирования — автоцена недоступна",
        "description": (
            "Косвенный конкурент. Цены в виджете, "
            "в HTML только описание номеров."
        ),
        "strengths": [
            "Удобная локация",
            "Активное присутствие на агрегаторах",
        ],
        "weaknesses": [
            "Нет авто-сбора цен",
            "Не апарт-формат",
        ],
        "vs_1apart": (
            "Разные ЦА: Парад Парк — отель; 1apart — апарт-отель."
        ),
    },
    "Элегант": {
        "district": "Томск",
        "segment": "Отель (косвенный)",
        "units_approx": "30+",
        "price_hint": "в виджете TL",
        "engine": "Bitrix + TravelLine (iframe)",
        "parser_note": "TravelLine iframe; robots закрывает *.html",
        "description": (
            "Косвенный конкурент. Цены в iframe TravelLine; "
            "robots.txt ограничивает обход *.html."
        ),
        "strengths": [
            "Премиальная подача",
            "Онлайн-бронирование",
        ],
        "weaknesses": [
            "robots.txt — не ходить на *.html",
            "Цены только в виджете",
        ],
        "vs_1apart": (
            "1apart — апарт-формат и прозрачные категории; "
            "Элегант — классический отель."
        ),
    },
}

TOMASK_TRENDS: list[dict[str, str]] = [
    {
        "title": "Спрос на 3–14 ночей в Томске",
        "body": (
            "Командировки, лечение, переезд и учёба в вузах — основной сегмент "
            "среднего проживания. Апарт-отели с кухней выигрывают у отелей 3*."
        ),
        "tag": "Спрос",
    },
    {
        "title": "OTA и агрегаторы в регионе",
        "body": (
            "Яндекс Путешествия и Ostrovok активны в Томске. "
            "Паритет цен и отзывы критичны для доли прямых бронирований."
        ),
        "tag": "Каналы",
    },
    {
        "title": "Динамическое ценообразование",
        "body": (
            "Лидеры (Петровские, Bon Apart) меняют тарифы по загрузке и сезону. "
            "Статичная «цена от» — витрина; стратегия — в TL/Bnovo."
        ),
        "tag": "Цены",
    },
    {
        "title": "Самозаезд и цифровой ключ",
        "body": (
            "Гости ожидают онлайн-регистрацию и код домофона. "
            "Снижает нагрузку на ресепшен при позднем заселении."
        ),
        "tag": "Сервис",
    },
    {
        "title": "Корпоративные контракты B2B",
        "body": (
            "Томские компании и вузы бронируют блоки на 1–3 месяца. "
            "Стабильная загрузка в будни компенсирует летнюю просадку."
        ),
        "tag": "B2B",
    },
]

GLOBAL_TRENDS: list[dict[str, str]] = [
    {
        "title": "Extended stay — главный драйвер (США, ЕС)",
        "body": (
            "Смешанные проекты hotel + apartment: 30+ ночей, кухня, коворкинг. "
            "Примеры: Sonder, Mint House, Marriott StudioRes."
        ),
        "tag": "Мир",
    },
    {
        "title": "Revenue Management на базе AI",
        "body": (
            "Алгоритмы прогнозируют спрос по событиям и конкурентам. "
            "Средний прирост RevPAR у внедривших — 8–15% (STR, 2025)."
        ),
        "tag": "Технологии",
    },
    {
        "title": "Профессионализация Airbnb-хостов",
        "body": (
            "Крупные операторы вытесняют частников рейтингом и стандартом. "
            "Апарт-отели с брендом и ресепшен — ответ на «pro host» сегмент."
        ),
        "tag": "Конкуренция",
    },
    {
        "title": "Экология и ESG в отелях",
        "body": (
            "Сортировка отходов, отказ от мини-шампуней, умные термостаты. "
            "Корпоративные клиенты всё чаще включают ESG в тендеры."
        ),
        "tag": "ESG",
    },
    {
        "title": "Bleisure — работа + отдых",
        "body": (
            "Гость приезжает на 5 дней: 3 рабочих + 2 выходных в городе. "
            "Пакеты «рабочее место + поздний выезд» повышают ADR."
        ),
        "tag": "Продукт",
    },
]

IDEAS_FOR_1APART: list[dict[str, str]] = [
    {
        "title": "Тариф «7+ ночей» на сайте",
        "body": "Скидка 10–15% при прямом бронировании — защита от OTA и рост доли direct.",
        "priority": "Высокий",
    },
    {
        "title": "Мониторинг 3 static-конкурентов",
        "body": "Автосбор цен с сайтов, где HTML открыт; остальные — ручная сверка раз в неделю.",
        "priority": "Средний",
    },
    {
        "title": "Пуш повторным гостям",
        "body": (
            "Сегмент «Уже проживали» в Sheets — основа для "
            "персональных предложений в Max/email."
        ),
        "priority": "Высокий",
    },
    {
        "title": "Календарь событий Томска",
        "body": "Пики: День города, выпускные, форумы вузов. Закладывать в TL за 2–3 недели.",
        "priority": "Средний",
    },
]


def _match_intel(name: str) -> dict[str, Any]:
    for key, intel in _COMPETITOR_INTEL.items():
        if key.lower() in name.lower() or name.lower() in key.lower():
            return intel
    return {}


def build_competitor_cards(
    config: AppConfig | None = None,
    prices: list[CompetitorPriceInfo] | None = None,
) -> list[dict[str, Any]]:
    """Объединить конфиг, справочник и (если есть) собранные цены."""
    cfg = config or get_config()
    price_by_name = {p.name: p for p in (prices or [])}
    cards: list[dict[str, Any]] = []

    for item in cfg.competitors:
        intel = _match_intel(item.name)
        price_info = price_by_name.get(item.name)
        cards.append(
            {
                "name": item.name,
                "type": item.type,
                "type_label": "Прямой" if item.type == "direct" else "Косвенный",
                "url": item.url,
                "parser": item.parser,
                "price_from": price_info.price_from if price_info else None,
                "available": price_info.available if price_info else False,
                "district": intel.get("district", "—"),
                "segment": intel.get("segment", "Апарт-отель"),
                "units_approx": intel.get("units_approx", "—"),
                "price_hint": intel.get("price_hint", "—"),
                "engine": intel.get("engine", "—"),
                "parser_note": intel.get("parser_note", _parser_label(item.parser)),
                "description": intel.get("description", ""),
                "strengths": intel.get("strengths", []),
                "weaknesses": intel.get("weaknesses", []),
                "vs_1apart": intel.get("vs_1apart", ""),
            }
        )

    if not cards:
        for name, intel in _COMPETITOR_INTEL.items():
            cards.append(
                {
                    "name": name,
                    "type": "direct",
                    "type_label": "Прямой",
                    "url": "",
                    "parser": "widget",
                    "price_from": None,
                    "available": False,
                    "parser_note": "Нет в config",
                    **intel,
                }
            )
    return cards


def _parser_label(parser: str) -> str:
    labels = {
        "static": "Автосбор из HTML (BeautifulSoup)",
        "tl_widget": "TravelLine-виджет — только вручную",
        "wubook_widget": "WuBook-виджет — только вручную",
        "widget": "Виджет бронирования — автоцена недоступна",
    }
    return labels.get(parser, parser)


def competitor_summary(cards: list[dict[str, Any]]) -> dict[str, int]:
    """Сводка по списку конкурентов."""
    direct = sum(1 for c in cards if c["type"] == "direct")
    indirect = len(cards) - direct
    with_price = sum(1 for c in cards if c.get("available"))
    static = sum(1 for c in cards if c.get("parser") == "static")
    return {
        "total": len(cards),
        "direct": direct,
        "indirect": indirect,
        "with_price": with_price,
        "static_parsers": static,
    }


def get_all_trends() -> dict[str, list[dict[str, str]]]:
    """Все блоки трендов для страницы «Тренды»."""
    return {
        "tomsk": TOMASK_TRENDS,
        "global": GLOBAL_TRENDS,
        "ideas": IDEAS_FOR_1APART,
    }
