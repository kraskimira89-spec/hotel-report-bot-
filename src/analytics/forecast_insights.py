"""ИИ-комментарий к разделу «Прогноз» (промпты 00 + 04 + 03)."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import httpx

from src.analytics.ai_insights import _build_llm_headers, _resolve_llm_settings
from src.analytics.prompt_loader import build_llm_prompt_parts
from src.config import get_config

logger = logging.getLogger(__name__)


def _slim_forecast_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    """Компактный JSON для LLM без лишних полей UI."""
    filters = bundle.get("filters") or {}
    kpi = bundle.get("kpi") or {}
    series = bundle.get("series") or []
    recs = bundle.get("recommendations") or []
    return {
        "horizon_days": filters.get("horizon_days"),
        "scenario": filters.get("scenario"),
        "room_type": filters.get("room_type") or "all",
        "run": bundle.get("run"),
        "kpi": kpi,
        "confidence": kpi.get("confidence"),
        "factors": bundle.get("factors") or {},
        "series_sample": series[: min(len(series), 14)],
        "series_count": len(series),
        "recommendations_top": recs[:8],
        "recommendations_count": len(recs),
        "quality": bundle.get("quality"),
        "competitor_median": bundle.get("competitor_median"),
    }


def build_forecast_llm_messages(bundle: dict[str, Any]) -> list[dict[str, str]]:
    """Собрать messages: 00_system_base + 04_forecast (+ 03_recommendations)."""
    system, task = build_llm_prompt_parts("forecast")
    payload = _slim_forecast_payload(bundle)
    user = (
        f"{task}\n\n"
        "Верни ответ строго в текстовом формате из промпта (блоки Период / Вывод / …).\n"
        f"Данные прогноза (JSON):\n"
        f"{json.dumps(payload, ensure_ascii=False)[:12000]}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _rule_based_forecast_comment(bundle: dict[str, Any]) -> str:
    """Фолбэк без LLM."""
    kpi = bundle.get("kpi") or {}
    filters = bundle.get("filters") or {}
    horizon = filters.get("horizon_days", 7)
    scenario = filters.get("scenario", "base")
    occ = kpi.get("occupancy_pct")
    rev = kpi.get("revenue")
    conf = bundle.get("confidence_label") or kpi.get("confidence", "medium")
    recs = bundle.get("recommendations") or []
    lines = [
        f"Период: горизонт {horizon} дн., сценарий {scenario}",
        "Вывод: прогноз рассчитан детерминированной моделью по накопленной истории.",
    ]
    if occ is not None:
        if horizon >= 180:
            lines.append(
                f"Прогноз: средняя загрузка ~{occ}% (для 6 мес. смотрите диапазон на графике и сценарии)"
            )
        else:
            lines.append(f"Прогноз: загрузка ~{occ}%")
    if rev is not None:
        lines.append(f"Выручка за период (сумма): ~{int(rev):,} ₽".replace(",", " "))
    lines.append(f"Уверенность: {conf}")
    if recs:
        top = recs[0]
        lines.append(
            f"Цены: {top.get('type_label', 'рекомендация')} — {top.get('room_label', '')} "
            f"на {top.get('target_date', '')}"
        )
    else:
        lines.append("Цены: нет активных рекомендаций")
    factors = bundle.get("factors") or {}
    notes = factors.get("notes") or []
    if notes:
        lines.append(f"Внимание: {notes[0]}")
    return "\n".join(lines)


def generate_forecast_commentary(
    bundle: dict[str, Any],
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Сгенерировать текстовый комментарий к странице /forecast."""
    cfg = get_config()
    if not cfg.forecast.enabled:
        return {"source": "disabled", "text": ""}

    if not use_llm:
        return {"source": "rules", "text": _rule_based_forecast_comment(bundle)}

    api_key, base_url, model, folder_id = _resolve_llm_settings()
    if not api_key:
        return {"source": "rules", "text": _rule_based_forecast_comment(bundle)}

    messages = build_forecast_llm_messages(bundle)
    url = base_url.rstrip("/") + "/chat/completions"
    headers = _build_llm_headers(api_key, folder_id=folder_id)
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                },
            )
        if resp.status_code != 200:
            logger.warning("Forecast LLM HTTP %s: %s", resp.status_code, resp.text[:200])
            return {"source": "rules", "text": _rule_based_forecast_comment(bundle)}
        content = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        if not content:
            return {"source": "rules", "text": _rule_based_forecast_comment(bundle)}
        return {"source": "llm", "text": content}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Forecast LLM ошибка: %s", exc)
        return {"source": "rules", "text": _rule_based_forecast_comment(bundle)}


def forecast_period_label(bundle: dict[str, Any]) -> str:
    """Подпись периода для UI."""
    series = bundle.get("series") or []
    filters = bundle.get("filters") or {}
    horizon = filters.get("horizon_days", 7)
    if not series:
        return f"горизонт {horizon} дн. (с {date.today():%d.%m.%Y})"
    start = series[0].get("date_label", "")
    end = series[-1].get("date_label", "")
    return f"{start}–{end} (горизонт {horizon} дн.)"
