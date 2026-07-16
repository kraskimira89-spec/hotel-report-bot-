"""Сбор цен виджет-конкурентов (TravelLine IBE / WuBook) через Playwright.

Стратегия: DOM (основной) + скриншот всегда + vision-fallback при сбое DOM.
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from src.config import CompetitorConfig, SitePricesConfig, get_config

logger = logging.getLogger(__name__)

_TL_CONTEXT_RE = re.compile(
    r"setContext['\"]?\s*,\s*['\"](TL-INT-[\w.\-]+)['\"]",
    re.IGNORECASE,
)
_TL_CONTEXT_ALT_RE = re.compile(
    r"contextItemName['\"]?\s*[:=]\s*['\"](TL-INT-[\w.\-]+)['\"]",
    re.IGNORECASE,
)
_TL_ANY_RE = re.compile(r"(TL-INT-[\w.\-]+)")
_PRICE_RE = re.compile(
    r"(?:от\s*)?([\d\s\u00a0]{2,})\s*(?:₽|руб\.?|Р(?!\w))",
    re.IGNORECASE,
)

# Типичные селекторы цены в TravelLine IBE / формах бронирования.
_DOM_PRICE_SELECTORS = (
    "[data-price]",
    ".tl-price",
    ".tl-room-price",
    ".price-value",
    ".room-rate__price",
    ".ibe-price",
    ".price",
    "[class*='price']",
)


@dataclass
class WidgetRoomPrice:
    """Цена категории/номера из виджета."""

    name: str
    price_from: float


@dataclass
class WidgetPriceResult:
    """Результат сбора цены с виджета."""

    price_from: float | None = None
    source: str = "dom"  # dom | vision
    screenshot_path: str | None = None  # относительно data/screenshots/
    available: bool = False
    context: str | None = None
    error: str | None = None
    products: list[WidgetRoomPrice] | None = None


def detect_tl_context(html: str) -> str | None:
    """Извлечь contextItemName TravelLine из HTML страницы конкурента."""
    for pattern in (_TL_CONTEXT_RE, _TL_CONTEXT_ALT_RE):
        match = pattern.search(html)
        if match:
            return match.group(1)
    match = _TL_ANY_RE.search(html)
    return match.group(1) if match else None


def competitor_slug(name: str) -> str:
    """Безопасное имя файла для скриншота."""
    slug = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    return slug.strip("_").lower() or "competitor"


def screenshot_rel_path(snapshot_date: date, name: str) -> str:
    """Относительный путь: competitors/YYYY-MM-DD/<slug>.png."""
    return f"competitors/{snapshot_date.isoformat()}/{competitor_slug(name)}.png"


def screenshots_root() -> Path:
    return Path("data/screenshots")


def cleanup_old_screenshots(retention_days: int = 90) -> int:
    """Удалить скриншоты старше retention_days. Возвращает число удалённых файлов."""
    root = screenshots_root() / "competitors"
    if not root.is_dir():
        return 0
    cutoff = date.today() - timedelta(days=retention_days)
    removed = 0
    for day_dir in root.iterdir():
        if not day_dir.is_dir():
            continue
        try:
            day = date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if day >= cutoff:
            continue
        for file in day_dir.glob("*.png"):
            try:
                file.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("Не удалось удалить скриншот %s: %s", file, exc)
        try:
            if not any(day_dir.iterdir()):
                day_dir.rmdir()
        except OSError:
            pass
    return removed


def _extract_price_digits(raw: str) -> float | None:
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    value = float(digits)
    # Отсекаем слишком маленькие/большие «цены» (мусор из дат/телефонов).
    if value < 500 or value > 500_000:
        return None
    return value


def extract_min_price_from_text(text: str) -> float | None:
    """Минимальная похожая на тариф цена из произвольного текста."""
    prices: list[float] = []
    for match in _PRICE_RE.finditer(text or ""):
        value = _extract_price_digits(match.group(1))
        if value is not None:
            prices.append(value)
    return min(prices) if prices else None


def read_price_from_dom(page: Any) -> float | None:
    """Считать минимальную цену из DOM страницы/фрейма виджета."""
    prices: list[float] = []
    for selector in _DOM_PRICE_SELECTORS:
        try:
            elements = page.query_selector_all(selector)
        except Exception:  # noqa: BLE001 — селектор/фрейм может быть недоступен
            continue
        for el in elements:
            try:
                text = el.inner_text()
            except Exception:  # noqa: BLE001
                continue
            value = extract_min_price_from_text(text) or _extract_price_digits(text)
            if value is not None:
                prices.append(value)
    if prices:
        return min(prices)
    try:
        body_text = page.inner_text("body")
    except Exception:  # noqa: BLE001
        return None
    return extract_min_price_from_text(body_text)


def read_price_from_vision(screenshot_path: Path) -> float | None:
    """Vision-fallback: распознать минимальную цену со скриншота (OpenAI)."""
    from os import getenv

    api_key = getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        logger.info("Vision-fallback пропущен: нет OPENAI_API_KEY")
        return None
    if not screenshot_path.is_file():
        return None

    model = getenv("OPENAI_MODEL", "gpt-4o-mini")
    base_url = getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    b64 = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "На скриншоте виджет бронирования отеля. "
                            "Верни ТОЛЬКО JSON вида {\"price_from\": <число>} — "
                            "минимальную цену за одну ночь в рублях. "
                            "Если цены нет — {\"price_from\": null}."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 80,
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vision-fallback ошибка: %s", exc)
        return None

    match = re.search(r"\{[^{}]+\}", content or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        raw = data.get("price_from")
        if raw is None:
            return None
        return float(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _booking_widget_url(context: str, check_in: date, check_out: date) -> str:
    """Устаревший прямой IBE v1 (часто 403 без referer) — оставлен для тестов."""
    return (
        "https://ru-ibe.tlintegration.ru/booking?"
        f"context={context}"
        f"&date={check_in.isoformat()}"
        f"&nights={(check_out - check_in).days}"
        "&adults=2"
    )


# Типичные названия категорий booking2 → «от N ₽» рядом в тексте.
_ROOM_NAME_RE = re.compile(
    r"(?P<name>"
    r"СТАНДАРТ\+?|КОМФОРТ|ЛЮКС|СУПЕРИОР|ПОЛУЛЮКС|АПАРТАМЕНТЫ?|СТУДИЯ|ЭКОНОМ|"
    r"STANDARD\+?|COMFORT|LUXE?|SUITE|STUDIO|FAMILY|DELUXE|JUNIOR(?:\s+SUITE)?"
    r")"
    r".{0,80}?"
    r"от\s+(?P<price>[\d\s\u00a0\u202f]{3,})\s*₽",
    re.IGNORECASE | re.DOTALL,
)

_ROOM_UI_NOISE = frozenset(
    {
        "rub",
        "войти",
        "заезд",
        "выезд",
        "найти",
        "выбрать",
        "выберите номер",
        "наша лучшая цена",
        "гарантия низкой цены",
        "бронируйте выгоднее",
    }
)


def extract_room_prices_from_text(text: str) -> list[WidgetRoomPrice]:
    """Категории с «от N ₽» из текста результатов booking2."""
    products: list[WidgetRoomPrice] = []
    seen: set[str] = set()
    for match in _ROOM_NAME_RE.finditer(text or ""):
        name = re.sub(r"\s+", " ", match.group("name")).strip(" -–|")
        name_l = name.lower()
        if len(name) < 3 or name_l in _ROOM_UI_NOISE:
            continue
        if any(x in name_l for x in ("вместимость", "площадь", "удобств", "ночь")):
            continue
        price = _extract_price_digits(match.group("price"))
        if price is None:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        products.append(WidgetRoomPrice(name=name, price_from=price))
    return products


def _anti_block_pause(
    site_cfg: SitePricesConfig,
    min_sec: float = 3.0,
    max_sec: float = 5.0,
) -> None:
    lo = max(min_sec, site_cfg.request_delay_min_sec)
    hi = max(lo, max(max_sec, site_cfg.request_delay_max_sec))
    time.sleep(random.uniform(lo, hi))


def _import_sync_playwright():
    """Изолированный импорт Playwright (удобно мокать в тестах)."""
    from playwright.sync_api import sync_playwright

    return sync_playwright


def _find_ibe_frame(page: Any) -> Any | None:
    """Найти iframe TravelLine booking2 / IBE."""
    for fr in page.frames:
        url = (fr.url or "").lower()
        if "booking2" in url or "tlintegration" in url or "ibe." in url:
            return fr
    return None


def _open_booking_page(page: Any, competitor: CompetitorConfig) -> None:
    """Открыть страницу с виджетом: booking_url или клик «Забронировать»."""
    start_url = competitor.booking_url or competitor.url
    page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(2500)

    if _find_ibe_frame(page) is not None:
        return

    for sel in (
        "[data-tl-booking-open]",
        ".tl-booking-open",
        "a[href*='booking']",
        "a[href*='ibe.tlintegration']",
        "a[href*='tlintegration']",
        "a:has-text('Забронировать')",
        "button:has-text('Забронировать')",
        "a:has-text('Бронирование')",
        "button:has-text('Бронирование')",
        "text=БРОНИРОВАНИЕ",
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.click(timeout=4000)
            page.wait_for_timeout(3500)
            if _find_ibe_frame(page) is not None:
                return
        except Exception:  # noqa: BLE001
            continue


def _click_search_in_ibe(frame: Any, page: Any) -> bool:
    """Нажать «НАЙТИ» в фильтре booking2 (после выбора дат)."""
    try:
        loc = frame.get_by_text(re.compile(r"найти", re.IGNORECASE))
        if loc.count() > 0:
            loc.first.click(timeout=5000)
            page.wait_for_timeout(6000)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        clicked = frame.evaluate(
            """() => {
              const nodes = Array.from(document.querySelectorAll(
                'button, a, span, div[role="button"], .tl-btn, .p-search-filter__button'
              ));
              const el = nodes.find((e) => {
                const t = (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim();
                return /^найти$/i.test(t);
              });
              if (!el) return false;
              el.click();
              return true;
            }"""
        )
        if clicked:
            page.wait_for_timeout(6000)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _read_prices_from_frames(page: Any) -> tuple[float | None, list[WidgetRoomPrice]]:
    """Минимальная цена и категории из всех фреймов страницы."""
    prices: list[float] = []
    products: list[WidgetRoomPrice] = []
    for fr in page.frames:
        try:
            text = fr.inner_text("body")
        except Exception:  # noqa: BLE001
            continue
        value = extract_min_price_from_text(text)
        if value is not None:
            prices.append(value)
        products.extend(extract_room_prices_from_text(text))
        value_dom = read_price_from_dom(fr)
        if value_dom is not None:
            prices.append(value_dom)
    # Дедуп продуктов по имени, оставляем min цену.
    by_name: dict[str, WidgetRoomPrice] = {}
    for item in products:
        prev = by_name.get(item.name.casefold())
        if prev is None or item.price_from < prev.price_from:
            by_name[item.name.casefold()] = item
    products = list(by_name.values())
    if products and not prices:
        prices = [p.price_from for p in products]
    return (min(prices) if prices else None), products


def parse_widget_with_screenshot(
    competitor: CompetitorConfig,
    check_in: date | None = None,
    check_out: date | None = None,
    *,
    site_cfg: SitePricesConfig | None = None,
    snapshot_date: date | None = None,
    browser: Any | None = None,
) -> WidgetPriceResult:
    """Сбор цены: сайт → iframe booking2 → НАЙТИ → DOM (+ vision-fallback).

    Прямой URL ``/booking?context=…`` у TL часто отдаёт 403 — работаем
    только через виджет на сайте конкурента (origin + referer).
    ``check_in``/``check_out`` используются как целевые даты (виджет обычно
    подставляет ближайшие доступные сам).
    """
    snapshot_date = snapshot_date or date.today()
    check_in = check_in or (snapshot_date + timedelta(days=1))
    check_out = check_out or (check_in + timedelta(days=1))
    _ = (check_in, check_out)  # даты задаёт UI виджета; параметры — для API/тестов
    site_cfg = site_cfg or get_config().site_prices

    rel = screenshot_rel_path(snapshot_date, competitor.name)
    abs_path = screenshots_root() / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        sync_playwright = _import_sync_playwright()
    except ImportError:
        logger.warning(
            "Playwright не установлен — виджет %s пропущен",
            competitor.name,
        )
        return WidgetPriceResult(
            screenshot_path=None,
            available=False,
            error="playwright_not_installed",
        )

    own_browser = browser is None
    playwright_cm = None
    result = WidgetPriceResult(screenshot_path=rel)

    try:
        if own_browser:
            playwright_cm = sync_playwright().start()
            browser = playwright_cm.chromium.launch(headless=True)

        if browser is None:
            raise RuntimeError("Playwright browser is not available")

        context = browser.new_context(
            user_agent=site_cfg.user_agent,
            viewport={"width": 1400, "height": 1000},
            locale="ru-RU",
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(45_000)

        _open_booking_page(page, competitor)
        html = page.content()
        tl_context = detect_tl_context(html)
        result.context = tl_context

        ibe = _find_ibe_frame(page)
        if ibe is None and competitor.parser in {"tl_widget", "widget"}:
            # Повторная попытка: клик бронирования с главной.
            page.goto(competitor.url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)
            _open_booking_page(page, competitor)
            ibe = _find_ibe_frame(page)

        if ibe is not None:
            _click_search_in_ibe(ibe, page)
            # Ждём появления цен (SPA).
            for _ in range(8):
                price_try, _ = _read_prices_from_frames(page)
                if price_try is not None:
                    break
                page.wait_for_timeout(1500)
        elif competitor.parser == "wubook_widget":
            page.wait_for_timeout(4000)
        else:
            page.wait_for_timeout(2000)

        page.screenshot(path=str(abs_path), full_page=True)

        price, products = _read_prices_from_frames(page)
        source = "dom"
        if price is None:
            price = read_price_from_vision(abs_path)
            source = "vision" if price is not None else "dom"

        result.price_from = price
        result.source = source
        result.available = price is not None
        result.screenshot_path = rel
        result.products = products or None
        logger.info(
            "Виджет %s: price=%s rooms=%s source=%s context=%s",
            competitor.name,
            price,
            len(products),
            source,
            tl_context,
        )
        context.close()
    except Exception as exc:  # noqa: BLE001 — graceful fallback
        logger.warning("Сбой виджета %s: %s", competitor.name, exc)
        result.error = str(exc)
        if abs_path.is_file():
            result.screenshot_path = rel
    finally:
        if own_browser and browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
        if playwright_cm is not None:
            try:
                playwright_cm.stop()
            except Exception:  # noqa: BLE001
                pass

    return result


def collect_widget_prices(
    competitors: list[CompetitorConfig],
    site_cfg: SitePricesConfig,
    *,
    snapshot_date: date | None = None,
    enable_widgets: bool = True,
) -> dict[str, WidgetPriceResult]:
    """Последовательно собрать виджет-конкурентов (один браузер на прогон)."""
    snapshot_date = snapshot_date or date.today()
    # Завтра + 1 ночь — меньше риск «сегодня всё занято».
    check_in = snapshot_date + timedelta(days=1)
    check_out = check_in + timedelta(days=1)
    widget_items = [
        c
        for c in competitors
        if c.parser in ("tl_widget", "wubook_widget", "widget")
    ]
    results: dict[str, WidgetPriceResult] = {}

    if not widget_items:
        return results

    if not enable_widgets:
        for item in widget_items:
            results[item.name] = WidgetPriceResult(
                available=False,
                error="widgets_disabled",
            )
        return results

    try:
        sync_playwright = _import_sync_playwright()
    except ImportError:
        for item in widget_items:
            results[item.name] = WidgetPriceResult(
                available=False,
                error="playwright_not_installed",
            )
        return results

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chromium недоступен: %s", exc)
            for item in widget_items:
                results[item.name] = WidgetPriceResult(
                    available=False,
                    error=f"chromium_unavailable: {exc}",
                )
            return results

        try:
            for idx, item in enumerate(widget_items):
                if idx > 0:
                    _anti_block_pause(site_cfg)
                results[item.name] = parse_widget_with_screenshot(
                    item,
                    check_in=check_in,
                    check_out=check_out,
                    site_cfg=site_cfg,
                    snapshot_date=snapshot_date,
                    browser=browser,
                )
        finally:
            browser.close()

    removed = cleanup_old_screenshots(get_config().storage.retention_days)
    if removed:
        logger.info("Очищено старых скриншотов конкурентов: %s", removed)
    return results
