#!/usr/bin/env python3
"""Генерация PNG для слайдов презентации из export JSON."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import font_manager

_PRES = Path(__file__).resolve().parents[1] / "docs" / "presentations"
ASSETS = _PRES / "assets"
DATA = _PRES / "build" / "presentation_data.json"

GOLD = "#C19B6A"
GOLD_DARK = "#A9824F"
BG = "#FAF8F5"
TEXT = "#1B1B1B"
CARD = "#FFFFFF"
BORDER = "#E8E0D5"


def _setup_style() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "figure.facecolor": BG,
            "axes.facecolor": CARD,
        }
    )


def build_forecast_chart(data: dict) -> Path:
    series = data.get("forecast_30", {}).get("series") or data.get("forecast_7", {}).get("series") or []
    if not series:
        series = data.get("forecast_7", {}).get("series") or []
    fig, ax = plt.subplots(figsize=(8.5, 3.2), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(CARD)
    for spine in ax.spines.values():
        spine.set_color(BORDER)

    dates, occ, lo, hi = [], [], [], []
    for row in series:
        d = row.get("date") or row.get("forecast_date")
        if not d:
            continue
        dates.append(datetime.fromisoformat(str(d)[:10]))
        occ.append(float(row.get("occupancy") or row.get("occupancy_pct") or 0))
        lo.append(float(row.get("lower") or row.get("lower_bound") or 0))
        hi.append(float(row.get("upper") or row.get("upper_bound") or 0))

    if dates:
        ax.fill_between(dates, lo, hi, color=GOLD, alpha=0.25, label="Диапазон прогноза")
        ax.plot(dates, occ, color=GOLD_DARK, linewidth=2.5, marker="o", markersize=3, label="Базовый сценарий")
        ax.set_ylabel("Загрузка, %", color=TEXT, fontsize=10)
        ax.tick_params(colors=TEXT, labelsize=8)
        ax.grid(axis="y", color=BORDER, linewidth=0.8, alpha=0.8)
        fig.autofmt_xdate()
    else:
        ax.text(0.5, 0.5, "Прогноз загрузки\n(данные из админки)", ha="center", va="center", color=TEXT)

    ax.set_title("📈 Прогноз загрузки · раздел «Прогноз»", loc="left", color=TEXT, fontsize=11, pad=10)
    badges = ["7 дн.", "14 дн.", "30 дн.", "180 дн."]
    for i, b in enumerate(badges):
        ax.text(
            0.02 + i * 0.11,
            1.02,
            b,
            transform=ax.transAxes,
            fontsize=8,
            color=GOLD_DARK if b == "30 дн." else "#7A756C",
            fontweight="bold" if b == "30 дн." else "normal",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#F3EBE0", edgecolor=BORDER),
        )
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    out = ASSETS / "forecast_chart.png"
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return out


def build_events_panel(data: dict) -> Path:
    rows = (data.get("events") or {}).get("rows") or []
    samples = [
        ("📅 Конференция", "Деловое мероприятие · высокий спрос"),
        ("🎵 Концерт", "Городское событие · проверить цены"),
        ("🎪 Фестиваль", "Массовое событие · несколько дней"),
        ("🏃 Спорт", "Соревнование · иногородние гости"),
    ]
    if rows:
        icons = {"conference": "📅", "concert": "🎵", "festival": "🎪", "sport": "🏃", "holiday": "🎉"}
        samples = []
        for row in rows[:4]:
            cat = (row.get("category") or "event").lower()
            icon = icons.get(cat, "📅")
            title = row.get("title") or cat.title()
            if len(title) > 42:
                title = title[:39] + "…"
            impact = row.get("impact_score")
            extra = f" · impact {int(impact)}" if impact else ""
            samples.append((f"{icon} {title}", f"Подтверждено · сигнал для проверки{extra}"))

    fig, ax = plt.subplots(figsize=(8.5, 3.6), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")
    ax.set_title("📅 События Томска · раздел «События»", loc="left", color=TEXT, fontsize=11, pad=8)

    x0, y = 0.02, 0.78
    w, h, gap = 0.46, 0.28, 0.04
    for i, (title, sub) in enumerate(samples[:4]):
        col, row_i = i % 2, i // 2
        x = x0 + col * (w + gap)
        y_pos = y - row_i * (h + gap)
        rect = mpatches.FancyBboxPatch(
            (x, y_pos),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            linewidth=1,
            edgecolor=BORDER,
            facecolor=CARD,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(x + 0.03, y_pos + h - 0.07, title, transform=ax.transAxes, fontsize=9, color=TEXT, fontweight="bold")
        ax.text(x + 0.03, y_pos + 0.06, sub, transform=ax.transAxes, fontsize=7.5, color="#7A756C")

    ax.text(
        0.02,
        0.04,
        "Сигнал для своевременной проверки, а не автоматическая смена цены",
        transform=ax.transAxes,
        fontsize=8,
        color=GOLD_DARK,
        style="italic",
    )
    out = ASSETS / "events_panel.png"
    fig.savefig(out, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return out


def build_reco_flow() -> Path:
    fig, ax = plt.subplots(figsize=(4.2, 3.8), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")
    steps = [
        "Данные и сигналы",
        "Рекомендация",
        "Пошаговая\nинструкция",
        "Применение\nи контроль",
    ]
    y = 0.88
    for i, step in enumerate(steps):
        rect = mpatches.FancyBboxPatch(
            (0.08, y - 0.12),
            0.84,
            0.14,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            linewidth=1,
            edgecolor=BORDER,
            facecolor=CARD,
            transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(0.5, y - 0.05, step, ha="center", va="center", transform=ax.transAxes, fontsize=9, color=TEXT)
        if i < len(steps) - 1:
            ax.text(0.5, y - 0.14, "↓", ha="center", transform=ax.transAxes, fontsize=14, color=GOLD)
        y -= 0.22
    out = ASSETS / "reco_flow.png"
    fig.savefig(out, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return out


def main() -> None:
    _setup_style()
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    build_forecast_chart(raw)
    build_events_panel(raw)
    build_reco_flow()
    print("assets ready:", ASSETS)


if __name__ == "__main__":
    main()
