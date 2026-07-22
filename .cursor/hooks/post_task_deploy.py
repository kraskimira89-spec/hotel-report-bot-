#!/usr/bin/env python3
"""Cursor hook: автодеплой после stop (логи в logs/post_task_deploy.log)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _ROOT / "logs"
_LOG_FILE = _LOG_DIR / "post_task_deploy.log"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _log(message: str) -> None:
    line = message.rstrip()
    print(line, file=sys.stderr)
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().isoformat(timespec="seconds")
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")
    except OSError:
        pass


def main() -> int:
    try:
        json.load(sys.stdin)
    except json.JSONDecodeError:
        pass

    _log("post_task_deploy: start")
    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "deploy_after_task.py"), "--trigger", "cursor_agent"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=960,
    )
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if out:
        _log(f"post_task_deploy: {out}")
    if result.returncode != 0:
        _log(f"post_task_deploy: exit={result.returncode} {err or 'failed'}")
    else:
        _log("post_task_deploy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
