#!/usr/bin/env python3
"""Разбор реальной разметки источников событий."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.events.parsers import parse_date_range, parse_russian_date

UA = {"User-Agent": "1apart-events-bot/1.0 (+https://1apart.ru)"}


def main() -> int:
    r = httpx.get("https://tomsk.kassy.ru/", headers=UA, follow_redirects=True, timeout=30)
    s = BeautifulSoup(r.text, "lxml")
    print("=== KASSY ===")
    el = s.select_one(".event_link")
    if el:
        p = el.parent
        print("event_link text:", el.get_text(" ", strip=True)[:150])
        print("parent:", p.name, p.get("class"), p.get_text(" ", strip=True)[:220])
        gp = p.parent if p else None
        if gp:
            print("grand:", gp.name, gp.get("class"), gp.get_text(" ", strip=True)[:220])
    # look for list items with dates
    for a in s.select("a[href]")[:200]:
        t = a.get_text(" ", strip=True)
        if "2026" in t and len(t) > 15:
            print("link_with_date:", t[:160], "href=", a.get("href"))
            break

    r2 = httpx.get("https://tomskfil.ru/afisha/", headers=UA, follow_redirects=True, timeout=30)
    s2 = BeautifulSoup(r2.text, "lxml")
    print("\n=== PHIL ===")
    card = s2.select_one(".poster__card")
    if card:
        print("card:", card.get_text(" | ", strip=True)[:280])
        title = card.select_one(".poster__card-title")
        d = card.select_one(".poster__card-date-date") or card.select_one(".poster__card-date")
        dt = d.get_text(" ", strip=True) if d else ""
        print("title:", title.get_text(strip=True) if title else None)
        print("date_text:", dt, "->", parse_russian_date(dt, 2026), parse_date_range(dt, 2026))

    r3 = httpx.get(
        "https://tusur.ru/ru/novosti-i-meropriyatiya",
        headers=UA,
        follow_redirects=True,
        timeout=30,
    )
    s3 = BeautifulSoup(r3.text, "lxml")
    print("\n=== TUSUR ===")
    for item in s3.select(".news-item")[:5]:
        t = item.select_one("h2, h3, .title, a")
        d = item.select_one(".date, time, .news-date")
        print(
            "item classes=",
            item.get("class"),
            "title=",
            (t.get_text(strip=True)[:90] if t else None),
            "date_el=",
            (d.get_text(strip=True) if d else None),
        )
        for x in item.select("[class*=date], time"):
            print("  cand", x.name, x.get("class"), repr(x.get_text(strip=True)[:80]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
