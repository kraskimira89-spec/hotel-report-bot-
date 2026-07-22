#!/usr/bin/env python3
"""Автокоммит + push после завершения задания (обёртка над post_task_commit)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".cursor" / "hooks" / "post_task_commit.py"


def main() -> int:
    if not HOOK.is_file():
        print(f"Нет hook: {HOOK}", file=sys.stderr)
        return 1
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=ROOT,
        input="{}",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
