"""Классификация отзывов через YandexGPT (промпты из prompts/).

Полный пайплайн сбора отзывов — Issue #15/#16. Здесь — загрузка промптов
и заготовка вызова LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from src.analytics.prompt_loader import build_llm_prompt_parts

logger = logging.getLogger(__name__)


def build_reviews_llm_messages(
    reviews_payload: dict[str, Any] | list[Any] | str,
) -> list[dict[str, str]]:
    """Собрать messages для классификации отзывов: 00 + 02."""
    import json

    system, task = build_llm_prompt_parts("reviews")
    if isinstance(reviews_payload, str):
        payload_text = reviews_payload
    else:
        payload_text = json.dumps(reviews_payload, ensure_ascii=False)[:8000]
    user = (
        f"{task}\n\n"
        "Верни ТОЛЬКО валидный JSON без markdown.\n"
        f"Данные отзывов:\n{payload_text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def reviews_system_prompt() -> str:
    """System-часть для отзывов (тесты / отладка)."""
    system, _ = build_llm_prompt_parts("reviews")
    return system
