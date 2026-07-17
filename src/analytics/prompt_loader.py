"""Загрузка промптов из папки prompts/ (правка файлов без изменения кода)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

PromptTask = Literal["numeric", "reviews", "recommendations", "forecast"]

_TASK_FILES: dict[PromptTask, str] = {
    "numeric": "01_numeric_analytics.md",
    "reviews": "02_reviews_classification.md",
    "recommendations": "03_recommendations.md",
    "forecast": "04_forecast.md",
}

_SYSTEM_FILE = "00_system_base.md"

# Кэш: path → (mtime_ns, text)
_cache: dict[str, tuple[int, str]] = {}

_FALLBACK_SYSTEM = (
    "Отвечай только валидным JSON. "
    "Весь текст полей — строго на русском языке. "
    "Квартиры/апартаменты, не гостиничные услуги. "
    "Используй только переданные данные, не выдумывай цифры."
)

_FALLBACK_NUMERIC = (
    "Ты аналитик апарт-отеля 1apart (Томск, 44 кв.). "
    "Пиши ТОЛЬКО по-русски. TravelLine — основной источник, Sheets — резерв."
)

_FALLBACK_FORECAST = (
    "Ты аналитик прогноза апарт-отеля 1apart. "
    "Объясняй прогноз загрузки и рекомендации по ценам только по переданным данным. "
    "На горизонте 6 месяцев — диапазон и сценарии, не точная цифра."
)


def prompts_dir() -> Path:
    """Корень prompts/ относительно корня проекта."""
    return Path(__file__).resolve().parents[2] / "prompts"


def load_prompt_file(filename: str, *, fallback: str = "") -> str:
    """Прочитать markdown-промпт с кэшем по mtime."""
    path = prompts_dir() / filename
    key = str(path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        logger.warning("Промпт не найден: %s — фолбэк", path)
        return fallback
    cached = _cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    text = path.read_text(encoding="utf-8").strip()
    _cache[key] = (mtime, text)
    return text


def clear_prompt_cache() -> None:
    """Сбросить кэш (для тестов)."""
    _cache.clear()


def build_llm_prompt_parts(
    task: PromptTask,
) -> tuple[str, str]:
    """Вернуть (system, task_instructions) = 00_system_base + задачный файл."""
    system = load_prompt_file(_SYSTEM_FILE, fallback=_FALLBACK_SYSTEM)
    task_file = _TASK_FILES[task]
    task_fb = ""
    if task == "numeric":
        task_fb = _FALLBACK_NUMERIC
    elif task == "forecast":
        task_fb = _FALLBACK_FORECAST
    task_text = load_prompt_file(task_file, fallback=task_fb)
    if task == "numeric":
        # Рекомендации в той же карточке insights.
        rec = load_prompt_file(
            _TASK_FILES["recommendations"],
            fallback="",
        )
        if rec:
            task_text = f"{task_text}\n\n---\n{rec}"
    elif task == "forecast":
        # Рекомендации по ценам — в том же контексте прогноза.
        rec = load_prompt_file(
            _TASK_FILES["recommendations"],
            fallback="",
        )
        if rec:
            task_text = f"{task_text}\n\n---\n{rec}"
    return system, task_text
