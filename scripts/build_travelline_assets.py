#!/usr/bin/env python3
"""PNG-схемы для презентации TravelLine."""
from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parents[1] / "docs" / "presentations" / "travelline" / "assets"
BG = "#0F172A"
CARD = "#1E293B"
ACCENT = "#38BDF8"
TEXT = "#F1F5F9"
MUTED = "#94A3B8"
BORDER = "#334155"


def _setup() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": BG})


def problem_flow() -> Path:
    fig, ax = plt.subplots(figsize=(8.5, 2.2), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")
    steps = ["Данные\nTravelLine", "Таблицы\nи отчёты", "Ручной\nанализ", "Решение\nс опозданием"]
    x = 0.04
    for i, label in enumerate(steps):
        rect = mpatches.FancyBboxPatch(
            (x, 0.35), 0.19, 0.45,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            facecolor=CARD, edgecolor=BORDER, linewidth=1.2, transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(x + 0.095, 0.57, label, ha="center", va="center", transform=ax.transAxes,
                fontsize=15, color=TEXT, fontweight="bold")
        if i < len(steps) - 1:
            ax.text(x + 0.21, 0.57, "→", ha="center", va="center", transform=ax.transAxes,
                    fontsize=24, color=ACCENT)
        x += 0.24
    path = OUT / "problem_flow.png"
    fig.savefig(path, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return path


def solution_stack() -> Path:
    fig, ax = plt.subplots(figsize=(7.5, 3.0), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")
    layers = [
        ("TravelLine + PMS + доступные источники рынка", CARD),
        ("Прогноз, контроль и рекомендации", "#1D4ED8"),
        ("Понятные действия для владельца и менеджера", "#0E7490"),
    ]
    y = 0.72
    for text, color in layers:
        rect = mpatches.FancyBboxPatch(
            (0.08, y), 0.84, 0.18,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            facecolor=color, edgecolor=BORDER, linewidth=1, transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(0.5, y + 0.09, text, ha="center", va="center", transform=ax.transAxes,
                fontsize=16, color=TEXT, fontweight="bold")
        if y > 0.2:
            ax.text(0.5, y - 0.02, "↓", ha="center", va="center", transform=ax.transAxes,
                    fontsize=22, color=ACCENT)
        y -= 0.28
    path = OUT / "solution_stack.png"
    fig.savefig(path, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return path


def action_chain() -> Path:
    fig, ax = plt.subplots(figsize=(8.5, 1.6), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    ax.axis("off")
    steps = ["Факт", "Рекомендация", "Инструкция", "Контроль"]
    x = 0.03
    for i, label in enumerate(steps):
        rect = mpatches.FancyBboxPatch(
            (x, 0.25), 0.2, 0.5,
            boxstyle="round,pad=0.02,rounding_size=0.02",
            facecolor="#EFF6FF", edgecolor="#3B82F6", linewidth=1.5, transform=ax.transAxes,
        )
        ax.add_patch(rect)
        ax.text(x + 0.1, 0.5, label, ha="center", va="center", transform=ax.transAxes,
                fontsize=16, color="#1E3A8A", fontweight="bold")
        if i < len(steps) - 1:
            ax.text(x + 0.22, 0.5, "→", ha="center", va="center", transform=ax.transAxes,
                    fontsize=22, color="#3B82F6")
        x += 0.24
    path = OUT / "action_chain.png"
    fig.savefig(path, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)
    return path


def main() -> None:
    _setup()
    for fn in (problem_flow, solution_stack, action_chain):
        fn()
    print("assets:", OUT)


if __name__ == "__main__":
    main()
