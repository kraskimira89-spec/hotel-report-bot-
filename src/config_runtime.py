"""Runtime-переопределения конфигурации из SQLite (без рестарта)."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

import yaml

from src.config import AppConfig, _load_yaml, _project_root, get_env_settings

logger = logging.getLogger(__name__)

RUNTIME_KEY = "config_overrides"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивное слияние словарей."""
    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_runtime_overrides() -> dict[str, Any]:
    """Прочитать переопределения из БД."""
    from src.storage.db import get_runtime_setting

    try:
        raw = get_runtime_setting(RUNTIME_KEY)
    except Exception as exc:
        logger.debug("runtime_settings недоступны: %s", exc)
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Некорректный JSON в runtime_settings")
        return {}


def save_runtime_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """Сохранить переопределения в БД (merge с существующими)."""
    from src.storage.db import set_runtime_setting

    current = load_runtime_overrides()
    merged = deep_merge(current, overrides)
    set_runtime_setting(RUNTIME_KEY, json.dumps(merged, ensure_ascii=False))
    return merged


def merge_yaml_with_runtime(yaml_data: dict[str, Any]) -> dict[str, Any]:
    """Объединить settings.yaml и runtime-переопределения."""
    overrides = load_runtime_overrides()
    if not overrides:
        return yaml_data
    return deep_merge(yaml_data, overrides)


def persist_dry_run_to_yaml(dry_run: bool) -> None:
    """Дублировать dry_run в settings.yaml, если файл доступен."""
    env = get_env_settings()
    yaml_path = _project_root() / env.settings_path
    if yaml_path.name == "settings.example.yaml":
        return
    if not yaml_path.exists():
        return
    try:
        data = _load_yaml(yaml_path)
        data["dry_run"] = dry_run
        with yaml_path.open("w", encoding="utf-8") as handle:
            yaml.dump(
                data,
                handle,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
    except OSError as exc:
        logger.warning("Не удалось записать dry_run в %s: %s", yaml_path, exc)


def build_config_from_sources() -> AppConfig:
    """Собрать AppConfig: YAML + runtime overrides."""
    env = get_env_settings()
    yaml_path = _project_root() / env.settings_path
    data = _load_yaml(yaml_path)
    merged = merge_yaml_with_runtime(data)
    webhook_url = env.max_webhook_url.strip()
    if webhook_url:
        max_bot = dict(merged.get("max_bot") or {})
        max_bot["webhook_url"] = webhook_url
        merged["max_bot"] = max_bot
    return AppConfig(**merged)
