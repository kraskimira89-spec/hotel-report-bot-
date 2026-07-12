"""Общие фикстуры pytest."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _remove_stale_default_db() -> None:
    """Убрать локальный data/hotel_report.db — runtime dry_run ломает CI-подобные прогоны."""
    db_path = Path("data/hotel_report.db")
    if db_path.exists():
        db_path.unlink()
