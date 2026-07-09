"""Тесты Max Bot API client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from src.config import MaxBotConfig
from src.notifiers.max_api import (
    MaxApiClient,
    discover_chat_ids,
    parse_updates,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/me"):
            return _FakeResponse(
                200,
                {
                    "user_id": 1,
                    "name": "Bot",
                    "username": "bot",
                    "is_bot": True,
                },
            )
        if url.endswith("/messages"):
            return _FakeResponse(200, {"message": {"body": {"text": kwargs["json"]["text"]}}})
        return _FakeResponse(200, {"updates": [], "marker": None})


@pytest.fixture
def api_client() -> MaxApiClient:
    cfg = MaxBotConfig(
        max_retries=1,
        backoff_initial_sec=0.01,
        backoff_max_sec=0.02,
    )
    return MaxApiClient("test-token", config=cfg, transport=_FakeTransport())


def test_get_me(api_client: MaxApiClient) -> None:
    info = api_client.get_me()
    assert info.user_id == 1
    assert info.is_bot is True


def test_send_message_uses_query_chat_id(api_client: MaxApiClient) -> None:
    api_client.send_message("hello", chat_id=364502022)
    transport = api_client._transport
    assert isinstance(transport, _FakeTransport)
    call = transport.calls[-1]
    assert call["method"] == "POST"
    assert call["params"]["chat_id"] == 364502022
    assert call["json"] == {"text": "hello", "format": "markdown"}
    assert call["headers"]["Authorization"] == "test-token"


def test_discover_chat_ids_from_updates() -> None:
    payload = {
        "updates": [
            {"update_type": "bot_started", "chat_id": 111},
            {
                "update_type": "message_created",
                "message": {"recipient": {"chat_id": 222}},
            },
        ]
    }
    assert discover_chat_ids(payload) == [111, 222]
    assert len(parse_updates(payload)) == 2
