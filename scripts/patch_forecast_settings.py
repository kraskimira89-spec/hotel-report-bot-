#!/usr/bin/env python3
"""Дополнить settings.yaml секцией forecast и retention_days=730."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import _load_yaml, _project_root, get_env_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch forecast config in settings.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Только показать diff")
    args = parser.parse_args()

    env = get_env_settings()
    target = _project_root() / env.settings_path
    example = _project_root() / "config" / "settings.example.yaml"
    if not target.exists():
        print(f"Файл не найден: {target}")
        return 1

    data = _load_yaml(target)
    ex = _load_yaml(example)
    changed = False

    storage = dict(data.get("storage") or {})
    if int(storage.get("retention_days", 90)) < 730:
        storage["retention_days"] = 730
        data["storage"] = storage
        changed = True
        print("→ storage.retention_days = 730")

    if "forecast" not in data or not data.get("forecast"):
        data["forecast"] = ex.get("forecast", {})
        changed = True
        print("→ добавлена секция forecast из settings.example.yaml")
    elif isinstance(data.get("forecast"), dict) and not data["forecast"]:
        data["forecast"] = {**(ex.get("forecast") or {}), **data["forecast"]}
        changed = True
        print("→ заполнена пустая секция forecast из settings.example.yaml")

    if not changed:
        print("Изменений не требуется")
        return 0

    if args.dry_run:
        print(yaml.dump(data, allow_unicode=True, sort_keys=False)[:800])
        return 0

    target.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"Сохранено: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
