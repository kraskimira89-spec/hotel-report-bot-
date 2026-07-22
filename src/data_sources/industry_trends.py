"""Отбор и форматирование отраслевых трендов для weekly email."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, timedelta
from urllib.parse import urlparse

from src.config import AppConfig, get_config
from src.notifiers.weekly.models import IndustryTrendCard
from src.storage.db import (
    get_approved_trends_for_email,
    log_trends_in_email,
    update_trend_ai_fields,
)
from src.storage.models import TrendRecord

logger = logging.getLogger(__name__)

INDUSTRY_CATEGORIES: list[str] = [
    "Динамическое ценообразование",
    "Прямые бронирования",
    "OTA и комиссии",
    "Повторные гости и лояльность",
    "Бесконтактное заселение",
    "Автоматизация и ИИ",
    "Репутация и отзывы",
    "Длительное проживание",
    "Корпоративные клиенты",
    "Регулирование",
    "Рынок апарт-отелей",
]

REGION_LABELS: dict[str, str] = {
    "tomsk": "Томск",
    "siberia": "Сибирь",
    "russia": "Россия",
    "moscow": "Москва",
    "spb": "Санкт-Петербург",
    "world": "Мир",
    "ru": "Россия",
}

LEADING_REGIONS = frozenset({"moscow", "spb", "world"})

REGION_PRIORITY: dict[str, int] = {
    "tomsk": 0,
    "siberia": 1,
    "russia": 2,
    "ru": 2,
    "moscow": 3,
    "spb": 3,
    "world": 4,
}

APPLICABILITY_PRIORITY: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

HOTEL_KEYWORDS = (
    "hotel",
    "apart",
    "апарт",
    "гостин",
    "туризм",
    "booking",
    "hospitality",
    "short-stay",
    "проживан",
)


def content_hash(title: str, source_url: str) -> str:
    raw = f"{title.strip().lower()}|{source_url.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def region_label(region: str) -> str:
    return REGION_LABELS.get(region, region)


def is_leading_region(region: str) -> bool:
    return region in LEADING_REGIONS


def score_trend_relevance(record: TrendRecord, config: AppConfig | None = None) -> float:
    """Оценка 0–100 для отбора в email."""
    _ = config
    score = 40.0
    text = f"{record.title} {record.summary}".lower()
    if any(kw in text for kw in HOTEL_KEYWORDS):
        score += 20.0
    score += max(0, 20 - REGION_PRIORITY.get(record.region, 5) * 4)
    if record.evidence_level == "official":
        score += 15.0
    elif record.evidence_level == "research":
        score += 10.0
    elif record.evidence_level == "industry_media":
        score += 5.0
    if record.published_at:
        age = (date.today() - record.published_at).days
        if age <= 7:
            score += 10.0
        elif age <= 14:
            score += 5.0
        elif age > 30 and record.trend_type != "regulation":
            score -= 30.0
    if record.local_applicability == "high":
        score += 10.0
    elif record.local_applicability == "low":
        score -= 5.0
    return min(100.0, max(0.0, round(score, 1)))


def enrich_trend_rule_based(record: TrendRecord) -> dict[str, str]:
    """Rule-based карточка без LLM."""
    fact = record.ai_fact or record.summary
    applicability = record.ai_applicability or record.takeaway
    risk = record.ai_risk_opportunity or (
        "Возможность" if record.trend_type == "opportunity" else "Требует проверки"
    )
    action = record.ai_safe_step or record.recommended_pilot or record.takeaway
    if is_leading_region(record.region):
        applicability = (
            f"{applicability} Опережающий тренд: применимость к Томску требует проверки."
        )
    return {
        "ai_fact": fact,
        "ai_applicability": applicability,
        "ai_risk_opportunity": risk,
        "ai_safe_step": action,
    }


def enrich_trend_with_llm(record: TrendRecord, use_llm: bool = True) -> dict[str, str]:
    """LLM-обогащение с rule-based fallback."""
    fallback = enrich_trend_rule_based(record)
    if not use_llm:
        return fallback
    try:
        from src.data_sources.industry_trends_llm import generate_trend_card

        result = generate_trend_card(record)
        if result:
            merged = {**fallback, **{k: v for k, v in result.items() if v}}
            return merged
    except Exception as exc:
        logger.debug("LLM trend enrich skipped: %s", exc)
    return fallback


def format_industry_trend_card(record: TrendRecord, index: int) -> IndustryTrendCard:
    fields = enrich_trend_rule_based(record)
    for_1apart = record.recommended_pilot or fields["ai_applicability"]
    return IndustryTrendCard(
        trend_id=record.id,
        index=index,
        title=record.title,
        region_label=region_label(record.region),
        what_happened=fields["ai_fact"],
        why_important=fields["ai_applicability"],
        for_1apart=for_1apart,
        action=fields["ai_safe_step"],
        source_name=record.source_name or urlparse(record.source_url).netloc or "источник",
        source_url=record.source_url,
        published_at=record.published_at,
        is_leading_trend=is_leading_region(record.region),
    )


def select_industry_trends_for_email(
    *,
    report_date: date,
    period_start: date,
    period_end: date,
    config: AppConfig | None = None,
    use_llm: bool = False,
    log_inclusion: bool = True,
) -> list[IndustryTrendCard]:
    """Top-N approved trends для Block 9."""
    cfg = config or get_config()
    mn = cfg.market_news
    records = get_approved_trends_for_email(
        max_age_days=mn.max_age_days,
        min_relevance=mn.min_relevance_for_email,
        dedup_days=mn.dedup_weeks * 7,
        limit=mn.max_email_items,
    )
    cards: list[IndustryTrendCard] = []
    trend_ids: list[int] = []
    for idx, record in enumerate(records, start=1):
        if use_llm and record.id:
            fields = enrich_trend_with_llm(record, use_llm=True)
            update_trend_ai_fields(
                record.id,
                ai_fact=fields.get("ai_fact"),
                ai_applicability=fields.get("ai_applicability"),
                ai_risk_opportunity=fields.get("ai_risk_opportunity"),
                ai_safe_step=fields.get("ai_safe_step"),
            )
        cards.append(format_industry_trend_card(record, idx))
        if record.id:
            trend_ids.append(record.id)
    if log_inclusion and trend_ids:
        log_trends_in_email(trend_ids, report_date, period_start, period_end)
    return cards


def enrich_pending_trends(*, use_llm: bool = False, config: AppConfig | None = None) -> int:
    """Обогатить candidate-тренды: score, AI-поля, auto-approve для official+high."""
    from src.storage.db import get_trends_records

    cfg = config or get_config()
    updated = 0
    for record in get_trends_records(days=cfg.market_news.max_age_days):
        if record.status not in ("candidate", ""):
            continue
        if not record.id:
            continue
        score = score_trend_relevance(record, cfg)
        fields = enrich_trend_with_llm(record, use_llm=use_llm)
        new_status = record.status or "candidate"
        if (
            record.evidence_level == "official"
            and score >= 80
            and record.region in ("tomsk", "siberia", "russia", "ru")
        ):
            new_status = "approved"
        update_trend_ai_fields(
            record.id,
            ai_fact=fields.get("ai_fact"),
            ai_applicability=fields.get("ai_applicability"),
            ai_risk_opportunity=fields.get("ai_risk_opportunity"),
            ai_safe_step=fields.get("ai_safe_step"),
            relevance_score=score,
        )
        if new_status == "approved" and record.status != "approved":
            from src.storage.db import update_trend_status

            update_trend_status(record.id, "approved")
        updated += 1
    return updated


def create_trend_pilot_recommendation(trend_id: int) -> int | None:
    """Создать пилот-рекомендацию из тренда (без автоматического внедрения)."""
    from datetime import datetime, timedelta

    from src.storage.db import get_trend_by_id, upsert_recommendation
    from src.storage.models import RecommendationRecord

    record = get_trend_by_id(trend_id)
    if record is None:
        return None
    fields = enrich_trend_rule_based(record)
    pilot = record.recommended_pilot or fields["ai_safe_step"]
    leading = is_leading_region(record.region)
    summary = (
        f"Тренд: {record.title}\n"
        f"Статус: {'опережающий рынок' if leading else 'локальный/отраслевой сигнал'}.\n"
        f"Рекомендация: {pilot}\n"
        f"Метрика: доля успешных действий, обращения гостей, время администратора.\n"
        f"Срок проверки: 30 дней."
    )
    rec = RecommendationRecord(
        source_module="trends",
        recommendation_type="trend_pilot",
        title=f"Пилот по тренду: {record.title[:80]}",
        summary=summary,
        priority="medium",
        status="new",
        due_at=datetime.now() + timedelta(days=30),
        instruction_template="trend_pilot",
        instruction_payload_json={
            "trend_id": trend_id,
            "source_url": record.source_url,
            "pilot_action": pilot,
        },
        evidence_snapshot_json={
            "trend_title": record.title,
            "region": record.region,
            "category": record.category,
            "relevance_score": record.relevance_score,
        },
        expected_result="Пилот завершён, метрики зафиксированы",
        success_criteria_json={"items": ["Метрики собраны за 30 дней", "Решение принято"]},
        source_ref=f"trend:{trend_id}",
    )
    return upsert_recommendation(rec)


def source_name_from_url(url: str) -> str:
    netloc = urlparse(url).netloc or url
    return re.sub(r"^www\.", "", netloc)
