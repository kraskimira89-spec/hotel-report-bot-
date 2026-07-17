"""Типы данных модуля событий."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class ParsedEvent:
    """Событие, извлечённое из источника."""

    title: str
    start_at: date
    end_at: date | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    source_url: str = ""
    source_name: str = ""
    source_priority: int = 3
    category: str = "other"
    description: str | None = None
    estimated_capacity: int | None = None
    audience_scope: str = "unknown"
    source_event_id: str | None = None
    raw_date: str | None = None
