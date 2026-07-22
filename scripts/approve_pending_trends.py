#!/usr/bin/env python3
"""Одобрить candidate-тренды с relevance >= порога (для Block 9 email)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import get_config, reload_config
from src.data_sources.industry_trends import enrich_pending_trends, score_trend_relevance
from src.storage.db import get_trends_records, update_trend_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve high-score industry trends")
    parser.add_argument(
        "--min-score",
        type=float,
        default=60.0,
        help="Минимальный relevance_score для approve",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Сначала enrich_pending_trends",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, без UPDATE",
    )
    args = parser.parse_args()

    reload_config()
    cfg = get_config()
    if args.enrich:
        n = enrich_pending_trends(use_llm=cfg.market_news.enrich_with_llm)
        print(f"enriched: {n}")

    approved = 0
    for record in get_trends_records(days=cfg.market_news.max_age_days):
        if record.status not in ("candidate", ""):
            continue
        if not record.id:
            continue
        score = record.relevance_score or score_trend_relevance(record, cfg)
        if score < args.min_score:
            continue
        print(f"approve id={record.id} score={score} title={record.title[:60]!r}")
        if not args.dry_run:
            update_trend_status(record.id, "approved")
        approved += 1

    print(f"total: {approved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
