"""Автодеплой на VPS (SSH: git pull + docker compose)."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.config import DeployConfig as DeploySettings, get_config, get_env_settings

logger = logging.getLogger(__name__)

_STATE_FILE = Path("data/last_deploy.json")


def _resolve_deploy() -> DeploySettings:
    """Настройки deploy: YAML + переопределение enabled из DEPLOY_ENABLED."""
    cfg = get_config()
    deploy = cfg.deploy.model_copy()
    env = get_env_settings()
    if env.deploy_enabled:
        deploy.enabled = True
    if env.vps_host:
        deploy.ssh_host = env.vps_host
    if env.vps_user:
        deploy.ssh_user = env.vps_user
    if env.vps_app_dir:
        deploy.app_dir = env.vps_app_dir
    if not deploy.ssh_host:
        deploy.ssh_host = "91.229.11.147"
    return deploy


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _state_path() -> Path:
    path = _project_root() / _STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_last_deploy() -> datetime | None:
    path = _state_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("deployed_at")
        if not raw:
            return None
        return datetime.fromisoformat(raw)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


def _write_last_deploy(trigger: str) -> None:
    path = _state_path()
    path.write_text(
        json.dumps(
            {
                "deployed_at": datetime.now(timezone.utc).isoformat(),
                "trigger": trigger,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _within_debounce(deploy: DeploySettings) -> bool:
    last = _read_last_deploy()
    if last is None:
        return False
    elapsed = (datetime.now(timezone.utc) - last.astimezone(timezone.utc)).total_seconds()
    return elapsed < deploy.min_interval_minutes * 60


def _build_remote_command(deploy: DeploySettings) -> str:
    return (
        f"cd {deploy.app_dir} && "
        f"git pull --ff-only && "
        f"docker compose -f {deploy.compose_file} up -d --build"
    )


def run_deploy(trigger: str = "manual", force: bool = False) -> bool:
    """Выполнить деплой на VPS по SSH. Возвращает True при успехе."""
    deploy = _resolve_deploy()
    if not deploy.enabled:
        logger.info("Деплой отключён (deploy.enabled=false)")
        return False
    if not force and _within_debounce(deploy):
        logger.info(
            "Деплой пропущен: debounce %s мин (trigger=%s)",
            deploy.min_interval_minutes,
            trigger,
        )
        return False

    remote = _build_remote_command(deploy)
    target = f"{deploy.ssh_user}@{deploy.ssh_host}"
    logger.info("Деплой на %s (trigger=%s)", target, trigger)

    try:
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", target, remote],
            check=True,
            timeout=900,
            capture_output=True,
            text=True,
        )
        _write_last_deploy(trigger)
        logger.info("Деплой завершён: %s", trigger)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Ошибка деплоя (%s): exit=%s stderr=%s",
            trigger,
            exc.returncode,
            (exc.stderr or "")[:500],
        )
        return False
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.error("Ошибка деплоя (%s): %s", trigger, exc)
        return False


def run_deploy_after_job(job_id: str, job_success: bool) -> bool:
    """Деплой после успешной задачи планировщика (с debounce)."""
    if not job_success:
        return False
    deploy = _resolve_deploy()
    if not deploy.enabled or not deploy.after_jobs:
        return False
    if job_id not in set(deploy.job_ids):
        return False
    return run_deploy(trigger=f"job:{job_id}")
