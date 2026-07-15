"""Тесты русских расшифровок и детекта английского текста."""

from __future__ import annotations

from src.utils.metric_labels import (
    ADR_RU,
    REVPAR_RU,
    expand_metric_abbrs,
    looks_mostly_english,
)


def test_expand_adr_and_revpar() -> None:
    text = "Исследование возможностей для увеличения ADR и RevPAR"
    out = expand_metric_abbrs(text)
    assert ADR_RU in out
    assert REVPAR_RU in out


def test_expand_occupancy_and_dry_run() -> None:
    assert "загрузка" in expand_metric_abbrs("Occupancy Data")
    assert "тестовый режим" in expand_metric_abbrs("Dry-run включён")


def test_expand_idempotent() -> None:
    once = expand_metric_abbrs("Рост ADR и RevPAR")
    assert expand_metric_abbrs(once) == once


def test_looks_mostly_english() -> None:
    assert looks_mostly_english(
        "Occupancy Data for 2026-07-01 — data is currently unavailable"
    )
    assert not looks_mostly_english(
        "Загрузка за период с 01.07 по 15.07 пока недоступна в данных"
    )
