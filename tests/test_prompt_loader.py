"""Тесты загрузки промптов из prompts/."""

from __future__ import annotations

from src.analytics.prompt_loader import (
    build_llm_prompt_parts,
    clear_prompt_cache,
    load_prompt_file,
    prompts_dir,
)
from src.analytics.reviews_insights import build_reviews_llm_messages


def test_prompts_dir_exists() -> None:
    assert prompts_dir().is_dir()
    assert (prompts_dir() / "00_system_base.md").is_file()


def test_load_system_base_contains_travelline() -> None:
    clear_prompt_cache()
    text = load_prompt_file("00_system_base.md")
    assert "TravelLine" in text
    assert "квартир" in text.lower()


def test_build_numeric_parts() -> None:
    clear_prompt_cache()
    system, task = build_llm_prompt_parts("numeric")
    assert "достоверности" in system.lower() or "TravelLine" in system
    assert "загрузка" in task.lower() or "ADR" in task
    assert "Рекомендац" in task or "рекомендац" in task.lower()


def test_reviews_messages_use_prompts() -> None:
    clear_prompt_cache()
    msgs = build_reviews_llm_messages({"reviews": []})
    assert msgs[0]["role"] == "system"
    assert "TravelLine" in msgs[0]["content"] or "квартир" in msgs[0]["content"].lower()
    assert msgs[1]["role"] == "user"
    assert "категор" in msgs[1]["content"].lower() or "отзыв" in msgs[1]["content"].lower()
    # Явный период сравнения (как в 01_numeric_analytics).
    assert "Период:" in msgs[1]["content"]
    assert "сравнение недоступно" in msgs[1]["content"].lower()


def test_load_prompt_fallback_when_missing(tmp_path, monkeypatch) -> None:
    clear_prompt_cache()
    fake_dir = tmp_path / "prompts"
    fake_dir.mkdir()
    monkeypatch.setattr(
        "src.analytics.prompt_loader.prompts_dir",
        lambda: fake_dir,
    )
    text = load_prompt_file("missing.md", fallback="fallback-text")
    assert text == "fallback-text"
