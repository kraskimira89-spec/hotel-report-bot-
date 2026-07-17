#!/usr/bin/env python3
"""Дополнить settings.yaml секцией events и новыми источниками."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import _load_yaml, _project_root, get_env_settings


def _merge_sources(existing: list[dict], example: list[dict]) -> tuple[list[dict], int]:
    by_name = {s.get("name"): dict(s) for s in existing if s.get("name")}
    added = 0
    for src in example:
        name = src.get("name")
        if not name:
            continue
        if name not in by_name:
            by_name[name] = dict(src)
            added += 1
        else:
            # дополнить новые ключи, не перетирая url/enabled
            for key, val in src.items():
                if key not in by_name[name]:
                    by_name[name][key] = val
    # сохранить порядок: сначала example, потом лишние из existing
    order = [s["name"] for s in example if s.get("name")]
    for name in by_name:
        if name not in order:
            order.append(name)
    return [by_name[n] for n in order if n in by_name], added


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch events config in settings.yaml")
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
    ex_events = ex.get("events") or {}

    if "events" not in data or not data.get("events"):
        data["events"] = ex_events
        changed = True
        print("-> добавлена секция events из settings.example.yaml")
    else:
        ev = data["events"]
        if not isinstance(ev, dict):
            data["events"] = ex_events
            changed = True
        else:
            for key in (
                "notify_horizon_days",
                "notify_min_impact",
                "notify_min_overnight",
                "refresh_interval_hours",
                "require_approval_score",
                "max_forecast_uplift",
                "collect_cron",
            ):
                if key not in ev and key in ex_events:
                    ev[key] = ex_events[key]
                    changed = True
                    print(f"-> добавлен events.{key}")
            merged, added = _merge_sources(ev.get("sources") or [], ex_events.get("sources") or [])
            if added or len(merged) != len(ev.get("sources") or []):
                ev["sources"] = merged
                changed = True
                print(f"-> источники: +{added}, всего {len(merged)}")
            data["events"] = ev

    if not changed:
        print("Изменений не требуется")
        return 0

    if args.dry_run:
        print(yaml.dump({"events": data["events"]}, allow_unicode=True, sort_keys=False))
        return 0

    target.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"Сохранено: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
