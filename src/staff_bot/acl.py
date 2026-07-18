"""ACL и роли сотрудников внутреннего бота."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import AppConfig, get_config
from src.storage.db import get_staff_user, list_staff_users, upsert_staff_user
from src.storage.models import StaffUserRecord

ROLE_OWNER = "owner"
ROLE_MANAGER = "manager"
ROLE_VIEWER = "viewer"
VALID_ROLES = frozenset({ROLE_OWNER, ROLE_MANAGER, ROLE_VIEWER})

# Команды → минимальная роль
PERMISSIONS: dict[str, str] = {
    "start": ROLE_VIEWER,
    "help": ROLE_VIEWER,
    "summary": ROLE_VIEWER,
    "events": ROLE_VIEWER,
    "problems": ROLE_VIEWER,
    "stop": ROLE_VIEWER,
    "recommendations": ROLE_MANAGER,
    "detail": ROLE_MANAGER,
    "accept": ROLE_MANAGER,
}

_ROLE_RANK = {ROLE_VIEWER: 1, ROLE_MANAGER: 2, ROLE_OWNER: 3}

DENIED_TEXT = "Доступ не предоставлен"


@dataclass(frozen=True)
class AccessResult:
    allowed: bool
    staff: StaffUserRecord | None = None
    reason: str = ""


def sync_staff_from_config(config: AppConfig | None = None) -> int:
    """Синхронизировать сотрудников из settings.yaml в БД."""
    cfg = config or get_config()
    count = 0
    for emp in cfg.staff_bot.employees:
        role = emp.role if emp.role in VALID_ROLES else ROLE_VIEWER
        existing = get_staff_user(emp.user_id)
        upsert_staff_user(
            StaffUserRecord(
                user_id=int(emp.user_id),
                display_name=emp.name,
                role=role,
                is_active=emp.active,
                notify_daily=existing.notify_daily if existing else True,
                notify_critical=existing.notify_critical if existing else True,
                notify_recommendations=(
                    existing.notify_recommendations if existing else True
                ),
                notify_events=existing.notify_events if existing else True,
            )
        )
        count += 1
    return count


def role_allows(role: str, required: str) -> bool:
    return _ROLE_RANK.get(role, 0) >= _ROLE_RANK.get(required, 99)


def check_access(
    user_id: int | None,
    command: str,
    *,
    config: AppConfig | None = None,
) -> AccessResult:
    """Проверить доступ до обработки команды."""
    cfg = config or get_config()
    if not cfg.staff_bot.enabled:
        return AccessResult(False, reason="disabled")
    if user_id is None:
        return AccessResult(False, reason="no_user_id")

    sync_staff_from_config(cfg)
    staff = get_staff_user(int(user_id))

    if staff is None or not staff.is_active:
        return AccessResult(False, reason="not_in_allowlist")

    if cfg.staff_bot.dry_run:
        test_ids = {int(x) for x in cfg.staff_bot.test_user_ids}
        if int(user_id) not in test_ids:
            return AccessResult(False, staff=staff, reason="dry_run_gate")

    required = PERMISSIONS.get(command, ROLE_OWNER)
    if not role_allows(staff.role, required):
        return AccessResult(False, staff=staff, reason="role_denied")

    return AccessResult(True, staff=staff)


def allowed_user_ids(config: AppConfig | None = None) -> set[int]:
    cfg = config or get_config()
    sync_staff_from_config(cfg)
    return {u.user_id for u in list_staff_users(active_only=True)}
