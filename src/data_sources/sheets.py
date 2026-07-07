"""Чтение данных из Google Sheets (gspread + сервисный аккаунт)."""

from __future__ import annotations

import logging
from typing import Any

from src.config import AppConfig, get_config, get_env_settings

logger = logging.getLogger(__name__)


class GoogleSheetsClient:
    """Клиент Google Sheets для листов «Заселяемость» и «Брони статистика»."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self._env = get_env_settings()
        self._client = None

    def _get_client(self) -> Any:
        """Инициализировать gspread-клиент.

        # TODO: этап 1 — авторизация через service account JSON.
        """
        if self._client is None:
            logger.debug("GoogleSheetsClient: заглушка, gspread не подключён")
        return self._client

    def read_occupancy(self) -> list[dict[str, Any]]:
        """Прочитать лист «Заселяемость».

        # TODO: этап 1 — парсинг строк в структурированные записи.
        """
        logger.info("read_occupancy: заглушка (этап 1)")
        return []

    def read_bookings_stats(self) -> list[dict[str, Any]]:
        """Прочитать лист «Брони статистика».

        # TODO: этап 1 — парсинг броней и каналов.
        """
        logger.info("read_bookings_stats: заглушка (этап 1)")
        return []
