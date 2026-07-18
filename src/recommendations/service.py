"""Синхронизация и генерация рекомендаций Центра."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta
from typing import Any

from src.config import get_config
from src.recommendations.templates_lib import get_template
from src.storage.db import (
    count_recommendations_summary,
    expire_overdue_recommendations,
    get_errors_log,
    get_latest_forecast_run,
    get_price_recommendations,
    get_reports_log,
    get_trends_records,
    upsert_recommendation,
)
from src.storage.models import PriceRecommendationRecord, RecommendationRecord

logger = logging.getLogger(__name__)

_PRICE_TYPE_MAP = {
    "increase": "price_increase",
    "decrease": "price_decrease",
    "restrict_discounts": "restrict_discounts",
    "hold": "hold",
    "manual_review": "manual_review",
}

_PRICE_STATUS_MAP = {
    "new": "new",
    "reviewed": "new",
    "accepted": "accepted",
    "deferred": "accepted",
    "applied": "done",
    "verified": "done",
    "rejected": "rejected",
    "expired": "expired",
    "rolled_back": "rejected",
}


def _room_label(slug: str) -> str:
    cfg = get_config()
    return (
        (cfg.category_slug_map or {}).get(slug)
        or (cfg.room_type_aliases or {}).get(slug)
        or slug
        or "категория"
    )


def _due_at(hours: int | None = None) -> datetime:
    cfg = get_config()
    h = hours if hours is not None else cfg.recommendations.default_due_hours
    return datetime.now().replace(microsecond=0) + timedelta(hours=h)


def _owner() -> str:
    return get_config().recommendations.default_owner


def _mid_price(lo: float | None, hi: float | None, cur: float | None) -> float | None:
    if lo is not None and hi is not None:
        return round((lo + hi) / 2, 0)
    return cur


def sync_price_recommendations(limit: int = 200) -> int:
    """Зеркалировать price_recommendations → recommendations."""
    cfg = get_config()
    fc = cfg.forecast
    count = 0
    rows = get_price_recommendations(status=None, horizon_days=None, limit=limit)
    for pr in rows:
        if pr.id is None:
            continue
        if pr.target_date < date.today() and pr.status in ("new", "reviewed"):
            continue
        tmpl_name = _PRICE_TYPE_MAP.get(pr.recommendation_type, "manual_review")
        tmpl = get_template(tmpl_name)
        snap = pr.recommendation_snapshot_json or {}
        room_label = _room_label(pr.room_type)
        selected = pr.selected_price or _mid_price(
            pr.recommended_price_min, pr.recommended_price_max, pr.current_price
        )
        what: list[str] = []
        if snap.get("occupancy_pct") is not None:
            what.append(f"Прогноз загрузки на дату — {snap['occupancy_pct']}%.")
        if snap.get("pickup_3d") is not None and snap.get("pickup_7d") is not None:
            what.append(
                f"Pickup: 3д={snap['pickup_3d']}, 7д={snap['pickup_7d']}."
            )
        if snap.get("market_gap_pct") is not None:
            what.append(
                f"Цена относительно медианы конкурентов: {snap['market_gap_pct']:+.1f}%."
            )
        for ev in snap.get("events") or []:
            what.append(
                f"Событие «{ev.get('title')}» (impact {ev.get('impact_score')})."
            )
        if pr.reason:
            what.append(pr.reason)

        priority = "medium"
        if pr.recommendation_type in ("increase", "decrease", "restrict_discounts"):
            priority = "high" if pr.confidence != "low" else "medium"
        if pr.confidence == "low":
            priority = "medium"

        mapped_status = _PRICE_STATUS_MAP.get(pr.status, "new")
        # При первом зеркалировании переносим статус; upsert не затрёт accepted/done
        initial_status = mapped_status if mapped_status != "expired" else "expired"
        payload = {
            "target_date": pr.target_date.strftime("%d.%m.%Y"),
            "room_label": room_label,
            "room_type": pr.room_type,
            "current_price": int(pr.current_price) if pr.current_price else None,
            "rec_min": int(pr.recommended_price_min)
            if pr.recommended_price_min is not None
            else None,
            "rec_max": int(pr.recommended_price_max)
            if pr.recommended_price_max is not None
            else None,
            "selected_price": int(selected) if selected is not None else None,
            "check_hours": fc.rollback_check_hours,
            "forecast_occupancy": snap.get("occupancy_pct"),
            "competitor_median": snap.get("market_median"),
            "rollback_occupancy": fc.rollback_occupancy_below,
            "price_rec_id": pr.id,
        }
        evidence = {
            **snap,
            "what_happens": what,
            "reason": pr.reason,
            "price_recommendation_id": pr.id,
            "confidence": pr.confidence,
        }
        title = f"Проверить цены на {pr.target_date.strftime('%d.%m.%Y')} — {room_label}"
        if tmpl_name == "price_increase":
            title = f"Повысить цену на {pr.target_date.strftime('%d.%m.%Y')} — {room_label}"
        elif tmpl_name == "price_decrease":
            title = f"Снизить цену на {pr.target_date.strftime('%d.%m.%Y')} — {room_label}"

        due = datetime.combine(pr.target_date, datetime.min.time()) - timedelta(hours=12)
        rec = RecommendationRecord(
            source_module="forecast",
            recommendation_type=tmpl_name,
            title=title,
            summary=pr.reason or tmpl["expected_result"],
            priority=priority,
            status=initial_status,
            target_date=pr.target_date,
            due_at=due if due > datetime.now() else _due_at(),
            owner=_owner(),
            instruction_template=tmpl_name,
            instruction_payload_json=payload,
            evidence_snapshot_json=evidence,
            expected_result=tmpl["expected_result"],
            # Критерии и откат — только из шаблона при рендере (без дублей в JSON)
            success_criteria_json={},
            rollback_plan="",
            source_ref=f"price:{pr.id}",
        )
        upsert_recommendation(rec)
        count += 1
    logger.info("Sync price recommendations: %s", count)
    return count


def build_system_recommendations() -> int:
    """Системные рекомендации из errors_log / reports_log / качества прогноза."""
    cfg = get_config()
    tech_priority = cfg.recommendations.tech_priority or "critical"
    created = 0

    errors = get_errors_log(resolved=False, limit=50)
    for err in errors:
        src = (err.source or "").lower()
        et = (err.error_type or "").lower()
        msg = (err.message or "").lower()
        tmpl = None
        if "travelline" in src or "webpms" in src or "travelline" in et:
            tmpl = "travelline_sync_error"
        elif "sheet" in src or "google" in src:
            tmpl = "sheets_access_error"
        elif "email" in src or "smtp" in src or "mail" in src:
            tmpl = "email_delivery_error"
        elif "competitor" in src:
            tmpl = "competitor_data_error"
        if tmpl is None:
            continue
        digest = hashlib.sha1(
            f"{err.source}:{err.error_type}:{err.message}".encode("utf-8")
        ).hexdigest()[:12]
        t = get_template(tmpl)
        rec = RecommendationRecord(
            source_module="system",
            recommendation_type=tmpl,
            title={
                "travelline_sync_error": "TravelLine не синхронизируется",
                "sheets_access_error": "Нет доступа к Google Sheets",
                "email_delivery_error": "Сбой отправки email-отчёта",
                "competitor_data_error": "Ошибка данных конкурентов",
            }.get(tmpl, "Техническая ошибка"),
            summary=(err.message or "")[:400],
            priority=tech_priority,
            status="new",
            due_at=_due_at(8),
            owner="Технический администратор",
            instruction_template=tmpl,
            instruction_payload_json={
                "error_source": err.source,
                "error_type": err.error_type,
                "check_hours": 8,
            },
            evidence_snapshot_json={
                "what_happens": [err.message or "Ошибка без текста"],
                "error_message": err.message,
                "error_details": (err.details or "")[:500],
                "source": err.source,
                "error_type": err.error_type,
            },
            expected_result=t["expected_result"],
            success_criteria_json={},
            rollback_plan="",
            source_ref=f"error:{digest}",
        )
        upsert_recommendation(rec)
        created += 1

    for rep in get_reports_log(limit=20):
        if rep.status in ("sent", "ok", "dry_run"):
            continue
        if rep.report_type and "week" not in (rep.report_type or "").lower() and "email" not in (
            rep.report_type or ""
        ).lower():
            if rep.report_type not in ("email", "weekly", "weekly_email"):
                continue
        t = get_template("email_delivery_error")
        ref = f"report_fail:{rep.report_type}:{rep.report_date}"
        upsert_recommendation(
            RecommendationRecord(
                source_module="reports",
                recommendation_type="email_delivery_error",
                title="Не отправлен еженедельный отчёт",
                summary=f"Статус {rep.status} за {rep.report_date}",
                priority="high",
                status="new",
                due_at=_due_at(24),
                owner=_owner(),
                instruction_template="email_delivery_error",
                instruction_payload_json={"check_hours": 24},
                evidence_snapshot_json={
                    "what_happens": [
                        f"Отчёт {rep.report_type} за {rep.report_date}: статус {rep.status}."
                    ],
                    "report_type": rep.report_type,
                    "report_status": rep.status,
                },
                expected_result=t["expected_result"],
                success_criteria_json={},
                rollback_plan="",
                source_ref=ref,
            )
        )
        created += 1

    run = get_latest_forecast_run(7)
    if run and run.data_quality in ("low", "poor", "insufficient"):
        t = get_template("forecast_data_insufficient")
        upsert_recommendation(
            RecommendationRecord(
                source_module="settings",
                recommendation_type="forecast_data_insufficient",
                title="Истории недостаточно для прогноза",
                summary=f"Качество данных прогноза: {run.data_quality}",
                priority="high",
                status="new",
                due_at=_due_at(72),
                owner=_owner(),
                instruction_template="forecast_data_insufficient",
                instruction_payload_json={"check_hours": 72},
                evidence_snapshot_json={
                    "what_happens": [
                        f"Последний расчёт h=7: data_quality={run.data_quality}."
                    ],
                    "data_quality": run.data_quality,
                    "model_version": run.model_version,
                },
                expected_result=t["expected_result"],
                success_criteria_json={},
                rollback_plan="",
                source_ref="forecast_quality:h7",
            )
        )
        created += 1

    logger.info("System recommendations upserted: %s", created)
    return created


def build_external_trends_payload(days: int = 90, limit: int = 12) -> list[dict[str, Any]]:
    """Только проверенные тренды из БД для передачи в ИИ."""
    out: list[dict[str, Any]] = []
    for t in get_trends_records(days=days)[:limit]:
        if not t.source_url:
            continue
        published = t.published_at.isoformat() if t.published_at else None
        if not published:
            continue
        region = (t.region or "").lower()
        local = region in ("tomsk", "siberia")
        out.append(
            {
                "title": t.title,
                "region": t.region,
                "category": t.category,
                "summary": t.summary,
                "source_url": t.source_url,
                "published_at": published,
                "evidence_level": "source_confirmed",
                "local_confirmation": local,
                "trend_id": t.id,
            }
        )
    return out


def build_trend_pilot_recommendations(limit: int = 5) -> int:
    """Пилоты по внешним трендам без локального подтверждения."""
    created = 0
    for item in build_external_trends_payload(limit=limit):
        if item.get("local_confirmation"):
            continue
        region = item["region"]
        tid = item.get("trend_id")
        if tid is None:
            continue
        t = get_template("trend_pilot")
        pub = item["published_at"]
        pilot = (
            f"подключить практику «{item['title']}» на 3 квартирах на 30 дней "
            "(без дорогой автоматизации)"
        )
        metrics = (
            "число поздних заездов, время администратора, оценка гостей, число ошибок"
        )
        scale = "не менее 80% успешных операций пилота без роста обращений"
        upsert_recommendation(
            RecommendationRecord(
                source_module="trends",
                recommendation_type="trend_pilot",
                title=f"Пилот: {item['title']}",
                summary=(
                    f"Уровень: {region} → потенциальная адаптация для Томска. "
                    f"Факт подтверждён источником от {pub}."
                ),
                priority="low" if region in ("world",) else "medium",
                status="new",
                due_at=_due_at(24 * 14),
                owner=_owner(),
                instruction_template="trend_pilot",
                instruction_payload_json={
                    "trend_title": item["title"],
                    "trend_region": region,
                    "source_url": item["source_url"],
                    "published_at": pub,
                    "pilot_plan": pilot,
                    "success_metrics": metrics,
                    "pilot_days": 30,
                    "scale_condition": scale,
                    "check_hours": 24 * 30,
                },
                evidence_snapshot_json={
                    # Только контекст; пилот/метрики/критерий — в шагах и проверке
                    "what_happens": [
                        f"Тренд: {item['title']}.",
                        f"Уровень: {region} → потенциальная адаптация для Томска.",
                        f"Факт: практика подтверждена источником от {pub}.",
                        f"Гипотеза: {item['summary']}",
                        "Применимость к 1apart: средняя (требует пилота).",
                    ],
                    "external_trend": item,
                    "local_confirmation": False,
                },
                expected_result=t["expected_result"],
                success_criteria_json={},
                rollback_plan="",
                source_ref=f"trend:{tid}",
            )
        )
        created += 1
    return created


def refresh_recommendations_center() -> dict[str, int]:
    """Полное обновление Центра: expire + sync + system + trends."""
    expired = expire_overdue_recommendations()
    price_n = sync_price_recommendations()
    sys_n = build_system_recommendations()
    trend_n = build_trend_pilot_recommendations()
    summary = count_recommendations_summary()
    return {
        "expired": expired,
        "price": price_n,
        "system": sys_n,
        "trends": trend_n,
        **summary,
    }
