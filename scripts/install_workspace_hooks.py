#!/usr/bin/env python3
"""Установить hooks.json в родительский workspace (1apart/)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_TEMPLATE = _REPO / ".cursor" / "hooks.workspace-root.json.example"
_TARGET_DIR = _REPO.parent / ".cursor"
_TARGET = _TARGET_DIR / "hooks.json"


def main() -> int:
    if not _TEMPLATE.is_file():
        print(f"Нет шаблона: {_TEMPLATE}", file=sys.stderr)
        return 1
    _TARGET_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_TEMPLATE, _TARGET)
    data = json.loads(_TARGET.read_text(encoding="utf-8"))
    print(f"OK: {_TARGET}")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("\nПерезапустите Cursor или откройте workspace 1apart/ заново.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
