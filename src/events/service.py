"""Оркестрация: сбор, дедуп, impact, ручные действия."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from src.config import get_config
from src.events.classify import classify_event_category
from src.events.collector import collect_from_source
from src.events.impact import (
    MIN_FORECAST_IMPACT,
    apply_impact_to_event,
    event_affects_forecast,
    event_demand_score,
    forecast_coefficient_for_category,
    impact_level,
)
from src.events.normalize import find_matching_event, normalize_title
from src.events.types import ParsedEvent
from src.storage.db import (
    count_event_sources,
    expire_city_events,
    get_approved_city_events,
    get_city_event,
    get_city_events,
    get_city_events_for_dedup,
    get_event_review_log,
    get_event_sources,
    save_city_event,
    save_event_review_log,
    save_event_source,
)
from src.storage.models import CityEventRecord, EventReviewLogRecord, EventSourceRecord

logger = logging.getLogger(__name__)


def _horizon_end(today: date) -> date:
    cfg = get_config()
    return today + timedelta(days=cfg.events.horizon_days)


def _apply_ai_category(parsed: ParsedEvent) -> ParsedEvent:
    """ИИ/правила: категория для нового события."""
    cfg = get_config()
    cat, source = classify_event_category(
        parsed.title,
        parsed.description,
        parsed.venue_name,
        use_llm=bool(cfg.events.classify_with_llm),
        hint=parsed.category if parsed.category != "other" else None,
    )
    # Если парсер дал other — всегда пробуем ИИ; если парсер уверен — оставляем
    if parsed.category == "other" or source == "llm":
        parsed.category = cat
    # source сохраним на записи ниже через поле в record
    parsed._category_source = source  # type: ignore[attr-defined]
    return parsed


def _parsed_to_record(parsed: ParsedEvent, status: str = "candidate") -> CityEventRecord:
    cfg = get_config()
    coef = forecast_coefficient_for_category(parsed.category, cfg.events.max_forecast_uplift)
    cat_source = getattr(parsed, "_category_source", "rules")
    return CityEventRecord(
        title=parsed.title,
        normalized_title=normalize_title(parsed.title),
        category=parsed.category,
        start_at=parsed.start_at,
        end_at=parsed.end_at,
        city=parsed.city or "Томск",
        venue_name=parsed.venue_name,
        venue_address=parsed.venue_address,
        estimated_capacity=parsed.estimated_capacity,
        audience_scope=parsed.audience_scope,
        source_url=parsed.source_url,
        source_name=parsed.source_name,
        source_priority=parsed.source_priority,
        status=status,
        forecast_coefficient=coef,
        description=parsed.description,
        is_online=parsed.is_online,
        registration_required=parsed.registration_required,
        expected_attendance=parsed.expected_attendance,
        attendance_source=parsed.attendance_source,
        tourism_relevance=parsed.tourism_relevance,
        overnight_likelihood=parsed.overnight_likelihood or 0.1,
        is_public_holiday=parsed.is_public_holiday,
        category_manual=False,
        category_source=str(cat_source),
    )


def _merge_parsed_into_event(
    existing: CityEventRecord,
    parsed: ParsedEvent,
) -> CityEventRecord:
    if parsed.source_priority <= existing.source_priority:
        existing.title = parsed.title
        existing.normalized_title = normalize_title(parsed.title)
        existing.start_at = parsed.start_at
        existing.end_at = parsed.end_at or existing.end_at
        if parsed.venue_name:
            existing.venue_name = parsed.venue_name
        existing.source_url = parsed.source_url
        existing.source_name = parsed.source_name
        existing.source_priority = parsed.source_priority
    if parsed.estimated_capacity and not existing.estimated_capacity:
        existing.estimated_capacity = parsed.estimated_capacity
    if parsed.expected_attendance and not existing.expected_attendance:
        existing.expected_attendance = parsed.expected_attendance
        existing.attendance_source = parsed.attendance_source or existing.attendance_source
    # Ручную категорию не перезаписываем
    if not existing.category_manual and parsed.category != "other":
        existing.category = parsed.category
        if existing.category_source == "rules":
            existing.category_source = "parser"
    if parsed.audience_scope != "unknown":
        existing.audience_scope = parsed.audience_scope
    if parsed.is_online:
        existing.is_online = True
    if parsed.registration_required:
        existing.registration_required = True
    if parsed.city and parsed.city != "Томск":
        existing.city = parsed.city
    return existing


def _source_is_verification_only(source_name: str) -> bool:
    cfg = get_config()
    for src in cfg.events.sources:
        if src.name == source_name:
            return bool(src.verification_only)
    return source_name == "ria_tomsk_events"


def ingest_parsed_events(parsed_list: list[ParsedEvent], today: date | None = None) -> dict[str, int]:
    """Дедупликация и сохранение кандидатов."""
    today = today or date.today()
    end = _horizon_end(today)
    existing = get_city_events_for_dedup(today, end)
    stats = {"new": 0, "merged": 0, "skipped": 0, "classified": 0}

    for parsed in parsed_list:
        match = find_matching_event(parsed, existing)
        if match and match.id:
            updated = _merge_parsed_into_event(match, parsed)
            save_city_event(updated)
            save_event_source(
                EventSourceRecord(
                    event_id=match.id,
                    source_name=parsed.source_name,
                    source_url=parsed.source_url,
                    source_event_id=parsed.source_event_id,
                    raw_title=parsed.title,
                    raw_date=parsed.raw_date,
                    raw_venue=parsed.venue_name,
                    is_primary=parsed.source_priority <= updated.source_priority,
                )
            )
            src_cnt = count_event_sources(match.id)
            apply_impact_to_event(updated, src_cnt)
            save_city_event(updated)
            stats["merged"] += 1
            continue

        if _source_is_verification_only(parsed.source_name):
            stats["skipped"] += 1
            continue

        _apply_ai_category(parsed)
        stats["classified"] += 1
        record = _parsed_to_record(parsed)
        src_cnt = 1
        apply_impact_to_event(record, src_cnt)
        if record.impact_score >= get_config().events.require_approval_score:
            record.status = "candidate"
        saved = save_city_event(record)
        assert saved.id is not None
        save_event_source(
            EventSourceRecord(
                event_id=saved.id,
                source_name=parsed.source_name,
                source_url=parsed.source_url,
                source_event_id=parsed.source_event_id,
                raw_title=parsed.title,
                raw_date=parsed.raw_date,
                raw_venue=parsed.venue_name,
                is_primary=True,
            )
        )
        existing.append(saved)
        stats["new"] += 1

    return stats


def reclassify_other_events(today: date | None = None, *, limit: int = 30) -> int:
    """Переклассифицировать события с категорией «Другое», если не зафиксированы вручную."""
    cfg = get_config()
    if not cfg.events.reclassify_other_on_collect:
        return 0
    today = today or date.today()
    end = _horizon_end(today)
    events = get_city_events(start=today, end=end, category="other", limit=limit)
    changed = 0
    for ev in events:
        if ev.category_manual or ev.id is None:
            continue
        if ev.status in ("rejected", "cancelled", "expired"):
            continue
        cat, source = classify_event_category(
            ev.title,
            ev.description,
            ev.venue_name,
            use_llm=bool(cfg.events.classify_with_llm),
            hint=None,
        )
        if cat == ev.category:
            continue
        old = ev.category
        ev.category = cat
        ev.category_source = source
        ev.forecast_coefficient = forecast_coefficient_for_category(
            cat, cfg.events.max_forecast_uplift
        )
        apply_impact_to_event(ev, max(1, count_event_sources(ev.id)))
        save_city_event(ev)
        save_event_review_log(
            EventReviewLogRecord(
                event_id=ev.id,
                action="classify_category",
                old_value=old,
                new_value=cat,
                comment=f"source={source}",
                actor="system",
            )
        )
        changed += 1
    return changed


def recalc_all_impact_scores(today: date | None = None) -> int:
    today = today or date.today()
    end = _horizon_end(today)
    events = get_city_events(start=today, end=end, limit=2000)
    count = 0
    for ev in events:
        if ev.id is None or ev.status in ("rejected", "cancelled", "expired"):
            continue
        src_cnt = count_event_sources(ev.id)
        apply_impact_to_event(ev, max(1, src_cnt))
        save_city_event(ev)
        count += 1
    return count


def collect_all_sources(
    today: date | None = None,
    *,
    force: bool = False,
    html_by_source: dict[str, str] | None = None,
) -> dict[str, int]:
    cfg = get_config()
    if not cfg.events.enabled:
        return {}
    today = today or date.today()
    end = _horizon_end(today)
    totals = {"parsed": 0, "new": 0, "merged": 0}
    all_parsed: list[ParsedEvent] = []

    for src in cfg.events.sources:
        if not src.enabled:
            continue
        html = (html_by_source or {}).get(src.name)
        parsed = collect_from_source(
            src,
            today,
            end,
            interval_hours=cfg.events.refresh_interval_hours,
            force=force,
            html_override=html,
        )
        totals["parsed"] += len(parsed)
        all_parsed.extend(parsed)

    ingest_stats = ingest_parsed_events(all_parsed, today=today)
    totals.update(ingest_stats)
    expired = expire_city_events(today)
    totals["expired"] = expired
    logger.info("Сбор событий: %s", totals)
    return totals


def run_events_pipeline(today: date | None = None, *, force: bool = False) -> dict[str, int]:
    """Полный пайплайн: сбор → классификация → impact → прогноз."""
    stats = collect_all_sources(today=today, force=force)
    stats["reclassified"] = reclassify_other_events(today)
    stats["impact_recalc"] = recalc_all_impact_scores(today)
    critical = notify_critical_events(today)
    stats["critical_notified"] = critical
    cfg = get_config()
    if cfg.forecast.enabled:
        from src.forecast.service import run_forecast_refresh

        run_forecast_refresh(horizons=[7, 14, 30])
        stats["forecast_refreshed"] = 1
    return stats


def notify_critical_events(today: date | None = None) -> int:
    """Уведомить о кандидатах на модерацию и подтверждённых с высоким overnight."""
    today = today or date.today()
    cfg = get_config()
    notified = 0

    # Кандидаты с высоким impact — в очередь модерации
    pending = get_city_events(
        start=today,
        end=today + timedelta(days=7),
        status="candidate",
        min_impact=80,
        limit=20,
    )
    if pending:
        try:
            from src.notifiers.incidents import send_incident

            lines = [
                f"• {e.title} ({e.start_at.isoformat()}, score={e.impact_score})"
                for e in pending[:5]
            ]
            send_incident(
                "Критичные события Томска",
                "Требуется подтверждение в админке /events:\n" + "\n".join(lines),
                source="city_events",
            )
            notified += len(pending)
        except Exception as exc:
            logger.warning("Не удалось отправить уведомление о событиях: %s", exc)

    # Подтверждённые: impact ≥ 80, overnight ≥ 0.35, в горизонте 14 дней
    horizon = today + timedelta(days=cfg.events.notify_horizon_days)
    approved = get_city_events(
        start=today,
        end=horizon,
        status="approved",
        min_impact=cfg.events.notify_min_impact,
        limit=20,
    )
    alertable = [
        e
        for e in approved
        if float(e.overnight_likelihood or 0) >= cfg.events.notify_min_overnight
        and not e.is_online
    ]
    if alertable:
        try:
            from src.notifiers.incidents import send_incident

            for e in alertable[:5]:
                end_d = e.end_at or e.start_at
                period = (
                    e.start_at.strftime("%d.%m")
                    if e.start_at == end_d
                    else f"{e.start_at.strftime('%d.%m')}–{end_d.strftime('%d.%m')}"
                )
                check_start = e.start_at - timedelta(days=1)
                check_end = end_d + timedelta(days=1)
                msg = (
                    f"🟣 {period}: подтверждён {e.title}.\n"
                    f"Ожидаемое влияние: {impact_level(e.impact_score)}. "
                    f"overnight={e.overnight_likelihood:.2f}.\n"
                    f"Проверьте цены и доступность квартир на "
                    f"{check_start.strftime('%d.%m')}–{check_end.strftime('%d.%m')}."
                )
                send_incident(
                    "Событие с высоким overnight",
                    msg,
                    source="city_events_overnight",
                )
            notified += len(alertable)
        except Exception as exc:
            logger.warning("Не удалось отправить overnight-уведомление: %s", exc)

    return notified


def _maybe_notify_approved_overnight(ev: CityEventRecord) -> None:
    """Отдельное уведомление сразу после approve, если пороги выполнены."""
    cfg = get_config()
    today = date.today()
    if ev.status != "approved":
        return
    if float(ev.impact_score or 0) < cfg.events.notify_min_impact:
        return
    if float(ev.overnight_likelihood or 0) < cfg.events.notify_min_overnight:
        return
    if ev.is_online:
        return
    if ev.start_at > today + timedelta(days=cfg.events.notify_horizon_days):
        return
    if ev.end_at and ev.end_at < today:
        return
    try:
        from src.notifiers.incidents import send_incident

        end_d = ev.end_at or ev.start_at
        period = (
            ev.start_at.strftime("%d.%m")
            if ev.start_at == end_d
            else f"{ev.start_at.strftime('%d.%m')}–{end_d.strftime('%d.%m')}"
        )
        send_incident(
            "Событие с высоким overnight",
            (
                f"🟣 {period}: подтверждён {ev.title}.\n"
                f"Ожидаемое влияние: {impact_level(ev.impact_score)}. "
                f"Проверьте цены и доступность квартир."
            ),
            source="city_events_overnight",
        )
    except Exception as exc:
        logger.warning("Не удалось отправить overnight после approve: %s", exc)

def _refresh_forecast_after_moderation() -> None:
    """Пересчитать прогноз после ручного изменения событий."""
    try:
        from src.config import get_config
        from src.forecast.service import run_forecast_refresh

        cfg = get_config()
        if not cfg.forecast.enabled:
            return
        horizons = [h for h in cfg.forecast.horizons if h <= 30] or [7, 14, 30]
        run_forecast_refresh(horizons=horizons)
        logger.info("Прогноз обновлён после модерации событий: %s", horizons)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось пересчитать прогноз после модерации: %s", exc)


def approve_event(event_id: int, actor: str = "admin", comment: str | None = None) -> CityEventRecord | None:
    ev = get_city_event(event_id)
    if not ev:
        return None
    old = ev.status
    ev.status = "approved"
    save_city_event(ev)
    save_event_review_log(
        EventReviewLogRecord(
            event_id=event_id,
            action="approve",
            old_value=old,
            new_value="approved",
            comment=comment,
            actor=actor,
        )
    )
    _maybe_notify_approved_overnight(ev)
    _refresh_forecast_after_moderation()
    return ev


def reject_event(event_id: int, actor: str = "admin", comment: str | None = None) -> CityEventRecord | None:
    ev = get_city_event(event_id)
    if not ev:
        return None
    old = ev.status
    ev.status = "rejected"
    save_city_event(ev)
    save_event_review_log(
        EventReviewLogRecord(
            event_id=event_id,
            action="reject",
            old_value=old,
            new_value="rejected",
            comment=comment,
            actor=actor,
        )
    )
    if old == "approved":
        _refresh_forecast_after_moderation()
    return ev


def cancel_event(event_id: int, actor: str = "admin", comment: str | None = None) -> CityEventRecord | None:
    ev = get_city_event(event_id)
    if not ev:
        return None
    old = ev.status
    ev.status = "cancelled"
    save_city_event(ev)
    save_event_review_log(
        EventReviewLogRecord(
            event_id=event_id,
            action="cancel",
            old_value=old,
            new_value="cancelled",
            comment=comment,
            actor=actor,
        )
    )
    if old == "approved":
        _refresh_forecast_after_moderation()
    return ev


def adjust_event(
    event_id: int,
    *,
    actor: str = "admin",
    impact_score: float | None = None,
    audience_scope: str | None = None,
    category: str | None = None,
    estimated_capacity: int | None = None,
    start_at: date | None = None,
    end_at: date | None = None,
    comment: str | None = None,
) -> CityEventRecord | None:
    ev = get_city_event(event_id)
    if not ev:
        return None
    cfg = get_config()
    changes: list[str] = []
    if impact_score is not None:
        save_event_review_log(
            EventReviewLogRecord(
                event_id=event_id,
                action="adjust_score",
                old_value=str(ev.impact_score),
                new_value=str(impact_score),
                comment=comment,
                actor=actor,
            )
        )
        ev.impact_score = impact_score
        changes.append("score")
    if audience_scope:
        save_event_review_log(
            EventReviewLogRecord(
                event_id=event_id,
                action="adjust_scope",
                old_value=ev.audience_scope,
                new_value=audience_scope,
                comment=comment,
                actor=actor,
            )
        )
        ev.audience_scope = audience_scope
        changes.append("scope")
    if category:
        from src.events.classify import ALLOWED_CATEGORIES

        cat = category.strip()
        if cat in ALLOWED_CATEGORIES and cat != ev.category:
            save_event_review_log(
                EventReviewLogRecord(
                    event_id=event_id,
                    action="adjust_category",
                    old_value=ev.category,
                    new_value=cat,
                    comment=comment or "ручная правка",
                    actor=actor,
                )
            )
            ev.category = cat
            ev.category_manual = True
            ev.category_source = "manual"
            ev.forecast_coefficient = forecast_coefficient_for_category(
                cat, cfg.events.max_forecast_uplift
            )
            changes.append("category")
    if estimated_capacity is not None:
        ev.estimated_capacity = estimated_capacity
        changes.append("capacity")
    if start_at:
        ev.start_at = start_at
        changes.append("start")
    if end_at is not None:
        ev.end_at = end_at
        changes.append("end")
    if changes:
        src_cnt = count_event_sources(event_id)
        if impact_score is None:
            apply_impact_to_event(ev, src_cnt)
        else:
            gmin, gmax = estimate_guest_nights_safe(ev)
            ev.expected_guest_nights_min = gmin
            ev.expected_guest_nights_max = gmax
        save_city_event(ev)
        if ev.status == "approved" or "score" in changes or "category" in changes:
            _refresh_forecast_after_moderation()
    return ev


def estimate_guest_nights_safe(ev: CityEventRecord) -> tuple[int | None, int | None]:
    from src.events.impact import estimate_guest_nights

    return estimate_guest_nights(
        estimated_capacity=ev.estimated_capacity or ev.expected_attendance,
        start_at=ev.start_at,
        end_at=ev.end_at,
        audience_scope=ev.audience_scope,
        overnight_likelihood=ev.overnight_likelihood,
    )


def create_manual_event(
    *,
    title: str,
    start_at: date,
    end_at: date | None = None,
    category: str = "other",
    venue_name: str | None = None,
    estimated_capacity: int | None = None,
    audience_scope: str = "unknown",
    description: str | None = None,
    actor: str = "admin",
    city: str = "Томск",
    location_confirmed: bool = False,
    is_online: bool = False,
) -> CityEventRecord:
    cfg = get_config()
    record = CityEventRecord(
        title=title,
        normalized_title=normalize_title(title),
        category=category,
        start_at=start_at,
        end_at=end_at or start_at,
        city=city,
        venue_name=venue_name,
        estimated_capacity=estimated_capacity,
        audience_scope=audience_scope,
        source_name="manual",
        source_priority=0,
        source_url="",
        status="approved",
        description=description,
        forecast_coefficient=forecast_coefficient_for_category(category, cfg.events.max_forecast_uplift),
        is_online=is_online,
        location_confirmed=location_confirmed or city.strip().lower() in ("томск", "tomsk"),
    )
    apply_impact_to_event(record, 1)
    saved = save_city_event(record)
    assert saved.id is not None
    save_event_source(
        EventSourceRecord(
            event_id=saved.id,
            source_name="manual",
            source_url="/events",
            raw_title=title,
            is_primary=True,
        )
    )
    save_event_review_log(
        EventReviewLogRecord(
            event_id=saved.id,
            action="approve",
            new_value="manual_create",
            comment="Создано вручную",
            actor=actor,
        )
    )
    if event_affects_forecast(saved.status, saved.impact_score, saved):
        _refresh_forecast_after_moderation()
    _maybe_notify_approved_overnight(saved)
    return saved


def events_for_forecast(start: date, end: date) -> list[CityEventRecord]:
    """Подтверждённые события с impact ≥ MIN_FORECAST_IMPACT для прогноза."""
    cfg = get_config()
    if not cfg.events.enabled:
        return []
    events = get_approved_city_events(start, end)
    return [e for e in events if event_affects_forecast(e.status, e.impact_score, e)]


def event_detail_bundle(event_id: int) -> dict | None:
    ev = get_city_event(event_id)
    if not ev:
        return None
    return {
        "event": ev,
        "sources": get_event_sources(event_id),
        "review_log": get_event_review_log(event_id),
        "impact_level": impact_level(ev.impact_score),
        "in_forecast": event_affects_forecast(ev.status, ev.impact_score, ev),
        "min_forecast_impact": MIN_FORECAST_IMPACT,
        "event_demand_score": event_demand_score(
            ev.impact_score,
            ev.overnight_likelihood,
            ev.start_at,
            ev.end_at,
            ev.audience_scope,
        ),
    }
