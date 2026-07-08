"""Единый механизм backoff/ретраев для сетевых вызовов."""

from __future__ import annotations

import logging
import time
from typing import Callable, Iterable, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    func: Callable[[], T],
    *,
    retries: int,
    backoff_initial: float,
    backoff_max: float,
    retry_statuses: Iterable[int] = (429, 500, 502, 503, 504),
    retry_exceptions: tuple[type[Exception], ...] = (httpx.HTTPError,),
    log_prefix: str = "HTTP",
) -> T:
    """Выполнить func с экспоненциальным backoff."""
    delay = backoff_initial
    last_exc: Exception | None = None

    for attempt in range(retries):
        try:
            result = func()
            status_code = getattr(result, "status_code", None)
            if status_code is not None:
                if status_code in retry_statuses:
                    logger.warning(
                        "%s %s, попытка %s/%s",
                        log_prefix,
                        status_code,
                        attempt + 1,
                        retries,
                    )
                    if attempt < retries - 1:
                        time.sleep(min(delay, backoff_max))
                        delay *= 2
                        continue
                raise_for_status = getattr(result, "raise_for_status", None)
                if callable(raise_for_status):
                    raise_for_status()
            return result
        except retry_exceptions as exc:
            last_exc = exc
            logger.warning(
                "%s error: %s, попытка %s/%s",
                log_prefix,
                exc,
                attempt + 1,
                retries,
            )
            if attempt < retries - 1:
                time.sleep(min(delay, backoff_max))
                delay *= 2

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Retry failed without exception")
