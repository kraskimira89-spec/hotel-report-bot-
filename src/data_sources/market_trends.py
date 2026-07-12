"""Сбор новостей/трендов и цен конкурентов для отчётов и админки."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from src.config import get_config
from src.data_sources.competitor_prices import collect_competitor_prices
from src.storage.db import (
    clear_trends_idea_of_week,
    get_trend_idea_of_week,
    prune_old_trends,
    save_competitor_prices,
    save_trends,
    trends_count,
)
from src.storage.models import CompetitorPriceRecord, TrendRecord

logger = logging.getLogger(__name__)

DEFAULT_MARKET_TRENDS: list[str] = [
    "Спрос на апарт-отели в Томске остаётся устойчивым в будний сезон.",
    "Гости чаще бронируют напрямую при длительном проживании (3+ ночей).",
    "Агрегаторы усиливают промо в выходные — следите за долей прямых каналов.",
]

TREND_CATEGORIES: list[str] = [
    "Технологии и ИИ",
    "Динамическое ценообразование / RMS",
    "Прямые бронирования",
    "Бесконтактный сервис",
    "Длительное проживание / корпоративные гости",
    "Гость-опыт и допуслуги",
    "Рынок и регулирование",
]

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Технологии и ИИ": ("ai", "ии", "искусствен", "chatbot", "automation", "agent"),
    "Динамическое ценообразование / RMS": (
        "pricing",
        "rms",
        "revenue",
        "yield",
        "tariff",
        "ценообраз",
    ),
    "Прямые бронирования": ("direct", "booking engine", "loyalty", "прям", "direct booking"),
    "Бесконтактный сервис": (
        "contactless",
        "self-check",
        "smart lock",
        "mobile key",
        "бесконтакт",
    ),
    "Длительное проживание / корпоративные гости": (
        "long-stay",
        "extended",
        "corporate",
        "serviced apartment",
        "apart",
    ),
    "Гость-опыт и допуслуги": ("experience", "upsell", "amenity", "guest", "service"),
    "Рынок и регулирование": (
        "market",
        "regulation",
        "demand",
        "supply",
        "moscow",
        "москв",
        "рынок",
    ),
}

class TrendItem(BaseModel):
    """Карточка тренда для сохранения в БД."""

    title: str
    summary: str
    category: str
    region: str
    source_url: str
    published_at: date | None = None
    takeaway: str
    is_idea_of_week: bool = False


class CompetitorPriceInfo(BaseModel):
    """Публичные цены конкурента (если доступны)."""

    name: str
    kind: str
    url: str
    price_from: float | None = None
    available: bool = False
    source: str = "dom"
    screenshot_path: str | None = None
    collected_date: date | None = None


def _build_trend_seeds() -> list[TrendItem]:
    today = date.today()
    return [
        TrendItem(
            title="Агентный ИИ в отелях",
            summary=(
                "ИИ перешёл от подсказок к самостоятельным действиям: отвечает гостю, "
                "двигает тариф в заданных лимитах; человек подключается только в исключениях."
            ),
            category="Технологии и ИИ",
            region="world",
            source_url="https://hoteltechreport.com/news/q2-2026-hotel-ai-trends-report",
            published_at=today - timedelta(days=3),
            takeaway="Снижает трудозатраты и помогает ловить выручку в нерабочее время.",
            is_idea_of_week=True,
        ),
        TrendItem(
            title="Разговорная аналитика",
            summary=(
                "Вместо сложного дашборда менеджер задаёт вопрос простым языком "
                "и получает мгновенный ответ по загрузке и выручке."
            ),
            category="Технологии и ИИ",
            region="world",
            source_url="https://hoteltechreport.com/news/q2-2026-hotel-ai-trends-report",
            published_at=today - timedelta(days=5),
            takeaway="Ускоряет решения по ценам и промо без обучения BI-инструментам.",
        ),
        TrendItem(
            title="Объяснимое ценообразование",
            summary=(
                "RMS показывает, почему рекомендует конкретную цену — растёт доверие "
                "к автоматическим решениям."
            ),
            category="Динамическое ценообразование / RMS",
            region="world",
            source_url="https://hoteltechreport.com/news/q2-2026-hotel-ai-trends-report",
            published_at=today - timedelta(days=7),
            takeaway="Проще обосновывать тарифы команде и владельцам.",
        ),
        TrendItem(
            title="Рост рынка serviced apartments",
            summary=(
                "Оценка ~$132 млрд (2025) → ~$434 млрд к 2033 (CAGR 16,9%); "
                "прямые брони ~44,9%; доминирует long-stay."
            ),
            category="Рынок и регулирование",
            region="world",
            source_url="https://www.grandviewresearch.com/industry-analysis/serviced-apartment-market-report",
            published_at=today - timedelta(days=10),
            takeaway="Апарт-формат растёт быстрее классических отелей — усиливайте long-stay.",
        ),
        TrendItem(
            title="Москва: дефицит предложения, рост цен",
            summary=(
                "В 1П2026 предложение апартаментов упало почти вдвое, "
                "цена за м² выросла на 58,7%."
            ),
            category="Рынок и регулирование",
            region="ru",
            source_url="https://rnrf.ru/news/24413-spros-i-ceny-na-apartamenty-v-moskve-izmenilis-v-2026-godu/",
            published_at=today - timedelta(days=12),
            takeaway="Рынок сжимается — следите за динамикой цен в регионах-лидерах.",
        ),
        TrendItem(
            title="Приоритет прямых бронирований",
            summary=(
                "Снижение зависимости от агрегаторов через лояльность, "
                "retargeting и прямой канал на сайте."
            ),
            category="Прямые бронирования",
            region="ru",
            source_url="https://www.hospitalitynet.org/opinion/4120000.html",
            published_at=today - timedelta(days=14),
            takeaway="Инвестируйте в прямой канал и повторные визиты.",
        ),
        TrendItem(
            title="Бесконтактный заезд и смарт-замки",
            summary=(
                "Онлайн-регистрация и самозаезд становятся стандартом "
                "для апарт-отелей и serviced apartments."
            ),
            category="Бесконтактный сервис",
            region="world",
            source_url="https://www.hospitalitynet.org/opinion/4120000.html",
            published_at=today - timedelta(days=16),
            takeaway="Снижает нагрузку на ресепшен и ускоряет заселение.",
        ),
    ]


TREND_SEEDS = _build_trend_seeds()


def _guess_category(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return TREND_CATEGORIES[0]


def _guess_region(title: str, summary: str, source_url: str) -> str:
    text = f"{title} {summary} {source_url}".lower()
    ru_markers = ("москв", "росси", "rnrf", "томск", ".ru/")
    if any(m in text for m in ru_markers):
        return "ru"
    return "world"


def _parse_rss_date(raw: str | None) -> date | None:
    if not raw:
        return None
    cleaned = raw.strip()
    match = re.search(r"(\d{4}-\d{2}-\d{2})", cleaned)
    if match:
        return date.fromisoformat(match.group(1))
    for fmt in ("%a, %d %b %Y %H:%M:%S", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned[:25], fmt).date()
        except ValueError:
            continue
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


def _parse_rss_items(content: str, source_url: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return items

    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        pub_el = item.find("pubDate")
        if title_el is None or not (title_el.text or "").strip():
            continue
        title = (title_el.text or "").strip()
        summary = _strip_html((desc_el.text if desc_el is not None else "") or title)
        link = (link_el.text if link_el is not None else source_url) or source_url
        items.append(
            {
                "title": title,
                "summary": summary[:500],
                "source_url": link.strip(),
                "published_at": _parse_rss_date(pub_el.text if pub_el is not None else None),
            }
        )
    return items


def _build_takeaway(title: str, category: str) -> str:
    templates = {
        "Технологии и ИИ": f"«{title[:40]}…» — оцените автоматизацию рутины без потери контроля.",
        "Динамическое ценообразование / RMS": (
            f"«{title[:40]}…» — проверьте прозрачность рекомендаций RMS для команды."
        ),
        "Прямые бронирования": f"«{title[:40]}…» — усилите мотивацию бронировать на сайте.",
        "Бесконтактный сервис": f"«{title[:40]}…» — сократите ручные шаги при заезде.",
        "Длительное проживание / корпоративные гости": (
            f"«{title[:40]}…» — проверьте тарифы на 7+ ночей."
        ),
        "Гость-опыт и допуслуги": f"«{title[:40]}…» — найдите 1–2 upsell без перегруза сервиса.",
        "Рынок и регулирование": f"«{title[:40]}…» — сверьте с локальной динамикой Томска.",
    }
    return templates.get(category, f"«{title[:40]}…» — оцените применимость для 1apart.")


def fetch_market_trends(period_days: int = 7, region: str | None = None) -> list[TrendItem]:
    """Собрать тренды из RSS/HTML источников config.market_news."""
    cfg = get_config()
    if not cfg.market_news.enabled:
        return []

    cutoff = date.today() - timedelta(days=period_days)
    collected: list[TrendItem] = []
    headers = {"User-Agent": cfg.site_prices.user_agent}

    for source in cfg.market_news.sources:
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(source, headers=headers)
            if resp.status_code != 200:
                logger.warning("RSS %s: HTTP %s", source, resp.status_code)
                continue
            for raw in _parse_rss_items(resp.text, source):
                pub = raw.get("published_at")
                if isinstance(pub, date) and pub < cutoff:
                    continue
                title = str(raw["title"])
                summary = str(raw["summary"])
                item_region = _guess_region(title, summary, str(raw["source_url"]))
                if region and item_region != region:
                    continue
                category = _guess_category(title, summary)
                collected.append(
                    TrendItem(
                        title=title,
                        summary=summary,
                        category=category,
                        region=item_region,
                        source_url=str(raw["source_url"]),
                        published_at=pub if isinstance(pub, date) else date.today(),
                        takeaway=_build_takeaway(title, category),
                    )
                )
        except httpx.HTTPError as exc:
            logger.warning("Не удалось загрузить RSS %s: %s", source, exc)

    collected.sort(
        key=lambda x: x.published_at or date.today(),
        reverse=True,
    )
    return collected[:8]


def seed_trends_if_empty() -> int:
    """Загрузить стартовые тренды при пустой таблице."""
    if trends_count() > 0:
        return 0
    records = [_trend_item_to_record(item) for item in TREND_SEEDS]
    saved = save_trends(records)
    logger.info("Загружено %s стартовых трендов", saved)
    return saved


def _trend_item_to_record(item: TrendItem) -> TrendRecord:
    return TrendRecord(
        title=item.title,
        summary=item.summary,
        category=item.category,
        region=item.region,
        source_url=item.source_url,
        published_at=item.published_at,
        takeaway=item.takeaway,
        is_idea_of_week=item.is_idea_of_week,
    )


def run_weekly_trends_collection(period_days: int = 7) -> int:
    """Еженедельный сбор трендов: RSS → БД, ретеншен, идея недели."""
    seed_trends_if_empty()
    cfg = get_config()
    saved_total = 0

    for region in cfg.market_news.regions or ["ru", "world"]:
        items = fetch_market_trends(period_days=period_days, region=region)
        if items:
            save_trends([_trend_item_to_record(item) for item in items])
            saved_total += len(items)

    prune_old_trends()
    _refresh_idea_of_week()
    return saved_total


def _refresh_idea_of_week() -> None:
    """Выбрать идею недели: резервный список категорий → любой свежий тренд."""
    if get_trend_idea_of_week() is not None:
        return
    cfg = get_config()
    from src.storage.db import db_session

    with db_session() as conn:
        chosen_id: int | None = None
        chosen_category: str | None = None

        for category in cfg.market_news.idea_priority_order:
            row = conn.execute(
                """
                SELECT id FROM trends
                WHERE category = ?
                ORDER BY COALESCE(published_at, date(created_at)) DESC
                LIMIT 1
                """,
                (category,),
            ).fetchone()
            if row is not None:
                chosen_id = int(row["id"])
                chosen_category = category
                break

        if chosen_id is None:
            row = conn.execute(
                """
                SELECT id, category FROM trends
                ORDER BY COALESCE(published_at, date(created_at)) DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return
            chosen_id = int(row["id"])
            chosen_category = str(row["category"])

        clear_trends_idea_of_week(conn=conn)
        conn.execute(
            "UPDATE trends SET is_idea_of_week = 1 WHERE id = ?",
            (chosen_id,),
        )
        logger.info("Идея недели выбрана из категории: %s", chosen_category)


def collect_and_save_competitor_prices(snapshot_date: date | None = None) -> int:
    """Собрать цены конкурентов и сохранить в БД."""
    snapshot_date = snapshot_date or date.today()
    cfg = get_config()
    if not cfg.competitors:
        return 0

    prices_map = collect_competitor_prices(cfg.competitors, cfg.site_prices)
    records: list[CompetitorPriceRecord] = []
    for item in cfg.competitors:
        price = prices_map.get(item.name)
        available = price is not None
        records.append(
            CompetitorPriceRecord(
                competitor_name=item.name,
                date=snapshot_date,
                price_from=price,
                source="dom" if item.parser == "static" else "vision",
                available=available,
            )
        )
    return save_competitor_prices(records)


def fetch_competitor_prices(
    period_start: date,
    period_end: date,
) -> list[CompetitorPriceInfo]:
    """Список конкурентов и минимальные публичные цены (если доступны)."""
    _ = (period_start, period_end)
    cfg = get_config()
    if not cfg.competitors:
        logger.info("fetch_competitor_prices: список конкурентов пуст")
        return []

    from src.storage.db import get_competitor_prices_latest

    latest_db = {r.competitor_name: r for r in get_competitor_prices_latest()}
    live_map = collect_competitor_prices(cfg.competitors, cfg.site_prices)

    result: list[CompetitorPriceInfo] = []
    for item in cfg.competitors:
        live_price = live_map.get(item.name)
        db_row = latest_db.get(item.name)
        if live_price is not None:
            price = live_price
            source = "dom"
            collected = date.today()
            screenshot = None
        elif db_row is not None:
            price = db_row.price_from
            source = db_row.source
            collected = db_row.date
            screenshot = db_row.screenshot_path
        else:
            price = None
            source = "dom"
            collected = None
            screenshot = None

        result.append(
            CompetitorPriceInfo(
                name=item.name,
                kind=item.type,
                url=item.url,
                price_from=price,
                available=price is not None,
                source=source,
                screenshot_path=screenshot,
                collected_date=collected,
            )
        )
    return result


def build_market_trends(
    period_start: date,
    period_end: date,
    occupancy_pct: float | None = None,
    prev_occupancy_pct: float | None = None,
    direct_share_pct: float | None = None,
    returning_share_pct: float | None = None,
) -> list[str]:
    """Сформировать 3–5 пунктов трендов рынка на основе метрик периода."""
    from src.storage.db import get_price_snapshots

    trends: list[str] = []

    if occupancy_pct is not None and prev_occupancy_pct is not None:
        delta = occupancy_pct - prev_occupancy_pct
        trends.append(
            f"Средняя загрузка за неделю {occupancy_pct:.1f}% "
            f"({delta:+.1f} п.п. к прошлой неделе)."
        )
    elif occupancy_pct is not None:
        trends.append(f"Средняя загрузка за неделю: {occupancy_pct:.1f}%.")

    if direct_share_pct is not None:
        trends.append(f"Доля прямых бронирований: {direct_share_pct:.1f}%.")

    if returning_share_pct is not None:
        trends.append(f"Доля повторных гостей: {returning_share_pct:.1f}%.")

    snapshots = get_price_snapshots(period_start, period_end)
    by_category: dict[str, list[float]] = defaultdict(list)
    for item in snapshots:
        by_category[item.category].append(item.price)

    for category, prices in sorted(by_category.items()):
        if len(prices) < 2:
            continue
        first_week = mean(prices[: max(1, len(prices) // 2)])
        last_week = mean(prices[len(prices) // 2 :])
        if first_week > 0:
            change = (last_week - first_week) / first_week * 100
            trends.append(
                f"Публичная цена «{category}»: {change:+.1f}% за период."
            )
        if len(trends) >= 5:
            break

    for fallback in DEFAULT_MARKET_TRENDS:
        if len(trends) >= 3:
            break
        if fallback not in trends:
            trends.append(fallback)

    return trends[:5]


def fetch_market_news() -> list[dict[str, str]]:
    """Тренды рынка для email (из БД или сиды)."""
    cfg = get_config()
    if not cfg.market_news.enabled:
        return []

    seed_trends_if_empty()
    from src.storage.db import get_trends_records

    rows = get_trends_records(days=30)[: cfg.market_news.max_items]
    if not rows:
        return [
            {
                "title": item.title,
                "body": item.summary,
                "source": urlparse(item.source_url).netloc or item.source_url,
                "tag": item.category,
            }
            for item in TREND_SEEDS[: cfg.market_news.max_items]
        ]

    return [
        {
            "title": row.title,
            "body": row.summary,
            "source": urlparse(row.source_url).netloc or row.source_url,
            "tag": row.category,
        }
        for row in rows
    ]
