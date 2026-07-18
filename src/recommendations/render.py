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


def _norm_text(text: str) -> str:
    return " ".join(str(text).casefold().replace(";", " ").split())


def dedupe_texts(items: list[str]) -> list[str]:
    """Убрать точные и «склеенные» дубли (A; B vs A + B)."""
    cleaned: list[str] = []
    for raw in items:
        t = " ".join(str(raw).split()).strip()
        if not t or t == "—":
            continue
        cleaned.append(t)

    atomics = [t for t in cleaned if ";" not in t]
    joined = [t for t in cleaned if ";" in t]

    out: list[str] = []
    seen: set[str] = set()
    for t in atomics:
        n = _norm_text(t)
        if n in seen:
            continue
        seen.add(n)
        out.append(t)

    for t in joined:
        parts = [p.strip() for p in t.split(";") if p.strip()]
        if parts and all(_norm_text(p) in seen for p in parts):
            continue
        for p in parts:
            pn = _norm_text(p)
            if pn in seen:
                continue
            seen.add(pn)
            out.append(p)
        if not parts:
            n = _norm_text(t)
            if n not in seen:
                seen.add(n)
                out.append(t)
    return out


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

    steps = dedupe_texts([substitute(s, variables) for s in tmpl["steps"]])
    success = [substitute(s, variables) for s in tmpl["success_criteria"]]
    if rec.success_criteria_json:
        for item in rec.success_criteria_json.get("items") or []:
            success.append(substitute(str(item), variables))
    success = dedupe_texts(success)

    rollback = [substitute(s, variables) for s in tmpl["rollback_steps"]]
    if rec.rollback_plan:
        rollback.append(substitute(rec.rollback_plan, variables))
    rollback = dedupe_texts(rollback)

    goal = substitute(rec.expected_result or tmpl["expected_result"] or tmpl["goal"], variables)
    goal_detail = substitute(tmpl["goal"], variables)
    if _norm_text(goal) == _norm_text(goal_detail):
        goal_detail = ""

    what_rendered = dedupe_texts([substitute(x, variables) for x in what_happens])
    # Не повторять в «Что происходит» критерии/откат/шаги и блоки пилота
    skip_norms = {_norm_text(x) for x in success + rollback + steps}
    _moved_prefixes = (
        "пилот:",
        "метрики:",
        "условие масштабирования:",
    )

    def _keep_what(line: str) -> bool:
        n = _norm_text(line)
        if n in skip_norms:
            return False
        for prefix in _moved_prefixes:
            if n.startswith(prefix):
                return False
        return True

    what_rendered = [x for x in what_rendered if _keep_what(x)]

    check_hours = variables.get("check_hours", 24)
    expected = substitute(rec.expected_result or tmpl["expected_result"], variables)
    check_text = f"Проверить через: {_fmt(check_hours)} ч."
    if expected and _norm_text(expected) != _norm_text(goal):
        check_text += f" Ожидаемый результат: {expected}"

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
        "what_happens": what_rendered,
        "goal": goal,
        "goal_detail": goal_detail,
        "preconditions": dedupe_texts(
            [substitute(p, variables) for p in tmpl["preconditions"]]
        ),
        "steps": steps,
        "success_criteria": success,
        "check_text": check_text,
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
