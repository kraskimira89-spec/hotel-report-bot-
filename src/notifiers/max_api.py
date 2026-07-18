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
DEFAULT_UPDATE_TYPES = (
    "bot_started",
    "message_created",
    "message_callback",
    "bot_added",
)

# Команды бота (меню «/» и кнопка «Начать» в клиенте Max)
DEFAULT_BOT_COMMANDS: list[dict[str, str]] = [
    {"name": "start", "description": "Начать"},
    {"name": "help", "description": "Справка"},
    {"name": "stop", "description": "Отключить уведомления"},
]


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

    def patch_me(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        commands: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """PATCH /me — имя, описание, меню команд (кнопка «Начать»)."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if commands is not None:
            body["commands"] = commands
        data = self._request("PATCH", "/me", json=body).json()
        return data if isinstance(data, dict) else {"value": data}

    def set_my_commands(
        self,
        commands: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Зарегистрировать команды бота (start → «Начать» в клиенте)."""
        return self.patch_me(commands=list(commands or DEFAULT_BOT_COMMANDS))

    def send_message(
        self,
        text: str,
        *,
        chat_id: int | str | None = None,
        user_id: int | str | None = None,
        format: str = "markdown",
        notify: bool | None = None,
        attachments: list[dict[str, Any]] | None = None,
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
        if attachments:
            body["attachments"] = attachments
        data = self._request("POST", "/messages", params=params, json=body).json()
        return data if isinstance(data, dict) else {"value": data}

    def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /answers — ответ на message_callback."""
        params = {"callback_id": callback_id}
        body: dict[str, Any] = {}
        if notification is not None:
            body["notification"] = notification
        if message is not None:
            body["message"] = message
        if not body:
            body["notification"] = "OK"
        data = self._request("POST", "/answers", params=params, json=body).json()
        return data if isinstance(data, dict) else {"value": data}

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
        data = self._request("GET", "/updates", params=params).json()
        return data if isinstance(data, dict) else {"value": data}

    def list_subscriptions(self) -> dict[str, Any]:
        """GET /subscriptions."""
        data = self._request("GET", "/subscriptions").json()
        return data if isinstance(data, dict) else {"value": data}

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
        data = self._request("POST", "/subscriptions", json=body).json()
        return data if isinstance(data, dict) else {"value": data}

    def delete_subscription(self, url: str) -> dict[str, Any]:
        """DELETE /subscriptions — отписка webhook."""
        data = self._request(
            "DELETE",
            "/subscriptions",
            params={"url": url},
        ).json()
        return data if isinstance(data, dict) else {"value": data}


def build_max_api_client(config: AppConfig | None = None) -> MaxApiClient | None:
    """Создать клиент, если задан MAX_TOKEN."""
    env = get_env_settings()
    if not env.max_token.strip():
        return None
    cfg = config or get_config()
    return MaxApiClient(env.max_token, config=cfg.max_bot)


def normalize_updates_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Webhook шлёт один Update; long polling — {updates: [...]}."""
    if "updates" in payload:
        return payload
    if payload.get("update_type"):
        return {"updates": [payload]}
    return payload


def parse_updates(payload: dict[str, Any]) -> list[MaxUpdate]:
    """Разобрать ответ GET /updates или webhook body."""
    normalized = normalize_updates_payload(payload)
    items: list[MaxUpdate] = []
    for raw in normalized.get("updates", []):
        if not isinstance(raw, dict):
            continue
        update_type = str(raw.get("update_type", ""))
        user_id = raw.get("user_id")
        chat_id = raw.get("chat_id")
        user = raw.get("user")
        if isinstance(user, dict) and user_id is None:
            user_id = user.get("user_id")

        callback = raw.get("callback")
        # message_callback: человек в callback.user (не в message.sender — там бот)
        if update_type == "message_callback" and isinstance(callback, dict):
            cb_user = callback.get("user") or {}
            if isinstance(cb_user, dict) and cb_user.get("user_id") is not None:
                user_id = cb_user.get("user_id")
            # chat_id часто в message.recipient
            message = raw.get("message")
            if isinstance(message, dict) and chat_id is None:
                recipient = message.get("recipient") or {}
                if isinstance(recipient, dict) and recipient.get("chat_id") is not None:
                    chat_id = recipient.get("chat_id")
                # иногда chat_id = user_id диалога
                if chat_id is None and user_id is not None:
                    chat_id = user_id
        else:
            message = raw.get("message")
            if isinstance(message, dict):
                if chat_id is None:
                    recipient = message.get("recipient") or {}
                    if isinstance(recipient, dict) and recipient.get("chat_id") is not None:
                        chat_id = recipient.get("chat_id")
                if user_id is None:
                    sender = message.get("sender") or {}
                    if isinstance(sender, dict):
                        user_id = sender.get("user_id")
            if isinstance(callback, dict) and user_id is None:
                cb_user = callback.get("user") or {}
                if isinstance(cb_user, dict):
                    user_id = cb_user.get("user_id")

        items.append(
            MaxUpdate(
                update_type=update_type,
                chat_id=int(chat_id) if chat_id is not None else None,
                user_id=int(user_id) if user_id is not None else None,
                timestamp=raw.get("timestamp"),
                raw=raw,
            )
        )
    return items


def extract_message_text(raw: dict[str, Any]) -> str:
    message = raw.get("message")
    if not isinstance(message, dict):
        return ""
    body = message.get("body")
    if isinstance(body, dict):
        return str(body.get("text") or "")
    return str(message.get("text") or "")


def extract_display_name(raw: dict[str, Any]) -> str:
    for key in ("user",):
        obj = raw.get(key)
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("first_name") or ""
            if name:
                return str(name)
    message = raw.get("message")
    if isinstance(message, dict):
        sender = message.get("sender") or {}
        if isinstance(sender, dict):
            name = sender.get("name") or sender.get("first_name") or ""
            if name:
                return str(name)
    callback = raw.get("callback")
    if isinstance(callback, dict):
        user = callback.get("user") or {}
        if isinstance(user, dict):
            name = user.get("name") or user.get("first_name") or ""
            if name:
                return str(name)
    return ""


def extract_callback(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    """Вернуть (callback_id, payload)."""
    callback = raw.get("callback")
    if not isinstance(callback, dict):
        return None, None
    callback_id = callback.get("callback_id")
    payload = callback.get("payload")
    if payload is None:
        # иногда payload лежит в attachment
        payload = raw.get("payload")
    return (
        str(callback_id) if callback_id else None,
        str(payload) if payload is not None else None,
    )


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
