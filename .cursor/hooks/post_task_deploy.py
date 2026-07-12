#!/usr/bin/env python3
"""Cursor hook: автодеплой после завершения задания агента."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    try:
        json.load(sys.stdin)
    except json.JSONDecodeError:
        pass

    result = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "deploy_after_task.py"), "--trigger", "cursor_agent"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=960,
    )
    if result.returncode != 0 and result.stderr:
        print(result.stderr, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
