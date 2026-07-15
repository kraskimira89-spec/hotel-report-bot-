"""Настройка логирования: консоль + файлы в каталоге logs/."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 10


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def logs_dir() -> Path:
    return project_root() / "logs"


def setup_logging(
    *,
    level: int = logging.INFO,
    directory: Path | None = None,
) -> Path:
    """Включить запись всех логов в logs/ (ротация) и в консоль.

    Повторный вызов безопасен (идемпотентен).
    Возвращает путь к каталогу логов.
    """
    global _CONFIGURED
    log_dir = directory or logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    if _CONFIGURED:
        return log_dir

    formatter = logging.Formatter(LOG_FORMAT)
    root = logging.getLogger()
    root.setLevel(level)

    # Убрать дефолтные хендлеры (например от basicConfig / uvicorn), чтобы не дублировать.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    app_file = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    app_file.setLevel(level)
    app_file.setFormatter(formatter)
    root.addHandler(app_file)

    error_file = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    error_file.setLevel(logging.WARNING)
    error_file.setFormatter(formatter)
    root.addHandler(error_file)

    _CONFIGURED = True
    logging.getLogger(__name__).info("Логи пишутся в %s", log_dir.resolve())
    return log_dir
