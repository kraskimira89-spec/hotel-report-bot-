"""Шаблоны меню и ответов внутреннего бота."""

from __future__ import annotations

from typing import Any

BTN_START = "🚀 Начать"
BTN_SUMMARY = "📊 Сводка на сегодня"
BTN_RECO = "🔮 Прогноз и рекомендации"
BTN_EVENTS = "📅 События Томска"
BTN_PROBLEMS = "⚠️ Проблемы и уведомления"
BTN_HELP = "❓ Помощь"
BTN_DETAIL_PREFIX = "Подробнее"
BTN_ACCEPT = "✅ Принять"
BTN_SEND_LAST = "📬 Скинь последнюю сводку"
BTN_WAIT_9 = "⏰ Ждать до 9:00"

TEXT_ALIASES: dict[str, str] = {
    "/start": "start",
    "start": "start",
    "начать": "start",
    BTN_START: "start",
    "/help": "help",
    "help": "help",
    BTN_HELP: "help",
    "/stop": "stop",
    "stop": "stop",
    BTN_SUMMARY: "summary",
    BTN_SEND_LAST: "send_last_summary",
    BTN_WAIT_9: "wait_until_9",
    BTN_RECO: "recommendations",
    BTN_EVENTS: "events",
    BTN_PROBLEMS: "problems",
    "⚠️ Проблемы": "problems",
}


def first_connect_text(name: str = "") -> str:
    """Сообщение при первом подключении / кнопке «Начать»."""
    display = (name or "").strip()
    hello = f"Здравствуйте, {display}! 👋" if display else "Здравствуйте! 👋"
    return (
        f"{hello}\n\n"
        "Это бот апарт-отеля 1apart.\n\n"
        "Каждый день около 9:00 я буду присылать сводку "
        "по загрузке, бронированиям и важным уведомлениям "
        "по объекту 1apart.\n\n"
        "Выслать последнюю сводку сейчас или дождаться 9:00?"
    )


def welcome_text(name: str) -> str:
    """Приветствие для сотрудников с доступом."""
    return first_connect_text(name)


def onboarding_choice_buttons() -> list[list[dict[str, str]]]:
    """Кнопки после приветствия: сводка сейчас или ждать 9:00."""
    return [
        [{"type": "callback", "text": BTN_SEND_LAST, "payload": "onboarding:send_last"}],
        [{"type": "callback", "text": BTN_WAIT_9, "payload": "onboarding:wait_9"}],
    ]


def help_text(*, role: str) -> str:
    lines = [
        "Команды внутреннего бота 1apart:",
        "",
        f"{BTN_START} / /start — приветствие и меню",
        f"{BTN_SUMMARY} — загрузка, брони, выручка, ошибки",
    ]
    if role in ("owner", "manager"):
        lines.append(
            f"{BTN_RECO} — 3 приоритетные рекомендации"
        )
    lines.extend(
        [
            f"{BTN_EVENTS} — события Томска на 7 дней",
            f"{BTN_PROBLEMS} — критичные ошибки и источники",
            "/help — этот список",
            "/stop — отключить регулярные уведомления",
            "",
            "Гостевые данные, телефоны, email и ключи API бот не выдаёт.",
        ]
    )
    return "\n".join(lines)


def main_menu_buttons(*, role: str) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = [
        [{"type": "callback", "text": BTN_START, "payload": "cmd:start"}],
        [{"type": "callback", "text": BTN_SUMMARY, "payload": "cmd:summary"}],
    ]
    if role in ("owner", "manager"):
        rows.append(
            [{"type": "callback", "text": BTN_RECO, "payload": "cmd:recommendations"}]
        )
    rows.extend(
        [
            [{"type": "callback", "text": BTN_EVENTS, "payload": "cmd:events"}],
            [{"type": "callback", "text": BTN_PROBLEMS, "payload": "cmd:problems"}],
            [{"type": "callback", "text": BTN_HELP, "payload": "cmd:help"}],
        ]
    )
    return rows


def inline_keyboard(rows: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
    return [{"type": "inline_keyboard", "payload": {"buttons": rows}}]


def resolve_command(text: str | None) -> str | None:
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower in TEXT_ALIASES:
        return TEXT_ALIASES[lower]
    if raw in TEXT_ALIASES:
        return TEXT_ALIASES[raw]
    if lower.startswith("/"):
        return TEXT_ALIASES.get(lower.split()[0])
    return None
