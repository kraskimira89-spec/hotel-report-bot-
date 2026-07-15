"""ИИ-аналитика: карточки выводов и рекомендаций."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from src.config import get_config, get_env_settings
from src.data_sources.sheets import GoogleSheetsClient, OccupancyDay
from src.metrics.guests import classify_channel
from src.storage.db import (
    get_bookings_daily,
    get_competitor_prices_latest,
    get_guest_stats,
    get_metrics_daily,
    get_trends_records,
    replace_insights,
)
from src.storage.models import InsightRecord
from src.utils.metric_labels import (
    ADR_RU,
    REVPAR_RU,
    expand_metric_abbrs,
    looks_mostly_english,
)

logger = logging.getLogger(__name__)

INSIGHT_TOPICS: list[dict[str, str]] = [
    {"id": "occupancy", "label": "Загрузка и динамика", "group": "travelline"},
    {
        "id": "revenue",
        "label": "Доход / ADR (средняя цена) / RevPAR (доход на номер)",
        "group": "travelline",
    },
    {"id": "channels", "label": "Каналы продаж", "group": "travelline"},
    {"id": "returning_guests", "label": "Повторные гости", "group": "travelline"},
    {"id": "cancellations", "label": "Отмены", "group": "travelline"},
    {"id": "als", "label": "Средний срок проживания", "group": "travelline"},
    {"id": "competitors", "label": "Конкуренты", "group": "web"},
    {"id": "market_trends", "label": "Тренды рынка", "group": "web"},
    {"id": "regional_demand", "label": "Спрос в регионе", "group": "web"},
    {"id": "regulation", "label": "Регулирование", "group": "web"},
]

SEVERITY_ORDER = {"action": 0, "attention": 1, "info": 2}


class InsightCard(BaseModel):
    """Карточка ИИ-вывода для ленты аналитики."""

    topic: str
    title: str
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    severity: str = "info"  # info | attention | action
    source: str = "travelline"  # travelline | web | mixed
    period: str = ""
    detail_payload: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


def parse_llm_insight_json(raw: str, topic: str, source: str, period: str) -> InsightCard:
    """Разобрать JSON-ответ LLM в InsightCard."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    severity = str(data.get("severity", "info")).lower()
    if severity not in ("info", "attention", "action"):
        severity = "info"
    recs = data.get("recommendations") or []
    if isinstance(recs, str):
        recs = [recs]
    return InsightCard(
        topic=topic,
        title=expand_metric_abbrs(str(data.get("title") or topic)),
        summary=expand_metric_abbrs(str(data.get("summary") or "")),
        recommendations=[expand_metric_abbrs(str(r)) for r in recs][:3],
        severity=severity,
        source=source,
        period=period,
        detail_payload=data.get("detail_payload") or {},
        updated_at=datetime.utcnow(),
    )


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _occ_day_pct(day: OccupancyDay) -> float | None:
    """Загрузка дня: приоритет строки TravelLine, иначе итог > 0."""
    if day.travelline_pct is not None:
        return float(day.travelline_pct)
    if day.total_pct is not None and float(day.total_pct) > 0:
        return float(day.total_pct)
    # Пустые/нулевые дни в таблице не считаем данными (ещё не заполнены)
    return None


def _series_from_occ_days(days: list[OccupancyDay]) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    for day in days:
        pct = _occ_day_pct(day)
        if pct is None:
            continue
        series.append({"date": day.date.isoformat(), "occupancy_pct": round(pct, 1)})
    return series


def _collect_sheets_overlay(
    start: date,
    end: date,
    prev_start: date,
    prev_end: date,
) -> dict[str, Any]:
    """Живые данные Google Sheets для аналитики (фолбэк, если SQLite пуст)."""
    out: dict[str, Any] = {
        "occupancy_series": [],
        "occupancy_current": None,
        "occupancy_previous": None,
        "by_type": [],
        "channels": None,
        "available": False,
    }
    try:
        sheets = GoogleSheetsClient(get_config())
        cur_days = sheets.read_occupancy_range(start, end)
        prev_days = sheets.read_occupancy_range(prev_start, prev_end)
        cur_series = _series_from_occ_days(cur_days)
        prev_series = _series_from_occ_days(prev_days)
        out["occupancy_series"] = cur_series
        out["occupancy_current"] = _avg([p["occupancy_pct"] for p in cur_series])
        out["occupancy_previous"] = _avg([p["occupancy_pct"] for p in prev_series])

        # Последний день с типами — для детализации карточки
        for day in reversed(cur_days):
            if day.by_type and (
                day.travelline_pct is not None
                or (day.total_pct is not None and float(day.total_pct) > 0)
                or any(r.occupancy_pct is not None for r in day.by_type)
            ):
                out["by_type"] = [
                    {
                        "room_type": r.room_type,
                        "occupancy_pct": r.occupancy_pct,
                        "units": r.units,
                    }
                    for r in day.by_type
                ][:12]
                break

        records = sheets.read_bookings_records_range(start, end)
        if records:
            cfg = get_config()
            direct = 0
            aggregator = 0
            total = 0
            for rec in records:
                n = max(int(rec.bookings_count or 0), 0)
                if n <= 0:
                    continue
                total += n
                kind = classify_channel(rec.source, cfg.channels_map)
                if kind == "direct":
                    direct += n
                elif kind == "aggregator":
                    aggregator += n
            if total:
                out["channels"] = {
                    "direct_pct": round(direct / total * 100, 1),
                    "aggregator_pct": round(aggregator / total * 100, 1),
                    "total": total,
                    "source": "sheets",
                }

        out["available"] = bool(cur_series or out["channels"] or out["by_type"])
        if out["available"]:
            logger.info(
                "Sheets для аналитики: occ_days=%s avg=%s bookings=%s",
                len(cur_series),
                out["occupancy_current"],
                (out["channels"] or {}).get("total", 0),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sheets overlay для аналитики недоступен: %s", exc)
    return out


def _collect_context(period_days: int = 14) -> dict[str, Any]:
    """Контекст аналитики: SQLite + Google Sheets (загрузка/каналы)."""
    end = date.today()
    start = end - timedelta(days=period_days)
    prev_end = start
    prev_start = prev_end - timedelta(days=period_days)

    cur_metrics = []
    prev_metrics = []
    try:
        cur_metrics = get_metrics_daily(start, end, metric_type="daily")
        prev_metrics = get_metrics_daily(prev_start, prev_end, metric_type="daily")
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics_daily недоступны: %s", exc)

    def _metric_vals(rows: list, field: str) -> list[float]:
        out: list[float] = []
        for row in rows:
            val = getattr(row, field, None)
            if val is not None:
                out.append(float(val))
        return out

    cur_occ = _avg(_metric_vals(cur_metrics, "occupancy_pct"))
    prev_occ = _avg(_metric_vals(prev_metrics, "occupancy_pct"))
    cur_adr = _avg(_metric_vals(cur_metrics, "adr"))
    prev_adr = _avg(_metric_vals(prev_metrics, "adr"))
    cur_revpar = _avg(_metric_vals(cur_metrics, "revpar"))
    prev_revpar = _avg(_metric_vals(prev_metrics, "revpar"))
    cur_als = _avg(_metric_vals(cur_metrics, "als"))
    prev_als = _avg(_metric_vals(prev_metrics, "als"))

    channels_agg: dict[str, Any] = {
        "direct_pct": 0.0,
        "aggregator_pct": 0.0,
        "total": 0,
        "source": "sqlite",
    }
    try:
        bookings = get_bookings_daily(start, end)
        direct = 0
        aggregator = 0
        cfg = get_config()
        for b in bookings:
            kind = classify_channel(b.channel or b.source, cfg.channels_map)
            if kind == "direct":
                direct += 1
            elif kind == "aggregator":
                aggregator += 1
        total = len(bookings)
        channels_agg = {
            "direct_pct": round(direct / total * 100, 1) if total else 0.0,
            "aggregator_pct": round(aggregator / total * 100, 1) if total else 0.0,
            "total": total,
            "source": "sqlite",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Каналы SQLite недоступны: %s", exc)

    guests: dict[str, Any] = {"total": 0, "returning": 0}
    try:
        guests = get_guest_stats()
    except Exception as exc:  # noqa: BLE001
        logger.debug("gostats недоступны: %s", exc)
    competitors = []
    try:
        competitors = [
            {
                "name": r.competitor_name,
                "price_from": r.price_from,
                "available": r.available,
            }
            for r in get_competitor_prices_latest()
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Конкуренты недоступны: %s", exc)
        competitors = []

    trends = []
    try:
        trends = [
            {
                "title": t.title,
                "category": t.category,
                "region": t.region,
                "source_url": t.source_url,
                "takeaway": t.takeaway,
            }
            for t in get_trends_records(days=90)[:8]
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Тренды недоступны: %s", exc)

    occ_series = [
        {"date": m.report_date.isoformat(), "occupancy_pct": m.occupancy_pct}
        for m in sorted(cur_metrics, key=lambda x: x.report_date)
        if m.occupancy_pct is not None
    ]
    occ_source = "sqlite"

    sheets = _collect_sheets_overlay(start, end, prev_start, prev_end)
    # Sheets приоритетнее для загрузки и каналов, если там есть цифры
    if sheets["occupancy_series"]:
        occ_series = sheets["occupancy_series"]
        cur_occ = sheets["occupancy_current"]
        prev_occ = sheets["occupancy_previous"]
        occ_source = "sheets"
    if sheets["channels"] and (
        not channels_agg.get("total") or channels_agg.get("total", 0) == 0
    ):
        channels_agg = sheets["channels"]

    period_label = f"{start.isoformat()} — {end.isoformat()}"
    return {
        "period": period_label,
        "period_days": period_days,
        "occupancy": {
            "current": cur_occ,
            "previous": prev_occ,
            "series": occ_series,
            "by_type": sheets.get("by_type") or [],
            "source": occ_source,
        },
        "revenue": {
            "adr": cur_adr,
            "prev_adr": prev_adr,
            "revpar": cur_revpar,
            "prev_revpar": prev_revpar,
        },
        "channels": channels_agg,
        "guests": guests,
        "als": {"current": cur_als, "previous": prev_als},
        "competitors": competitors,
        "trends": trends,
        "data_sources": {
            "occupancy": occ_source,
            "channels": channels_agg.get("source", "sqlite"),
            "sheets_available": bool(sheets.get("available")),
        },
    }


def _delta_label(current: float | None, previous: float | None) -> str:
    if current is None or previous is None or previous == 0:
        return "нет данных для сравнения"
    pct = (current - previous) / previous * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _rule_based_cards(ctx: dict[str, Any]) -> list[InsightCard]:
    """Сгенерировать карточки без LLM (фолбэк и offline-режим)."""
    period = ctx["period"]
    cards: list[InsightCard] = []
    now = datetime.utcnow()

    occ = ctx["occupancy"]
    occ_delta = _delta_label(occ["current"], occ["previous"])
    occ_sev = "info"
    if occ["current"] is not None and occ["previous"] is not None:
        if occ["current"] < occ["previous"] - 5:
            occ_sev = "action"
        elif abs(occ["current"] - (occ["previous"] or 0)) >= 3:
            occ_sev = "attention"
    cards.append(
        InsightCard(
            topic="occupancy",
            title=(
                f"Загрузка {occ['current']:.0f}%"
                if occ["current"] is not None
                else "Загрузка: недостаточно данных"
            ),
            summary=(
                f"Средняя загрузка за период {occ['current']:.1f}% "
                f"(к прошлому периоду {occ_delta})."
                if occ["current"] is not None
                else "В БД мало метрик загрузки — дождитесь накопления данных."
            ),
            recommendations=[
                "Скорректировать тарифы на дни с низкой загрузкой в TravelLine",
                "Усилить прямые акции на слабые даты",
                "Сверить календарь событий города с ценами",
            ],
            severity=occ_sev,
            source="travelline",
            period=period,
            detail_payload={
                "series": occ["series"],
                "current": occ["current"],
                "previous": occ["previous"],
                "by_type": occ.get("by_type") or [],
                "source": occ.get("source", "sqlite"),
            },
            updated_at=now,
        )
    )

    rev = ctx["revenue"]
    rev_delta = _delta_label(rev["revpar"], rev["prev_revpar"])
    rev_sev = "info"
    if rev["revpar"] is not None and rev["prev_revpar"] is not None:
        if rev["revpar"] < rev["prev_revpar"] * 0.9:
            rev_sev = "action"
        elif abs(rev["revpar"] - rev["prev_revpar"]) / max(rev["prev_revpar"], 1) >= 0.05:
            rev_sev = "attention"
    cards.append(
        InsightCard(
            topic="revenue",
            title=(
                f"{REVPAR_RU} {rev['revpar']:.0f} ₽"
                if rev["revpar"] is not None
                else "Доход: мало данных"
            ),
            summary=(
                f"{ADR_RU} {rev['adr']:.0f} ₽, {REVPAR_RU} {rev['revpar']:.0f} ₽ "
                f"(к прошлому периоду {rev_delta})."
                if rev["adr"] is not None and rev["revpar"] is not None
                else f"Недостаточно метрик {ADR_RU} / {REVPAR_RU} в SQLite."
            ),
            recommendations=[
                f"Проверить вклад категорий в {ADR_RU}",
                f"Не демпинговать слишком глубоко — следить за {REVPAR_RU}",
                "Сверить с отчётом TravelLine «Доходность и загрузка»",
            ],
            severity=rev_sev,
            source="travelline",
            period=period,
            detail_payload=rev,
            updated_at=now,
        )
    )

    ch = ctx["channels"]
    direct = float(ch.get("direct_pct") or 0)
    ch_sev = "action" if direct < 30 else ("attention" if direct < 45 else "info")
    cards.append(
        InsightCard(
            topic="channels",
            title=f"Прямые каналы {direct:.0f}%",
            summary=(
                f"Доля прямых бронирований {direct:.1f}%, "
                f"агрегаторы {float(ch.get('aggregator_pct') or 0):.1f}%."
            ),
            recommendations=[
                "Усилить тариф «прямое бронирование» на сайте",
                "Стимулировать повторные визиты без OTA",
                "Проверить паритет цен на агрегаторах",
            ],
            severity=ch_sev,
            source="travelline",
            period=period,
            detail_payload=ch,
            updated_at=now,
        )
    )

    guests = ctx["guests"]
    total_g = int(guests.get("total") or 0)
    ret = int(guests.get("returning") or 0)
    ret_pct = round(ret / total_g * 100, 1) if total_g else 0
    cards.append(
        InsightCard(
            topic="returning_guests",
            title=f"Повторные гости {ret_pct:.0f}%",
            summary=(
                f"В базе {total_g} гостей, повторных {ret} ({ret_pct}%)."
                if total_g
                else "Пока нет статистики гостей в БД."
            ),
            recommendations=[
                "Сегмент «уже проживали» — персональные предложения",
                "Пуш в Max/email повторным гостям",
                "Тариф лояльности на 2+ визит",
            ],
            severity="attention" if total_g and ret_pct < 15 else "info",
            source="travelline",
            period=period,
            detail_payload={"total": total_g, "returning": ret, "returning_pct": ret_pct},
            updated_at=now,
        )
    )

    cards.append(
        InsightCard(
            topic="cancellations",
            title="Отмены: мониторинг",
            summary=(
                "Отдельной метрики отмен в локальной БД пока мало — "
                "сверяйте отмены в TravelLine и добавляйте в отчёт при росте."
            ),
            recommendations=[
                "Смотреть cancelled в Analytics TravelLine еженедельно",
                "Ужесточить правила отмены на пиковые даты",
                "Фиксировать причину отмены в комментарии",
            ],
            severity="info",
            source="travelline",
            period=period,
            detail_payload={},
            updated_at=now,
        )
    )

    als = ctx["als"]
    cards.append(
        InsightCard(
            topic="als",
            title=(
                f"ALS {als['current']:.1f} ночи"
                if als["current"] is not None
                else "Срок проживания: мало данных"
            ),
            summary=(
                f"Средний срок проживания {als['current']:.1f} "
                f"(к прошлому периоду {_delta_label(als['current'], als['previous'])})."
                if als["current"] is not None
                else "Нужны метрики ALS в metrics_daily."
            ),
            recommendations=[
                "Продвигать тарифы 3+ и 7+ ночей",
                "Пакеты для long-stay / корпоративных гостей",
                "Скидка за продление до выезда",
            ],
            severity="info",
            source="travelline",
            period=period,
            detail_payload=als,
            updated_at=now,
        )
    )

    comps = ctx["competitors"]
    with_price = [c for c in comps if c.get("available") and c.get("price_from")]
    if with_price:
        prices = [float(c["price_from"]) for c in with_price]
        avg_p = sum(prices) / len(prices)
        cards.append(
            InsightCard(
                topic="competitors",
                title=f"Конкуренты: средняя «от» {avg_p:.0f} ₽",
                summary=(
                    f"Собраны цены по {len(with_price)} конкурентам из {len(comps)}. "
                    f"Минимум {min(prices):.0f} ₽, максимум {max(prices):.0f} ₽."
                ),
                recommendations=[
                    "Сверить наши «цены от» с минимумом рынка",
                    f"Не опускаться ниже порога {REVPAR_RU} ради загрузки",
                    "Обновлять сбор цен еженедельно",
                ],
                severity="attention",
                source="web",
                period=period,
                detail_payload={"competitors": with_price, "avg": avg_p},
                updated_at=now,
            )
        )
    else:
        cards.append(
            InsightCard(
                topic="competitors",
                title="Конкуренты: цены ещё не собраны",
                summary=(
                    "Нет доступных авто-цен конкурентов — "
                    "запустите сбор или дождитесь планировщика."
                ),
                recommendations=[
                    "Проверить /competitors и static-парсеры",
                    "Сверить вручную 3 ключевых конкурента",
                ],
                severity="info",
                source="web",
                period=period,
                detail_payload={"competitors": comps},
                updated_at=now,
            )
        )

    trends = ctx["trends"]
    if trends:
        top = trends[0]
        cards.append(
            InsightCard(
                topic="market_trends",
                title=f"Тренд: {top['title'][:60]}",
                summary=top.get("takeaway") or top.get("title", ""),
                recommendations=[
                    "Оценить применимость для 1apart на неделе",
                    "Связать с тарифом или сервисом на сайте",
                    "Обсудить на планёрке с управляющим",
                ],
                severity="attention",
                source="web",
                period=period,
                detail_payload={
                    "trends": trends[:5],
                    "sources": [
                        {"title": t["title"], "url": t.get("source_url"), "date": period}
                        for t in trends[:5]
                        if t.get("source_url")
                    ],
                },
                updated_at=now,
            )
        )
    else:
        cards.append(
            InsightCard(
                topic="market_trends",
                title="Тренды рынка: сиды/сбор",
                summary="Лента трендов пуста — загрузите сиды или дождитесь еженедельного сбора.",
                recommendations=["Открыть /trends и обновить сиды", "Проверить RSS в market_news"],
                severity="info",
                source="web",
                period=period,
                detail_payload={},
                updated_at=now,
            )
        )

    cards.append(
        InsightCard(
            topic="regional_demand",
            title="Спрос в Томске: сезонность",
            summary=(
                "Учитывайте вузы, командировки и городские события при планировании цен "
                "на ближайшие 2–3 недели."
            ),
            recommendations=[
                "Календарь событий города в TL за 2–3 недели",
                f"Пиковые выходные — не занижать {ADR_RU} заранее",
                "Будни — пакеты для длительного проживания (business stay)",
            ],
            severity="info",
            source="web",
            period=period,
            detail_payload={
                "sources": [
                    {
                        "title": "Локальная сезонность апарт-отеля",
                        "url": "https://1apart.ru",
                        "date": date.today().isoformat(),
                    }
                ]
            },
            updated_at=now,
        )
    )

    cards.append(
        InsightCard(
            topic="regulation",
            title="Регулирование: следить за требованиями",
            summary=(
                "Для средств размещения важны классификация и учёт гостей — "
                "проверяйте изменения правил на федеральных ресурсах."
            ),
            recommendations=[
                "Сверить статус объекта в реестре",
                "Проверить требования к онлайн-регистрации",
                "Сохранить ссылку на источник в документах объекта",
            ],
            severity="info",
            source="web",
            period=period,
            detail_payload={
                "sources": [
                    {
                        "title": "Федеральная тема размещения",
                        "url": "https://tourism.gov.ru/",
                        "date": date.today().isoformat(),
                    }
                ]
            },
            updated_at=now,
        )
    )
    return cards


def _build_llm_headers(api_key: str, folder_id: str = "") -> dict[str, str]:
    """Заголовки Chat Completions: YandexGPT (Api-Key) или OpenAI (Bearer)."""
    if folder_id:
        return {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Project": folder_id,
        }
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _resolve_llm_settings() -> tuple[str, str, str, str]:
    """api_key, base_url, model, folder_id (LLM_* с фолбэком на OPENAI_*)."""
    env = get_env_settings()
    api_key = (
        (getattr(env, "llm_api_key", "") or "")
        or (getattr(env, "openai_api_key", "") or "")
    ).strip()
    folder_id = (getattr(env, "llm_folder_id", "") or "").strip()
    base_url = (
        (getattr(env, "llm_base_url", "") or "")
        or (getattr(env, "openai_base_url", "") or "")
        or "https://api.openai.com/v1"
    ).strip()
    model = (
        (getattr(env, "llm_model", "") or "")
        or (getattr(env, "openai_model", "") or "")
        or "gpt-4o-mini"
    ).strip()
    if folder_id and "yandex" not in base_url:
        base_url = "https://ai.api.cloud.yandex.net/v1"
    if folder_id and (not model or model == "gpt-4o-mini"):
        model = f"gpt://{folder_id}/yandexgpt-lite/latest"
    return api_key, base_url, model, folder_id


def _call_llm(
    topic: str,
    context: dict[str, Any],
    api_key: str,
    base_url: str,
    model: str,
    folder_id: str = "",
) -> InsightCard | None:
    """Один вызов OpenAI-compatible Chat Completions (YandexGPT / OpenAI)."""
    prompt = (
        "Ты аналитик апарт-отеля 1apart (Томск, 44 кв.). "
        "Пиши ТОЛЬКО по-русски: title, summary и recommendations на русском. "
        "Запрещены английские фразы вроде Occupancy Data, unavailable, Regulation. "
        "Аббревиатуры расшифровывай: "
        f"{ADR_RU}; {REVPAR_RU}; ALS (средний срок проживания). "
        "Загрузку называй «загрузка», не Occupancy. "
        "По контексту верни ТОЛЬКО JSON без markdown:\n"
        '{"title":"...","summary":"1-2 предложения","recommendations":["...","..."],'
        '"severity":"info|attention|action"}\n'
        f"Тема: {topic}\nКонтекст: {json.dumps(context, ensure_ascii=False)[:3500]}"
    )
    url = base_url.rstrip("/") + "/chat/completions"
    headers = _build_llm_headers(api_key, folder_id=folder_id)
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Отвечай только валидным JSON. "
                                "Весь текст полей — строго на русском языке."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                },
            )
        if resp.status_code != 200:
            logger.warning("LLM HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        topic_meta = next((t for t in INSIGHT_TOPICS if t["id"] == topic), {})
        source = "web" if topic_meta.get("group") == "web" else "travelline"
        card = parse_llm_insight_json(content, topic, source, context.get("period", ""))
        # Сбой модели (английский текст) — не сохраняем
        sample = f"{card.title} {card.summary}"
        if looks_mostly_english(sample):
            logger.warning("LLM вернул английский текст для %s — отбрасываем", topic)
            return None
        return card
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM ошибка для %s: %s", topic, exc)
        return None


def generate_insights(period_days: int = 14, use_llm: bool = True) -> list[InsightCard]:
    """Батч-генерация карточек: LLM при наличии ключа, иначе правила."""
    ctx = _collect_context(period_days=period_days)
    api_key, base_url, model, folder_id = _resolve_llm_settings()

    if use_llm and api_key:
        cards: list[InsightCard] = []
        for topic in INSIGHT_TOPICS:
            tid = topic["id"]
            # компактный срез
            slim = {
                "period": ctx["period"],
                "topic": tid,
                "data_sources": ctx.get("data_sources"),
                "occupancy": {
                    "current": ctx["occupancy"].get("current"),
                    "previous": ctx["occupancy"].get("previous"),
                    "source": ctx["occupancy"].get("source"),
                    "by_type": (ctx["occupancy"].get("by_type") or [])[:8],
                    "series": (ctx["occupancy"].get("series") or [])[-14:],
                },
                "revenue": ctx["revenue"],
                "channels": {
                    "direct_pct": ctx["channels"].get("direct_pct"),
                    "aggregator_pct": ctx["channels"].get("aggregator_pct"),
                    "total": ctx["channels"].get("total"),
                    "source": ctx["channels"].get("source"),
                },
                "guests": ctx["guests"],
                "als": ctx["als"],
                "competitors": ctx["competitors"][:5],
                "trends": ctx["trends"][:3],
            }
            card = _call_llm(
                tid, slim, api_key, base_url, model, folder_id=folder_id
            )
            if card is None:
                # подставим rule-based по этой теме
                rules = {c.topic: c for c in _rule_based_cards(ctx)}
                card = rules.get(tid)
            if card is not None:
                if not card.detail_payload:
                    rules = {c.topic: c for c in _rule_based_cards(ctx)}
                    if tid in rules:
                        card.detail_payload = rules[tid].detail_payload
                cards.append(card)
        if cards:
            return cards

    return _rule_based_cards(ctx)


def insight_card_to_record(card: InsightCard) -> InsightRecord:
    return InsightRecord(
        topic=card.topic,
        title=card.title,
        summary=card.summary,
        recommendations=card.recommendations,
        severity=card.severity,
        source=card.source,
        period=card.period,
        detail_payload=card.detail_payload,
        updated_at=card.updated_at,
    )


def run_insights_refresh(period_days: int | None = None) -> int:
    """Пересчитать карточки и заменить кеш в БД.

    period_days: явный период с UI; если None — из settings.analytics.period_days (14).
    """
    cfg = get_config()
    if period_days is None:
        period_days = getattr(getattr(cfg, "analytics", None), "period_days", None) or 14
    days = max(1, min(int(period_days), 365))
    cards = generate_insights(period_days=days, use_llm=True)
    records = [insight_card_to_record(c) for c in cards]
    saved = replace_insights(records)
    logger.info("Аналитика: сохранено %s карточек", saved)
    return saved
