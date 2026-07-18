"""Пошаговые инструкции менеджера и условия отката для карточки рекомендации."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.config import ForecastConfig
from src.storage.models import PriceRecommendationRecord

_MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

TYPE_LABELS = {
    "increase": "Повысить цену",
    "decrease": "Снизить цену",
    "hold": "Оставить цену",
    "restrict_discounts": "Ограничить скидки",
    "manual_review": "Ручная проверка",
}

STATUS_LABELS = {
    "new": "Новая",
    "reviewed": "Просмотрена",
    "accepted": "Принята",
    "applied": "Применена",
    "verified": "Проверена",
    "rejected": "Отклонена",
    "deferred": "Отложена",
    "expired": "Истекла",
    "rolled_back": "Откат",
}


def format_date_ru(value: date) -> str:
    return f"{value.day} {_MONTHS_RU[value.month]} {value.year}"


def format_price_rub(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{int(round(value)):,}".replace(",", " ") + " ₽"


def _price_or_placeholder(
    selected: float | None,
    rec_min: float | None,
    rec_max: float | None,
    allow_concrete: bool,
) -> str:
    if not allow_concrete:
        return "после ручной проверки"
    if selected is not None:
        return format_price_rub(selected)
    if rec_min is not None and rec_max is not None and rec_min == rec_max:
        return format_price_rub(rec_min)
    if rec_min is not None and rec_max is not None:
        return f"{format_price_rub(rec_min)}–{format_price_rub(rec_max)}"
    return "—"


def build_manager_steps(
    rec: PriceRecommendationRecord,
    *,
    room_label: str,
    selected_price: float | None = None,
) -> list[str]:
    """Шаги для менеджера в TravelLine по типу рекомендации."""
    date_label = format_date_ru(rec.target_date)
    current = format_price_rub(rec.current_price)
    price = selected_price if selected_price is not None else rec.selected_price
    allow_concrete = rec.recommendation_type != "manual_review" or (
        rec.recommended_price_min is not None
        and rec.recommended_price_max is not None
        and rec.current_price is not None
        and not (
            rec.recommended_price_min == rec.recommended_price_max == rec.current_price
            and "недостаточно" in (rec.reason or "").lower()
        )
        and rec.current_price > 0
    )
    # manual_review без цены — без конкретной суммы
    if rec.recommendation_type == "manual_review" and (
        rec.current_price is None or rec.current_price <= 0
    ):
        allow_concrete = False
    target = _price_or_placeholder(
        price, rec.recommended_price_min, rec.recommended_price_max, allow_concrete
    )
    rtype = rec.recommendation_type

    common_open = [
        "Откройте TravelLine → Тарифы и цены.",
        f"Выберите период {date_label} и категорию «{room_label}».",
    ]

    if rtype == "increase":
        return [
            *common_open,
            f"Проверьте, что текущая цена равна {current}.",
            f"Установите цену {target} в основном тарифе.",
            "Проверьте ограничения: минимальная длительность проживания, "
            "закрытие продаж, скидки и каналы OTA.",
            "Сохраните изменение.",
            "В карточке рекомендации нажмите «Отметить как применённую».",
            "Через 24 часа проверьте pickup и загрузку.",
        ]
    if rtype == "decrease":
        return [
            *common_open,
            f"Проверьте, что текущая цена равна {current}.",
            f"Снизьте цену до {target} в основном тарифе.",
            "Убедитесь, что скидки и промо не дублируют снижение.",
            "Проверьте каналы OTA и ограничения минимального тарифа.",
            "Сохраните изменение.",
            "В карточке рекомендации нажмите «Отметить как применённую».",
            "Через 24 часа оцените прирост броней.",
        ]
    if rtype == "hold":
        return [
            *common_open,
            f"Убедитесь, что текущая цена {current} актуальна.",
            "Не меняйте основной тариф без новых данных.",
            "Проверьте, что скидки и закрытия продаж соответствуют плану.",
            "При необходимости зафиксируйте комментарий в карточке.",
            "Повторно оцените загрузку за 3 дня до заезда.",
        ]
    if rtype == "restrict_discounts":
        return [
            *common_open,
            f"Оставьте базовую цену около {current} (или {target}, если согласовано).",
            "Отключите или ограничьте скидки и промо на выбранный период.",
            "Проверьте закрытие продаж по низкодоходным каналам при необходимости.",
            "Сохраните изменения ограничений.",
            "В карточке рекомендации нажмите «Отметить как применённую».",
            "Через 24 часа проверьте, что ADR не просел из‑за скидок.",
        ]
    # manual_review
    steps = [
        *common_open,
        "Сверьте фактическую цену и наличие бронирований в TravelLine.",
        "Соберите дополнительные данные: конкуренты, события, остатки.",
    ]
    if allow_concrete:
        steps.append(f"При согласовании установите цену {target} вручную.")
    else:
        steps.append(
            "Не устанавливайте цену автоматически — решение только после проверки."
        )
    steps.extend(
        [
            "Зафиксируйте вывод в комментарии менеджера.",
            "При изменении тарифа отметьте рекомендацию как применённую.",
        ]
    )
    return steps


def build_control_block(
    rec: PriceRecommendationRecord,
    cfg: ForecastConfig,
    *,
    selected_price: float | None = None,
) -> dict[str, Any]:
    """Контрольные точки и условие отката (пороги из конфига)."""
    current = rec.current_price or 0.0
    band = cfg.rollback_price_band_pct / 100.0
    rollback_lo = round(current * (1 - band), 0) if current else None
    rollback_hi = round(current * (1 + band), 0) if current else None
    price = selected_price if selected_price is not None else rec.selected_price
    booking_note = (
        "и за 24 часа нет новых броней"
        if cfg.rollback_require_zero_bookings
        else ""
    )
    rollback_text = (
        f"если за {cfg.rollback_check_hours} ч. загрузка ниже "
        f"{cfg.rollback_occupancy_below:.0f}%"
    )
    if booking_note:
        rollback_text += f", {booking_note}"
    if rollback_lo is not None and rollback_hi is not None:
        rollback_text += (
            f" — вернуть цену в диапазон "
            f"{format_price_rub(rollback_lo)}–{format_price_rub(rollback_hi)}"
        )

    return {
        "check_after_hours": cfg.rollback_check_hours,
        "check_before_arrival_days": 3,
        "goal": "pickup не ниже медианы, сохранение/рост загрузки",
        "occupancy_below": cfg.rollback_occupancy_below,
        "require_zero_bookings": cfg.rollback_require_zero_bookings,
        "rollback_price_min": rollback_lo,
        "rollback_price_max": rollback_hi,
        "applied_or_selected": price,
        "check_text": (
            f"Проверить: через {cfg.rollback_check_hours} ч. "
            f"и за 3 дня до заезда."
        ),
        "goal_text": "Цель: pickup не ниже медианы, сохранение/рост загрузки.",
        "rollback_text": f"Откат: {rollback_text}.",
    }


def can_show_apply_price(rec: PriceRecommendationRecord) -> bool:
    """Для manual_review без данных не показываем конкретную цену к применению."""
    if rec.recommendation_type != "manual_review":
        return True
    if rec.current_price is None or rec.current_price <= 0:
        return False
    if rec.recommended_price_min is None or rec.recommended_price_max is None:
        return False
    return True
