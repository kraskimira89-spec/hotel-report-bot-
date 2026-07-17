#!/usr/bin/env python3
"""Диагностика: почему парсеры событий дают 0."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bs4 import BeautifulSoup

from src.config import get_config, reload_config
from src.events.collector import fetch_source_html
from src.events.parsers import parse_events_from_html


SELECTORS = {
    "tomsk_kassy": ".event-card, .kassy-event, li.event",
    "ticketland_tomsk": ".event-item, .afisha-item, article.event",
    "tomsk_philharmonic": "article.event, .afisha-row, .concert-item",
    "tusur_events": ".news-item, article, .event-card",
}


def main() -> int:
    reload_config()
    cfg = get_config()
    today = date.today()
    horizon = today + timedelta(days=cfg.events.horizon_days)
    print(
        f"enabled={cfg.events.enabled} horizon_days={cfg.events.horizon_days} "
        f"today={today} horizon_end={horizon}"
    )
    for s in cfg.events.sources:
        print(f"\n=== {s.name} enabled={s.enabled} url={s.url}")
        html, err = fetch_source_html(s, force=True)
        print(f"err={err!r} html_len={len(html or '')}")
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        sel = SELECTORS.get(s.name, ".event, article")
        hits = soup.select(sel)
        print(f"selector_hits={len(hits)} sel={sel!r}")
        classes: set[str] = set()
        for tag in soup.find_all(True)[:800]:
            for c in (tag.get("class") or [])[:4]:
                cl = str(c).lower()
                if any(k in cl for k in ("event", "afisha", "concert", "news", "card", "date", "show")):
                    classes.add(str(c))
        print("interesting_classes=", sorted(classes)[:30])
        # sample first dates/titles in page text
        sample_dates = []
        for m in __import__("re").findall(
            r"\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+[а-яА-Я]{3,10}\w*\s+\d{4}",
            soup.get_text(" ", strip=True)[:5000],
        )[:8]:
            sample_dates.append(m)
        print("sample_dates_in_text=", sample_dates)
        parsed = parse_events_from_html(html, s.name, s.url, today, horizon)
        print(f"parsed={len(parsed)}")
        for ev in parsed[:5]:
            print(f"  - {ev.start_at} | {ev.title[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
