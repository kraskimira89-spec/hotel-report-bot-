"""Маршрутизация команд и callback внутреннего бота Max."""

from __future__ import annotations

import logging
from typing import Any

from src.config import AppConfig, get_config
from src.notifiers.max_api import MaxApiClient, build_max_api_client
from src.staff_bot import handlers
from src.staff_bot.acl import DENIED_TEXT, check_access
from src.staff_bot.templates import resolve_command
from src.storage.db import save_staff_command_log
from src.storage.models import StaffCommandLogRecord

logger = logging.getLogger(__name__)


def _send(
    api: MaxApiClient,
    *,
    chat_id: int | None,
    user_id: int | None,
    text: str,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    kwargs: dict[str, Any] = {"format": "markdown"}
    if attachments:
        kwargs["attachments"] = attachments
    # Предпочитаем chat_id: user_id из callback иногда путают с id бота
    last_exc: Exception | None = None
    if chat_id is not None:
        try:
            api.send_message(text, chat_id=chat_id, **kwargs)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("staff_bot send chat_id=%s failed: %s", chat_id, exc)
    if user_id is not None:
        try:
            api.send_message(text, user_id=user_id, **kwargs)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("staff_bot send user_id=%s failed: %s", user_id, exc)
    if last_exc is not None:
        raise last_exc
    logger.warning("staff_bot: нет chat_id/user_id для ответа")


def _log(user_id: int | None, command: str, status: str, detail: str | None = None) -> None:
    if user_id is None:
        return
    try:
        save_staff_command_log(
            StaffCommandLogRecord(
                user_id=int(user_id),
                command=command,
                status=status,
                detail=detail,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("staff_command_log: %s", exc)


def handle_first_connect(
    *,
    user_id: int | None,
    chat_id: int | None,
    display_name: str = "",
    config: AppConfig | None = None,
    api: MaxApiClient | None = None,
    callback_id: str | None = None,
) -> dict[str, Any]:
    """Первое подключение: про 9:00 + кнопки «сводка сейчас» / «ждать»."""
    cfg = config or get_config()
    client = api or build_max_api_client(cfg)
    if client is None:
        return {"ok": False, "reason": "no_max_token"}

    # Всегда одно и то же приветствие с выбором (staff/гость)
    reply = handlers.reply_first_connect(display_name)
    _send(
        client,
        chat_id=chat_id,
        user_id=user_id,
        text=reply["text"],
        attachments=reply.get("attachments") or None,
    )
    access = check_access(user_id, "start", config=cfg)
    _log(
        user_id,
        "start",
        "ok",
        "staff" if access.allowed else "first_connect_guest",
    )
    if callback_id:
        try:
            client.answer_callback(callback_id, notification="Готово")
        except Exception as exc:  # noqa: BLE001
            logger.debug("answer_callback start: %s", exc)
    return {"ok": True, "command": "start", "staff": bool(access.allowed)}


def handle_onboarding_choice(
    choice: str,
    *,
    user_id: int | None,
    chat_id: int | None,
    config: AppConfig | None = None,
    api: MaxApiClient | None = None,
    callback_id: str | None = None,
) -> dict[str, Any]:
    """Обработка кнопок после приветствия."""
    cfg = config or get_config()
    client = api or build_max_api_client(cfg)
    if client is None:
        return {"ok": False, "reason": "no_max_token"}

    try:
        if choice in ("wait_9", "wait_until_9"):
            reply = handlers.reply_wait_until_9()
            _send(client, chat_id=chat_id, user_id=user_id, text=reply["text"])
            _log(user_id, "wait_until_9", "ok")
            if callback_id:
                try:
                    client.answer_callback(callback_id, notification="Ждём 9:00")
                except Exception as exc:  # noqa: BLE001
                    logger.debug("answer_callback wait: %s", exc)
            return {"ok": True, "command": "wait_until_9"}

        reply = handlers.reply_summary(config=cfg)
        _send(client, chat_id=chat_id, user_id=user_id, text=reply["text"])
        _log(user_id, "send_last_summary", "ok")
        if callback_id:
            try:
                client.answer_callback(callback_id, notification="Сводка отправлена")
            except Exception as exc:  # noqa: BLE001
                logger.debug("answer_callback summary: %s", exc)
        return {"ok": True, "command": "send_last_summary"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("onboarding choice failed: %s", exc)
        _log(user_id, choice, "error", str(exc)[:500])
        try:
            _send(
                client,
                chat_id=chat_id,
                user_id=user_id,
                text="Не удалось отправить сводку. Попробуйте ещё раз или напишите /start.",
            )
        except Exception:  # noqa: BLE001
            pass
        if callback_id:
            try:
                client.answer_callback(callback_id, notification="Ошибка")
            except Exception:  # noqa: BLE001
                pass
        return {"ok": False, "error": str(exc)}


def handle_staff_command(
    *,
    command: str,
    user_id: int | None,
    chat_id: int | None,
    display_name: str = "",
    config: AppConfig | None = None,
    api: MaxApiClient | None = None,
    callback_id: str | None = None,
    payload_extra: str | None = None,
) -> dict[str, Any]:
    """Обработать команду/кнопку. Возвращает статус для webhook."""
    if command == "start":
        return handle_first_connect(
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            config=config,
            api=api,
            callback_id=callback_id,
        )
    if command in ("send_last_summary", "wait_until_9"):
        choice = "send_last" if command == "send_last_summary" else "wait_9"
        return handle_onboarding_choice(
            choice,
            user_id=user_id,
            chat_id=chat_id,
            config=config,
            api=api,
            callback_id=callback_id,
        )

    cfg = config or get_config()
    client = api or build_max_api_client(cfg)
    if client is None:
        return {"ok": False, "reason": "no_max_token"}

    access = check_access(user_id, command, config=cfg)
    if not access.allowed:
        _log(user_id, command, "denied", access.reason)
        if user_id is not None or chat_id is not None:
            _send(client, chat_id=chat_id, user_id=user_id, text=DENIED_TEXT)
        if callback_id:
            try:
                client.answer_callback(callback_id, notification=DENIED_TEXT)
            except Exception as exc:  # noqa: BLE001
                logger.debug("answer_callback denied: %s", exc)
        return {"ok": True, "denied": True, "reason": access.reason}

    staff = access.staff
    assert staff is not None
    if display_name and not staff.display_name:
        staff = staff.model_copy(update={"display_name": display_name})

    try:
        if command == "help":
            reply = handlers.reply_help(staff)
        elif command == "stop":
            reply = handlers.reply_stop(staff)
        elif command == "summary":
            reply = handlers.reply_summary(config=cfg)
        elif command == "recommendations":
            reply = handlers.reply_recommendations(config=cfg)
        elif command == "events":
            reply = handlers.reply_events(config=cfg)
        elif command == "problems":
            reply = handlers.reply_problems(config=cfg)
        elif command == "detail":
            rec_id = int(payload_extra or "0")
            reply = handlers.reply_detail(rec_id, staff=staff, config=cfg)
        elif command == "accept":
            rec_id = int(payload_extra or "0")
            reply = handlers.reply_accept(rec_id, staff=staff, config=cfg)
        else:
            reply = {"text": "Неизвестная команда. Нажмите /help", "attachments": []}
        _send(
            client,
            chat_id=chat_id,
            user_id=user_id,
            text=reply["text"],
            attachments=reply.get("attachments") or None,
        )
        if callback_id:
            try:
                client.answer_callback(callback_id, notification="Готово")
            except Exception as exc:  # noqa: BLE001
                logger.debug("answer_callback: %s", exc)
        _log(user_id, command, "ok")
        return {"ok": True, "command": command}
    except Exception as exc:  # noqa: BLE001
        logger.exception("staff_bot command error: %s", exc)
        _log(user_id, command, "error", str(exc)[:500])
        _send(
            client,
            chat_id=chat_id,
            user_id=user_id,
            text="Не удалось выполнить команду. Попробуйте позже или откройте админку.",
        )
        return {"ok": False, "error": str(exc)}


def dispatch_text(
    text: str,
    *,
    user_id: int | None,
    chat_id: int | None,
    display_name: str = "",
    config: AppConfig | None = None,
    api: MaxApiClient | None = None,
) -> dict[str, Any] | None:
    command = resolve_command(text)
    if command is None:
        # Неизвестное сообщение — показать меню только своим
        access = check_access(user_id, "start", config=config)
        if not access.allowed:
            client = api or build_max_api_client(config)
            if client is not None:
                _send(client, chat_id=chat_id, user_id=user_id, text=DENIED_TEXT)
            _log(user_id, "unknown", "denied", (text or "")[:80])
            return {"ok": True, "denied": True}
        return handle_staff_command(
            command="help",
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            config=config,
            api=api,
        )
    return handle_staff_command(
        command=command,
        user_id=user_id,
        chat_id=chat_id,
        display_name=display_name,
        config=config,
        api=api,
    )


def dispatch_callback(
    payload: str,
    *,
    user_id: int | None,
    chat_id: int | None,
    display_name: str = "",
    callback_id: str | None = None,
    config: AppConfig | None = None,
    api: MaxApiClient | None = None,
) -> dict[str, Any]:
    raw = (payload or "").strip()
    if raw.startswith("onboarding:"):
        choice = raw.split(":", 1)[1]
        return handle_onboarding_choice(
            choice,
            user_id=user_id,
            chat_id=chat_id,
            config=config,
            api=api,
            callback_id=callback_id,
        )
    if raw.startswith("cmd:"):
        command = raw.split(":", 1)[1]
        return handle_staff_command(
            command=command,
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            config=config,
            api=api,
            callback_id=callback_id,
        )
    if raw.startswith("detail:"):
        return handle_staff_command(
            command="detail",
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            config=config,
            api=api,
            callback_id=callback_id,
            payload_extra=raw.split(":", 1)[1],
        )
    if raw.startswith("accept:"):
        return handle_staff_command(
            command="accept",
            user_id=user_id,
            chat_id=chat_id,
            display_name=display_name,
            config=config,
            api=api,
            callback_id=callback_id,
            payload_extra=raw.split(":", 1)[1],
        )
    return handle_staff_command(
        command="help",
        user_id=user_id,
        chat_id=chat_id,
        display_name=display_name,
        config=config,
        api=api,
        callback_id=callback_id,
    )
