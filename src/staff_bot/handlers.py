"""Сборка ответов на команды внутреннего бота."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.config import AppConfig, get_config
from src.recommendations.render import render_instruction_card
from src.staff_bot.templates import (
    BTN_ACCEPT,
    BTN_DETAIL_PREFIX,
    help_text,
    inline_keyboard,
    main_menu_buttons,
    welcome_text,
)
from src.storage.db import (
    get_city_events,
    get_errors_log,
    get_metrics_for_date,
    get_recommendation_by_id,
    list_recommendations,
    update_staff_notifications,
)
from src.storage.models import StaffUserRecord


def _admin_url(path: str, config: AppConfig) -> str:
    base = (config.staff_bot.admin_base_url or "").rstrip("/")
    if not base:
        return path
    return f"{base}{path}"


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%"


def reply_start(staff: StaffUserRecord) -> dict[str, Any]:
    text = welcome_text(staff.display_name)
    return {
        "text": text,
        "attachments": inline_keyboard(main_menu_buttons(role=staff.role)),
    }


def reply_help(staff: StaffUserRecord) -> dict[str, Any]:
    return {
        "text": help_text(role=staff.role),
        "attachments": inline_keyboard(main_menu_buttons(role=staff.role)),
    }


def reply_stop(staff: StaffUserRecord) -> dict[str, Any]:
    update_staff_notifications(
        staff.user_id,
        notify_daily=False,
        notify_critical=False,
        notify_recommendations=False,
        notify_events=False,
    )
    return {
        "text": (
            "Регулярные уведомления отключены.\n"
            "Чтобы снова получать сводки — напишите /start и сообщите администратору."
        ),
        "attachments": inline_keyboard(main_menu_buttons(role=staff.role)),
    }


def reply_summary(*, config: AppConfig | None = None) -> dict[str, Any]:
    cfg = config or get_config()
    today = date.today()
    metrics = get_metrics_for_date(today, "daily")
    if metrics is None:
        metrics = get_metrics_for_date(today - timedelta(days=1), "daily")
    errors = get_errors_log(resolved=False, limit=5)
    if metrics is None:
        body = "Сводка: данных за сегодня/вчера пока нет."
    else:
        body = (
            f"📊 Сводка на {metrics.report_date.isoformat()}\n\n"
            f"Загрузка: {_fmt_pct(metrics.occupancy_pct)}\n"
            f"Брони: {metrics.bookings_count if metrics.bookings_count is not None else '—'}\n"
            f"Выручка: {_fmt_money(metrics.revenue)}\n"
            f"ADR: {_fmt_money(metrics.adr)} · RevPAR: {_fmt_money(metrics.revpar)}"
        )
    if errors:
        body += f"\n\n⚠️ Открытых ошибок: {len(errors)}"
        for err in errors[:3]:
            body += f"\n• [{err.source}] {err.error_type}: {err.message[:120]}"
    else:
        body += "\n\n✅ Критичных открытых ошибок нет."
    body += f"\n\nПодробнее: {_admin_url('/analytics', cfg)}"
    return {"text": body, "attachments": []}


def reply_recommendations(
    *,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    cfg = config or get_config()
    recs = list_recommendations(
        statuses=["new", "accepted", "in_progress"],
        limit=3,
    )
    if not recs:
        return {
            "text": "Активных рекомендаций сейчас нет.",
            "attachments": [],
        }
    lines = ["🔮 Прогноз и рекомендации (топ-3):\n"]
    buttons: list[list[dict[str, str]]] = []
    for i, rec in enumerate(recs, start=1):
        rid = rec.id or 0
        lines.append(
            f"{i}. [{rec.priority}] {rec.title}\n"
            f"   {rec.summary[:160] if rec.summary else '—'}"
        )
        if rid:
            buttons.append(
                [
                    {
                        "type": "callback",
                        "text": f"{BTN_DETAIL_PREFIX} #{rid}",
                        "payload": f"detail:{rid}",
                    }
                ]
            )
    lines.append(f"\nВсе рекомендации: {_admin_url('/recommendations', cfg)}")
    return {
        "text": "\n".join(lines),
        "attachments": inline_keyboard(buttons) if buttons else [],
    }


def reply_detail(
    rec_id: int,
    *,
    staff: StaffUserRecord,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    cfg = config or get_config()
    rec = get_recommendation_by_id(rec_id)
    if rec is None:
        return {"text": f"Рекомендация #{rec_id} не найдена.", "attachments": []}
    card = render_instruction_card(rec)
    steps = card.get("steps") or []
    short_steps = steps[:3]
    lines = [
        f"📌 {card.get('title') or rec.title}",
        f"Приоритет: {card.get('priority_label') or rec.priority}",
        "",
        "Краткий план:",
    ]
    if short_steps:
        for i, step in enumerate(short_steps, start=1):
            lines.append(f"{i}. {step}")
    else:
        lines.append("• См. полную инструкцию в админке")
    url = _admin_url(f"/recommendations/{rec_id}", cfg)
    lines.append(f"\nПолная инструкция: {url}")
    buttons: list[list[dict[str, str]]] = []
    if staff.role in ("owner", "manager") and rec.status == "new":
        buttons.append(
            [
                {
                    "type": "callback",
                    "text": BTN_ACCEPT,
                    "payload": f"accept:{rec_id}",
                }
            ]
        )
    return {
        "text": "\n".join(lines),
        "attachments": inline_keyboard(buttons) if buttons else [],
    }


def reply_accept(
    rec_id: int,
    *,
    staff: StaffUserRecord,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    from src.storage.db import update_recommendation_status

    cfg = config or get_config()
    ok = update_recommendation_status(
        rec_id,
        "accepted",
        actor=staff.display_name or str(staff.user_id),
    )
    if not ok:
        return {
            "text": f"Не удалось принять рекомендацию #{rec_id}.",
            "attachments": [],
        }
    url = _admin_url(f"/recommendations/{rec_id}", cfg)
    return {
        "text": f"✅ Рекомендация #{rec_id} принята.\nКарточка: {url}",
        "attachments": [],
    }


def reply_events(*, config: AppConfig | None = None) -> dict[str, Any]:
    cfg = config or get_config()
    today = date.today()
    end = today + timedelta(days=7)
    min_impact = float(cfg.events.notify_min_impact or 60.0)
    events = get_city_events(
        start=today,
        end=end,
        status="approved",
        min_impact=min_impact,
        limit=10,
    )
    if not events:
        # запасной список без жёсткого порога
        events = get_city_events(
            start=today,
            end=end,
            status="approved",
            limit=5,
        )
    if not events:
        return {
            "text": "На ближайшие 7 дней событий с высоким влиянием нет.",
            "attachments": [],
        }
    lines = [f"📅 События Томска ({today.isoformat()} — {end.isoformat()}):\n"]
    for ev in events[:7]:
        impact = f"{ev.impact_score:.0f}" if ev.impact_score is not None else "—"
        start = ev.start_at.isoformat() if ev.start_at else "?"
        lines.append(f"• {start}: {ev.title} (влияние {impact})")
    lines.append(f"\nВсе события: {_admin_url('/events', cfg)}")
    return {"text": "\n".join(lines), "attachments": []}


def reply_problems(*, config: AppConfig | None = None) -> dict[str, Any]:
    cfg = config or get_config()
    errors = get_errors_log(resolved=False, limit=10)
    if not errors:
        return {
            "text": "✅ Критичных открытых ошибок нет.\nИсточники в норме.",
            "attachments": [],
        }
    lines = ["⚠️ Проблемы и уведомления:\n"]
    for err in errors[:8]:
        lines.append(
            f"• {err.error_date.isoformat()} [{err.source}] "
            f"{err.error_type}: {err.message[:140]}"
        )
    lines.append(f"\nЛоги: {_admin_url('/logs', cfg)}")
    return {"text": "\n".join(lines), "attachments": []}
