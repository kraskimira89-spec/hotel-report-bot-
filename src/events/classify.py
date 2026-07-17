"""Классификация категории события: ИИ + правила-фолбэк."""

from __future__ import annotations

import json
import logging
import re

import httpx

from src.events.normalize import infer_category

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = frozenset(
    {
        "conference",
        "business",
        "concert",
        "sport",
        "festival",
        "fair",
        "exhibition",
        "holiday",
        "city_holiday",
        "other",
    }
)

_CATEGORY_HINTS_RU = {
    "conference": "конференция, форум, сессия, круглый стол",
    "business": "бизнес, семинар, обучение предпринимателей, мой бизнес",
    "concert": "концерт, филармония, оркестр, музыка, стендап",
    "sport": "спорт, матч, турнир, марафон, забег, чемпионат",
    "festival": "фестиваль, сабантуй, праздник топора",
    "fair": "ярмарка",
    "exhibition": "выставка, экспо",
    "holiday": "праздник, выходные",
    "city_holiday": "день города, масленица, день победы, новый год",
    "other": "другое / не подходит",
}


def _normalize_ai_category(raw: str) -> str | None:
    text = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    # иногда модель возвращает русскую метку
    ru_map = {
        "конференция": "conference",
        "бизнес": "business",
        "концерт": "concert",
        "спорт": "sport",
        "фестиваль": "festival",
        "ярмарка": "fair",
        "выставка": "exhibition",
        "праздник": "holiday",
        "городской_праздник": "city_holiday",
        "городскои_праздник": "city_holiday",
        "другое": "other",
        "театр": "concert",
        "спектакль": "concert",
    }
    if text in ALLOWED_CATEGORIES:
        return text
    if text in ru_map:
        return ru_map[text]
    m = re.search(r"[a-z_]+", text)
    if m and m.group(0) in ALLOWED_CATEGORIES:
        return m.group(0)
    return None


def classify_category_rules(
    title: str,
    description: str | None = None,
    venue: str | None = None,
) -> str:
    return infer_category(title, f"{description or ''} {venue or ''}")


def classify_category_llm(
    title: str,
    description: str | None = None,
    venue: str | None = None,
) -> str | None:
    """Один вызов LLM. None — нет ключа / ошибка / невалидный ответ."""
    from src.analytics.ai_insights import _build_llm_headers, _resolve_llm_settings

    api_key, base_url, model, folder_id = _resolve_llm_settings()
    if not api_key:
        return None

    hints = "\n".join(f"- {k}: {v}" for k, v in _CATEGORY_HINTS_RU.items())
    user_prompt = (
        "Определи категорию городского события для отеля в Томске.\n"
        f"Допустимые id категорий:\n{hints}\n\n"
        f"Название: {title}\n"
        f"Описание: {description or '—'}\n"
        f"Площадка: {venue or '—'}\n\n"
        'Ответь ТОЛЬКО JSON: {"category":"<id>"} без markdown.'
    )
    url = base_url.rstrip("/") + "/chat/completions"
    headers = _build_llm_headers(api_key, folder_id=folder_id)
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Ты классификатор афиши. Выбирай одну категорию из списка. "
                                "Отвечай только JSON."
                            ),
                        },
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                },
            )
        if resp.status_code != 200:
            logger.warning("LLM category HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)
        return _normalize_ai_category(str(data.get("category", "")))
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM category error: %s", exc)
        return None


def classify_event_category(
    title: str,
    description: str | None = None,
    venue: str | None = None,
    *,
    use_llm: bool = True,
    hint: str | None = None,
) -> tuple[str, str]:
    """Вернуть (category, source) где source = llm|rules|parser."""
    if hint and hint != "other" and hint in ALLOWED_CATEGORIES:
        # Парсер уже уверен — оставляем, но уточняем ИИ только для other
        return hint, "parser"
    if use_llm:
        ai = classify_category_llm(title, description, venue)
        if ai:
            return ai, "llm"
    rules = classify_category_rules(title, description, venue)
    return rules, "rules"
