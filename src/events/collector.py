"""HTTP-сбор HTML-афиш с кэшем ETag и интервалом обновления."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from src.config import EventSourceConfig
from src.events.parsers import parse_events_from_html
from src.events.types import ParsedEvent
from src.storage.db import get_event_source_state, save_error_log, upsert_event_source_state
from src.storage.models import ErrorLogRecord

logger = logging.getLogger(__name__)


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: object) -> httpx.Response: ...


def _should_fetch(source_name: str, interval_hours: int) -> bool:
    state = get_event_source_state(source_name)
    last = state.get("last_success_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last))
    except ValueError:
        return True
    return datetime.now() - last_dt >= timedelta(hours=interval_hours)


def fetch_source_html(
    source: EventSourceConfig,
    *,
    client: HttpClient | None = None,
    interval_hours: int = 12,
    force: bool = False,
) -> tuple[str | None, str | None]:
    """Скачать HTML источника. Возвращает (html, error)."""
    if not force and not _should_fetch(source.name, interval_hours):
        logger.info("Источник %s пропущен — интервал %s ч", source.name, interval_hours)
        return None, None

    own_client: httpx.Client | None = None
    if client is None:
        own_client = httpx.Client(timeout=30.0, follow_redirects=True)
        client = own_client

    state = get_event_source_state(source.name)
    headers: dict[str, str] = {
        "User-Agent": "1apart-events-bot/1.0 (+https://1apart.ru)",
        "Accept": "text/html,application/xhtml+xml",
    }
    if state.get("etag"):
        headers["If-None-Match"] = str(state["etag"])
    if state.get("last_modified"):
        headers["If-Modified-Since"] = str(state["last_modified"])

    try:
        resp = client.get(source.url, headers=headers)
        if resp.status_code == 304:
            upsert_event_source_state(source.name, last_success_at=datetime.now())
            return None, None
        resp.raise_for_status()
        upsert_event_source_state(
            source.name,
            last_success_at=datetime.now(),
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
            last_error=None,
        )
        return resp.text, None
    except httpx.HTTPError as exc:
        msg = f"{source.name}: {exc}"
        logger.warning("Ошибка сбора событий: %s", msg)
        upsert_event_source_state(source.name, last_error=msg)
        save_error_log(
            ErrorLogRecord(
                error_date=date.today(),
                source=f"events:{source.name}",
                error_type="fetch_error",
                message=msg,
            )
        )
        return None, msg
    finally:
        if own_client:
            own_client.close()


def collect_from_source(
    source: EventSourceConfig,
    today: date,
    horizon_end: date,
    *,
    client: HttpClient | None = None,
    interval_hours: int = 12,
    force: bool = False,
    html_override: str | None = None,
) -> list[ParsedEvent]:
    """Собрать события из одного источника."""
    if not source.enabled:
        return []
    html = html_override
    if html is None:
        html, err = fetch_source_html(
            source, client=client, interval_hours=interval_hours, force=force
        )
        if err or html is None:
            return []
    return parse_events_from_html(html, source.name, source.url, today, horizon_end)


def load_fixture_html(source_name: str) -> str | None:
    path = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "events" / f"{source_name}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
