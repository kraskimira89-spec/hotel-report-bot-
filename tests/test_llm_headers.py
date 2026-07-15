"""Тесты заголовков LLM (YandexGPT Api-Key vs OpenAI Bearer)."""

from __future__ import annotations

from src.analytics.ai_insights import _build_llm_headers


def test_yandex_headers_use_api_key_and_project() -> None:
    headers = _build_llm_headers("secret", folder_id="b1gp3rqkf5t6kqmqaf7c")
    assert headers["Authorization"] == "Api-Key secret"
    assert headers["OpenAI-Project"] == "b1gp3rqkf5t6kqmqaf7c"


def test_openai_headers_use_bearer_without_folder() -> None:
    headers = _build_llm_headers("sk-test", folder_id="")
    assert headers["Authorization"] == "Bearer sk-test"
    assert "OpenAI-Project" not in headers
