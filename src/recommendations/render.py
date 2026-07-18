"""Рендер инструкции из шаблона + payload (без выдуманных цифр)."""

from __future__ import annotations

import re
from typing import Any

from src.recommendations.templates_lib import (
    MODULE_LABELS,
    PRIORITY_LABELS,
    STATUS_LABELS,
    get_template,
    template_vars_merge,
)
from src.storage.models import RecommendationRecord

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return f"{value:.1f}"
    return str(value)


def substitute(text: str, variables: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            return "—"
        return _fmt(variables[key])

    return _VAR_RE.sub(repl, text)


def render_instruction_card(rec: RecommendationRecord) -> dict[str, Any]:
    """Собрать блоки карточки для HTML/DOCX."""
    tmpl = get_template(rec.instruction_template)
    variables = template_vars_merge(
        rec.evidence_snapshot_json or {},
        rec.instruction_payload_json or {},
    )
    evidence = rec.evidence_snapshot_json or {}
    what_happens: list[str] = []
    if evidence.get("what_happens"):
        what_happens = list(evidence["what_happens"])
    else:
        for key in (
            "reason",
            "summary_fact",
            "occupancy_line",
            "pickup_line",
            "market_line",
            "event_line",
            "error_message",
        ):
            if evidence.get(key):
                what_happens.append(str(evidence[key]))
        if not what_happens and rec.summary:
            what_happens.append(rec.summary)

    steps = [substitute(s, variables) for s in tmpl["steps"]]
    success = [substitute(s, variables) for s in tmpl["success_criteria"]]
    if rec.success_criteria_json:
        for item in rec.success_criteria_json.get("items") or []:
            success.append(substitute(str(item), variables))
    rollback = [substitute(s, variables) for s in tmpl["rollback_steps"]]
    if rec.rollback_plan:
        rollback.insert(0, substitute(rec.rollback_plan, variables))

    goal = substitute(rec.expected_result or tmpl["expected_result"] or tmpl["goal"], variables)
    goal_detail = substitute(tmpl["goal"], variables)

    return {
        "id": rec.id,
        "title": rec.title,
        "summary": rec.summary,
        "module": rec.source_module,
        "module_label": MODULE_LABELS.get(rec.source_module, rec.source_module),
        "type": rec.recommendation_type,
        "template": rec.instruction_template,
        "priority": rec.priority,
        "priority_label": PRIORITY_LABELS.get(rec.priority, rec.priority),
        "status": rec.status,
        "status_label": STATUS_LABELS.get(rec.status, rec.status),
        "owner": rec.owner,
        "target_date": rec.target_date.isoformat() if rec.target_date else None,
        "due_at": rec.due_at.isoformat(sep=" ", timespec="minutes") if rec.due_at else None,
        "due_hint": substitute(tmpl["due_hint"], variables),
        "what_happens": [substitute(x, variables) for x in what_happens],
        "goal": goal,
        "goal_detail": goal_detail,
        "preconditions": [substitute(p, variables) for p in tmpl["preconditions"]],
        "steps": steps,
        "success_criteria": success,
        "check_text": substitute(
            "Проверить через: {{ check_hours }} ч. Ожидаемый результат: "
            + (rec.expected_result or tmpl["expected_result"]),
            {**variables, "check_hours": variables.get("check_hours", 24)},
        ),
        "rollback_steps": rollback,
        "escalation": substitute(tmpl["escalation"], variables),
        "evidence": evidence,
        "payload": rec.instruction_payload_json or {},
        "completion_note": rec.completion_note,
        "accepted_at": rec.accepted_at.isoformat() if rec.accepted_at else None,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
        "completed_by": rec.completed_by,
        "source_ref": rec.source_ref,
        "actions": {
            "can_accept": rec.status == "new",
            "can_start": rec.status in ("new", "accepted"),
            "can_reject": rec.status in ("new", "accepted", "in_progress"),
            "can_complete": rec.status in ("accepted", "in_progress"),
            "can_problem": rec.status in ("accepted", "in_progress", "done"),
        },
    }
