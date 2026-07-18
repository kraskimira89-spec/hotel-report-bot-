"""Сборка ответов на команды внутреннего бота."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.config import AppConfig, get_config
from src.recommendations.render import render_instruction_card
from src.staff_bot.templates import (
    BTN_ACCEPT,
    BTN_DETAIL_PREFIX,
    first_connect_text,
    help_text,
    inline_keyboard,
    main_menu_buttons,
    onboarding_choice_buttons,
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
    return reply_first_connect(staff.display_name)


def reply_first_connect(name: str = "") -> dict[str, Any]:
    """Приветствие + вопрос: сводка сейчас или ждать 9:00."""
    return {
        "text": first_connect_text(name),
        "attachments": inline_keyboard(onboarding_choice_buttons()),
    }


def reply_wait_until_9() -> dict[str, Any]:
    return {
        "text": (
            "Хорошо! ⏰\n\n"
            "Сводка по 1apart придёт около 9:00.\n"
            "До связи!"
        ),
        "attachments": [],
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
    """Последняя сводка в формате утреннего Max (несколько частей)."""
    cfg = config or get_config()
    texts = build_last_summary_texts(config=cfg)
    return {"text": texts[0] if texts else "Сводка недоступна.", "texts": texts, "attachments": []}


def build_last_summary_texts(*, config: AppConfig | None = None) -> list[str]:
    """Сводка из БД (быстро), без live-API и без сырых http_error."""
    from src.metrics.occupancy import traffic_light
    from src.storage.db import db_session, get_competitor_prices_latest

    cfg = config or get_config()
    today = date.today()
    metrics = get_metrics_for_date(today, "daily")
    if metrics is None:
        metrics = get_metrics_for_date(today - timedelta(days=1), "daily")
    if metrics is None:
        return ["Сводка: данных за сегодня/вчера пока нет."]

    report_date = metrics.report_date
    occ = metrics.occupancy_pct or 0.0
    light = traffic_light(occ, cfg.traffic_light)

    section_occ = [
        f"📊 *Сводка за {report_date.strftime('%d.%m.%Y')}*",
        f"*Загрузка:* {light} {occ:.1f}%",
        "",
        f"Брони: {metrics.bookings_count if metrics.bookings_count is not None else '—'}",
        f"Выручка: {_fmt_money(metrics.revenue)}",
        f"ADR: {_fmt_money(metrics.adr)} · RevPAR: {_fmt_money(metrics.revpar)}",
    ]

    with db_session() as conn:
        cat_rows = conn.execute(
            """
            SELECT metric_type, occupancy_pct FROM metrics_daily
            WHERE report_date = ? AND metric_type LIKE 'category:%'
            ORDER BY metric_type
            """,
            (report_date.isoformat(),),
        ).fetchall()
    if cat_rows:
        section_occ.append("")
        section_occ.append("*Загрузка по категориям:*")
        for row in cat_rows:
            label = str(row["metric_type"]).replace("category:", "", 1)
            section_occ.append(f"• {label}: {_fmt_pct(row['occupancy_pct'])}")

    parts = ["\n".join(section_occ)]

    competitors = get_competitor_prices_latest()
    if competitors:
        for comp in competitors:
            price = (
                f"{comp.price_from:,.0f}".replace(",", " ") + " ₽"
                if comp.price_from is not None
                else "—"
            )
            parts.append(f"*Конкурент:* {comp.competitor_name}\nот {price}")
    else:
        parts.append("*Конкуренты*\n- нет данных")

    parts.append(f"Подробнее: {_admin_url('/analytics', cfg)}")
    return parts


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
        msg = err.message.split(" for url ")[0][:140]
        lines.append(
            f"• {err.error_date.isoformat()} [{err.source}] {err.error_type}: {msg}"
        )
    lines.append(f"\nЛоги: {_admin_url('/logs', cfg)}")
    return {"text": "\n".join(lines), "attachments": []}
