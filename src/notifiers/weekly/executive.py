"""Executive summary для weekly email."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.analytics.ai_insights import _build_llm_headers, _resolve_llm_settings
from src.analytics.prompt_loader import load_prompt_file, load_prompt_file as _load
from src.notifiers.weekly.models import ExecutiveSummary, WeeklyReportData

logger = logging.getLogger(__name__)


def _rule_based_executive(data: WeeklyReportData) -> ExecutiveSummary:
    cur = data.current_metrics
    prev = data.prev_week_metrics
    parts: list[str] = []
    if cur and cur.occupancy_pct is not None:
        if prev and prev.occupancy_pct is not None:
            delta = cur.occupancy_pct - prev.occupancy_pct
            direction = "выросла" if delta > 0 else "снизилась" if delta < 0 else "стабильна"
            parts.append(f"Загрузка {direction} на {abs(delta):.1f} п.п.")
        else:
            parts.append(f"Средняя загрузка за неделю {cur.occupancy_pct:.1f}%.")
    if data.direct_share_pct is not None and prev and data.prev_week_metrics:
        parts.append(f"Прямые брони: {data.direct_share_pct:.1f}%.")
    headline = (
        " ".join(parts) if parts else "Неделя завершена; ключевые метрики собраны из TravelLine."
    )
    action = "Проверить прогноз на 14 дней и приоритетные рекомендации в админке."
    if data.priority_recommendations:
        action = data.priority_recommendations[0].title
    conf = data.data_quality.overall or "средняя"
    return ExecutiveSummary(headline=headline, main_action=action, confidence_label=conf)


def build_executive_summary(
    data: WeeklyReportData,
    *,
    use_llm: bool = True,
) -> ExecutiveSummary:
    fallback = _rule_based_executive(data)
    if not use_llm:
        return fallback
    settings = _resolve_llm_settings()
    if not settings.get("api_key"):
        return fallback
    task = load_prompt_file("05_weekly_executive.md", fallback="")
    payload: dict[str, Any] = {
        "period": f"{data.period_start} — {data.period_end}",
        "kpi_cards": [c.model_dump() for c in data.kpi_cards[:6]],
        "impact_factors": [f.model_dump() for f in data.impact_factors[:4]],
        "forecast": data.forecast_next_14_days.model_dump(),
        "recommendations": [r.title for r in data.priority_recommendations],
        "events": [e.title for e in data.city_events],
        "data_quality": data.data_quality.model_dump(),
    }
    system = _load("00_system_base.md", fallback="Отвечай JSON на русском.")
    user = f"{task}\n\nДанные:\n{json.dumps(payload, ensure_ascii=False, default=str)[:8000]}"
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                f"{settings['base_url']}/chat/completions",
                headers=_build_llm_headers(settings),
                json={
                    "model": settings["model"],
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        start, end = content.find("{"), content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
            return ExecutiveSummary(
                headline=str(parsed.get("headline") or fallback.headline),
                main_action=str(parsed.get("main_action") or fallback.main_action),
                confidence_label=str(
                    parsed.get("confidence_label") or fallback.confidence_label
                ),
            )
    except Exception as exc:
        logger.warning("Executive LLM fallback: %s", exc)
    return fallback
