#!/usr/bin/env python3
"""Проверка Cursor hooks: commit, deploy, пути workspace."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _run(cmd: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=cwd or _ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out


def main() -> int:
    ok = True
    checks: list[dict[str, object]] = []

    # Git repo
    code, out = _run(["git", "rev-parse", "--show-toplevel"])
    git_ok = code == 0
    checks.append({"git_repo": git_ok, "root": out if git_ok else str(_ROOT)})
    ok &= git_ok

    # Hook scripts
    commit_hook = _ROOT / ".cursor" / "hooks" / "post_task_commit.py"
    deploy_hook = _ROOT / ".cursor" / "hooks" / "post_task_deploy.py"
    hooks_json = _ROOT / ".cursor" / "hooks.json"
    for label, path in [
        ("commit_hook", commit_hook),
        ("deploy_hook", deploy_hook),
        ("hooks_json", hooks_json),
    ]:
        exists = path.is_file()
        checks.append({label: exists, "path": str(path)})
        ok &= exists

    # Dry-run commit hook
    code, out = _run(
        [sys.executable, str(commit_hook), "--dry-run"],
        cwd=_ROOT,
    )
    stdin_sim = subprocess.run(
        [sys.executable, str(commit_hook), "--dry-run"],
        cwd=_ROOT,
        input="{}",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    dry_ok = stdin_sim.returncode == 0
    checks.append({"commit_dry_run": dry_ok, "exit": stdin_sim.returncode})
    ok &= dry_ok

    # Deploy config
    from src.config import get_config, reload_config

    reload_config()
    cfg = get_config()
    deploy_on = cfg.deploy.enabled
    checks.append(
        {
            "deploy_enabled": deploy_on,
            "hint": "deploy.enabled=true или DEPLOY_ENABLED=1 для autopush на VPS",
        }
    )

    # Parent workspace hooks (1apart/)
    parent_hooks = _ROOT.parent / ".cursor" / "hooks.json"
    if parent_hooks.is_file():
        try:
            data = json.loads(parent_hooks.read_text(encoding="utf-8"))
            stop_cmds = [h.get("command") for h in data.get("hooks", {}).get("stop", [])]
            checks.append({"parent_workspace_hooks": True, "stop": stop_cmds})
        except json.JSONDecodeError:
            checks.append({"parent_workspace_hooks": False, "error": "invalid json"})
            ok = False
    else:
        checks.append(
            {
                "parent_workspace_hooks": False,
                "hint": f"Создайте {parent_hooks} или откройте workspace={_ROOT}",
            }
        )

    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    if dry_ok and "DRY-RUN" in (stdin_sim.stdout or ""):
        print("\n--- dry-run preview ---")
        print(stdin_sim.stdout[:1500])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
