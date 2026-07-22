"""LLM-карточка отраслевого тренда (опционально)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.analytics.ai_insights import _build_llm_headers, _resolve_llm_settings
from src.analytics.prompt_loader import load_prompt_file
from src.storage.models import TrendRecord

logger = logging.getLogger(__name__)


def generate_trend_card(record: TrendRecord) -> dict[str, str] | None:
    settings = _resolve_llm_settings()
    if not settings.get("api_key"):
        return None
    task = load_prompt_file("06_industry_trends.md", fallback="")
    system = load_prompt_file("00_system_base.md", fallback="Отвечай JSON на русском.")
    payload: dict[str, Any] = {
        "title": record.title,
        "summary": record.summary[:1500],
        "category": record.category,
        "region": record.region,
        "source_name": record.source_name,
        "evidence_level": record.evidence_level,
    }
    user = (
        f"{task}\n\nДанные (JSON):\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "Верни JSON: ai_fact, ai_applicability, ai_risk_opportunity, ai_safe_step"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                f"{settings['base_url']}/chat/completions",
                headers=_build_llm_headers(settings),
                json={
                    "model": settings["model"],
                    "messages": messages,
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(content[start:end])
            return {
                k: str(data[k])
                for k in (
                    "ai_fact",
                    "ai_applicability",
                    "ai_risk_opportunity",
                    "ai_safe_step",
                )
                if k in data and data[k]
            }
    except Exception as exc:
        logger.warning("LLM trend card failed: %s", exc)
    return None
