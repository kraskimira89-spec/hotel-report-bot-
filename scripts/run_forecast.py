#!/usr/bin/env python3
"""Ручной пересчёт прогнозов (все горизонты из config)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.forecast.service import run_forecast_refresh
from src.storage.db import init_db
from src.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Пересчёт прогноза загрузки и цен")
    parser.add_argument(
        "--horizon",
        type=int,
        action="append",
        help="Горизонт в днях (можно указать несколько раз)",
    )
    args = parser.parse_args()
    setup_logging()
    init_db()
    stats = run_forecast_refresh(horizons=args.horizon or None)
    logger.info("Готово: %s", stats)


if __name__ == "__main__":
    main()
