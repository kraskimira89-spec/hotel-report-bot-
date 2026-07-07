"""Инициализация SQLite, миграции и подключение."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Generator

from src.config import get_config, get_db_path
from src.storage.models import INDEXES, SCHEMA_VERSION, TABLES

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Получить подключение к SQLite с row_factory."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session() -> Generator[sqlite3.Connection, None, None]:
    """Контекстный менеджер с автокоммитом."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создать таблицы, если их нет."""
    with db_session() as conn:
        for ddl in TABLES:
            conn.execute(ddl)
        for idx in INDEXES:
            conn.execute(idx)
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
    logger.info("БД инициализирована: %s", get_db_path())


def migrate() -> None:
    """Применить миграции схемы.

    # TODO: этап 4 — версионированные миграции при изменении схемы.
    """
    init_db()
    with db_session() as conn:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        current = row["version"] if row else 0
        if current < SCHEMA_VERSION:
            conn.execute(
                "UPDATE schema_version SET version = ?",
                (SCHEMA_VERSION,),
            )
            logger.info("Миграция: %s → %s", current, SCHEMA_VERSION)


def cleanup_old_records() -> int:
    """Удалить записи старше retention_days.

    # TODO: этап 4 — вызывать из планировщика ежедневно.
    """
    cfg = get_config()
    cutoff = (datetime.now() - timedelta(days=cfg.storage.retention_days)).strftime(
        "%Y-%m-%d"
    )
    deleted = 0
    with db_session() as conn:
        for table, date_col in [
            ("price_snapshots", "snapshot_date"),
            ("metrics_daily", "report_date"),
            ("bookings_daily", "report_date"),
        ]:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE {date_col} < ?",
                (cutoff,),
            )
            deleted += cur.rowcount
    logger.info("Удалено %s записей старше %s", deleted, cutoff)
    return deleted
