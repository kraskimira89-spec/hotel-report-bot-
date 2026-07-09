"""Клиент Max Bot API (https://dev.max.ru/docs-api)."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from src.config import AppConfig, MaxBotConfig, get_config, get_env_settings
from src.utils.retry import retry_with_backoff
from src.utils.ssl_certs import get_max_api_verify

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {401, 403, 429, 500, 502, 503, 504}
DEFAULT_UPDATE_TYPES = ("bot_started", "message_created", "bot_added")


class BotInfo(BaseModel):
    """Ответ GET /me."""

    user_id: int
    name: str = ""
    username: str = ""
    is_bot: bool = True
    last_activity_time: int | None = None


class MaxUpdate(BaseModel):
    """Элемент списка updates (упрощённо)."""

    update_type: str = ""
    chat_id: int | None = None
    user_id: int | None = None
    timestamp: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class HttpTransport(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


class MaxApiClient:
    """HTTPS-клиент platform-api2.max.ru."""

    def __init__(
        self,
        token: str,
        config: MaxBotConfig | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        cfg = config or get_config().max_bot
        self._token = token.strip()
        self._cfg = cfg
        self._base = cfg.api_url.rstrip("/")
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._token,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self._base}{path}"

        def _call() -> httpx.Response:
            if self._transport is not None:
                resp = self._transport.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=self._headers(),
                    timeout=30.0,
                )
            else:
                resp = httpx.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=self._headers(),
                    timeout=30.0,
                    verify=get_max_api_verify(),
                )
            if resp.status_code in RETRYABLE_STATUS:
                resp.raise_for_status()
            return resp

        resp = retry_with_backoff(
            _call,
            retries=self._cfg.max_retries,
            backoff_initial=self._cfg.backoff_initial_sec,
            backoff_max=self._cfg.backoff_max_sec,
            retry_statuses=RETRYABLE_STATUS,
            log_prefix="max_api",
        )
        resp.raise_for_status()
        return resp

    def get_me(self) -> BotInfo:
        """GET /me — информация о боте."""
        data = self._request("GET", "/me").json()
        return BotInfo.model_validate(data)

    def send_message(
        self,
        text: str,
        *,
        chat_id: int | str | None = None,
        user_id: int | str | None = None,
        format: str = "markdown",
        notify: bool | None = None,
    ) -> dict[str, Any]:
        """POST /messages — chat_id/user_id в query, тело NewMessageBody."""
        params: dict[str, Any] = {}
        if chat_id is not None:
            params["chat_id"] = int(chat_id)
        if user_id is not None:
            params["user_id"] = int(user_id)
        body: dict[str, Any] = {"text": text, "format": format}
        if notify is not None:
            body["notify"] = notify
        return self._request("POST", "/messages", params=params, json=body).json()

    def get_updates(
        self,
        *,
        limit: int = 100,
        timeout: int = 30,
        marker: int | None = None,
        types: list[str] | None = None,
    ) -> dict[str, Any]:
        """GET /updates — Long Polling (для dev/тестов)."""
        params: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        return self._request("GET", "/updates", params=params).json()

    def list_subscriptions(self) -> dict[str, Any]:
        """GET /subscriptions."""
        return self._request("GET", "/subscriptions").json()

    def create_subscription(
        self,
        url: str,
        *,
        update_types: list[str] | None = None,
        secret: str | None = None,
    ) -> dict[str, Any]:
        """POST /subscriptions — webhook (production)."""
        body: dict[str, Any] = {
            "url": url,
            "update_types": list(update_types or DEFAULT_UPDATE_TYPES),
        }
        if secret:
            body["secret"] = secret
        return self._request("POST", "/subscriptions", json=body).json()

    def delete_subscription(self, url: str) -> dict[str, Any]:
        """DELETE /subscriptions — отписка webhook."""
        return self._request(
            "DELETE",
            "/subscriptions",
            params={"url": url},
        ).json()


def build_max_api_client(config: AppConfig | None = None) -> MaxApiClient | None:
    """Создать клиент, если задан MAX_TOKEN."""
    env = get_env_settings()
    if not env.max_token.strip():
        return None
    cfg = config or get_config()
    return MaxApiClient(env.max_token, config=cfg.max_bot)


def parse_updates(payload: dict[str, Any]) -> list[MaxUpdate]:
    """Разобрать ответ GET /updates или webhook body."""
    items: list[MaxUpdate] = []
    for raw in payload.get("updates", []):
        if not isinstance(raw, dict):
            continue
        items.append(
            MaxUpdate(
                update_type=str(raw.get("update_type", "")),
                chat_id=raw.get("chat_id"),
                user_id=raw.get("user_id"),
                timestamp=raw.get("timestamp"),
                raw=raw,
            )
        )
    return items


def discover_chat_ids(payload: dict[str, Any]) -> list[int]:
    """Извлечь chat_id из updates (bot_started, message_created и т.д.)."""
    ids: list[int] = []
    for upd in parse_updates(payload):
        if upd.chat_id is not None:
            ids.append(int(upd.chat_id))
            continue
        message = upd.raw.get("message")
        if isinstance(message, dict):
            recipient = message.get("recipient") or {}
            chat_id = recipient.get("chat_id")
            if chat_id is not None:
                ids.append(int(chat_id))
    return list(dict.fromkeys(ids))
