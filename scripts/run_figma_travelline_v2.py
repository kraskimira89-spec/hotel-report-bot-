#!/usr/bin/env python3
"""Создать TravelLine v2 в Figma Slides через MCP (create_new_file + use_figma)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECK_JS = ROOT / "scripts" / "figma" / "travelline_v2_deck.js"
FILE_NAME = "TravelLine · партнёрское предложение v2"


def _read_deck_script() -> str:
    return DECK_JS.read_text(encoding="utf-8")


def _print_manual_steps() -> None:
    print(
        """
╔══════════════════════════════════════════════════════════════╗
║  Figma MCP не подключён                                      ║
╠══════════════════════════════════════════════════════════════╣
║  1. Cursor → Settings → MCP → Figma → Connect                ║
║  2. Повторите: python scripts/run_figma_travelline_v2.py    ║
║                                                              ║
║  Или вручную:                                                ║
║  • /figma-create-new-file slides TravelLine v2               ║
║  • Вставьте scripts/figma/travelline_v2_deck.js в use_figma ║
╚══════════════════════════════════════════════════════════════╝
"""
    )
    print(f"Спецификация: docs/presentations/travelline/figma-design-spec.md")
    print(f"Скрипт deck:  {DECK_JS}")


def main() -> int:
    if not DECK_JS.is_file():
        print(f"Нет файла: {DECK_JS}", file=sys.stderr)
        return 1

    # Попытка через Cursor MCP недоступна из subprocess — инструкция для агента/пользователя
    _print_manual_steps()
    print("\n--- Превью: первые 40 строк deck.js ---")
    lines = _read_deck_script().splitlines()
    print("\n".join(lines[:40]))
    print(f"\n... всего {len(lines)} строк, {len(_read_deck_script())} символов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
