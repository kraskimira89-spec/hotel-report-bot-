#!/usr/bin/env python3
"""Ручной запуск пайплайна событий Томска."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.events.service import run_events_pipeline
from src.storage.db import init_db
from src.utils.logging_setup import setup_logging


def main() -> None:
    setup_logging()
    init_db()
    stats = run_events_pipeline(force=True)
    print("events pipeline:", stats)


if __name__ == "__main__":
    main()
