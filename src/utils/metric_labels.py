"""Русские подписи отельных метрик и проверка языка текстов."""

from __future__ import annotations

import re

# Аббревиатуры с русской расшифровкой (в текстах отчётов).
ADR_RU = "ADR (средняя цена номера за сутки)"
REVPAR_RU = "RevPAR (доход на доступный номер)"
ALS_RU = "ALS (средний срок проживания)"
OCCUPANCY_RU = "загрузка"
DRY_RUN_RU = "тестовый режим"

_WORD_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bRevPAR\b(?!\s*\()", re.IGNORECASE), REVPAR_RU),
    (re.compile(r"\bADR\b(?!\s*\()", re.IGNORECASE), ADR_RU),
    (re.compile(r"\bALS\b(?!\s*\()", re.IGNORECASE), ALS_RU),
    (re.compile(r"\bOccupancy\b", re.IGNORECASE), OCCUPANCY_RU),
    (re.compile(r"\bOcc\.?\b(?=\s*%|\s*$|[,\s])", re.IGNORECASE), OCCUPANCY_RU),
    (re.compile(r"\bDry[- ]?run\b", re.IGNORECASE), DRY_RUN_RU),
    (re.compile(r"\bSnapshot\b", re.IGNORECASE), "снимок"),
]


def expand_metric_abbrs(text: str) -> str:
    """Подставить русские расшифровки к метрикам и частым англ. словам."""
    if not text:
        return text
    out = text
    for pattern, repl in _WORD_MAP:
        out = pattern.sub(repl, out)
    return out


def expand_metric_abbrs_list(items: list[str] | None) -> list[str]:
    """Раскрыть аббревиатуры в списке строк."""
    if not items:
        return []
    return [expand_metric_abbrs(str(x)) for x in items]


def looks_mostly_english(text: str) -> bool:
    """True, если в тексте преобладает латиница (типичный сбой LLM)."""
    if not text or not text.strip():
        return False
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    if len(letters) < 8:
        return False
    latin = sum(1 for c in letters if ("A" <= c <= "Z") or ("a" <= c <= "z"))
    return (latin / len(letters)) >= 0.55
