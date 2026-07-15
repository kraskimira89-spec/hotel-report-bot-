"""Точка входа: планировщик и/или веб-сервер."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

import uvicorn

from src.config import get_config
from src.scheduler import start_scheduler
from src.utils.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def run_web() -> None:
    """Запустить FastAPI через uvicorn."""
    cfg = get_config()
    uvicorn.run(
        "src.web.app:app",
        host=cfg.web.host,
        port=cfg.web.port,
        log_level="info",
        log_config=None,  # не перетирать наши handlers (logs/ + консоль)
    )


def run_scheduler_blocking() -> None:
    """Запустить планировщик и ждать сигнала остановки."""
    scheduler = start_scheduler()
    stop_event = threading.Event()

    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Сигнал %s, остановка планировщика...", signum)
        scheduler.shutdown(wait=False)
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Планировщик запущен. Ctrl+C для остановки.")
    stop_event.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="hotel-report-bot")
    parser.add_argument("--web", action="store_true", help="Запустить веб-админку")
    parser.add_argument("--scheduler", action="store_true", help="Запустить планировщик")
    parser.add_argument("--all", action="store_true", help="Планировщик + веб")
    args = parser.parse_args()

    if not any([args.web, args.scheduler, args.all]):
        parser.print_help()
        sys.exit(0)

    if args.all:
        sched = start_scheduler()
        logger.info("Режим --all: планировщик + веб")
        try:
            run_web()
        finally:
            sched.shutdown(wait=False)
    elif args.scheduler:
        run_scheduler_blocking()
    elif args.web:
        run_web()


if __name__ == "__main__":
    main()
