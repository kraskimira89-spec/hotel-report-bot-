"""Клиент TravelLine API: WebPMS + Read Reservation."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from src.config import AppConfig, get_config, get_env_settings

logger = logging.getLogger(__name__)


class TravelLineClient:
    """REST-клиент TravelLine (Universal WebPMS + Read Reservation API)."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self._env = get_env_settings()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._env.tl_api_key}",
            "Content-Type": "application/json",
        }

    async def get_reservations(
        self,
        start_date: date,
        end_date: date,
        date_kind: int = 2,
    ) -> list[dict[str, Any]]:
        """Получить брони. date_kind=2 — по дате создания (новые брони сегодня).

        # TODO: этап 7 — реальный endpoint Read Reservation API.
        """
        logger.info(
            "get_reservations: заглушка %s..%s date_kind=%s (этап 7)",
            start_date,
            end_date,
            date_kind,
        )
        return []

    async def get_dynamic_prices(
        self,
        check_in: date,
        check_out: date,
        category_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Цены на конкретные даты (Price Optimizer) — только из API.

        # TODO: этап 7 — НЕ парсить виджет, только TravelLine API.
        """
        logger.info(
            "get_dynamic_prices: заглушка %s..%s (этап 7)",
            check_in,
            check_out,
        )
        return []

    async def get_revenue(
        self,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Фактический доход (prepaidSum / платежи) из WebPMS API.

        # TODO: этап 7 — приоритетный источник для ADR/RevPAR.
        """
        logger.info("get_revenue: заглушка %s..%s (этап 7)", start_date, end_date)
        return {"revenue": 0.0, "is_estimated": True}

    async def get_channels(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Статистика по каналам бронирования.

        # TODO: этап 7 — каналы из Reservation API.
        """
        logger.info("get_channels: заглушка %s..%s (этап 7)", start_date, end_date)
        return []

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Базовый HTTP-запрос к TravelLine."""
        async with httpx.AsyncClient(headers=self._headers(), timeout=30.0) as client:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
