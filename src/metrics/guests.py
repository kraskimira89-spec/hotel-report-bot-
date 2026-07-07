"""Классификация каналов и повторные гости."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from src.config import ChannelsMap


def normalize_phone(phone: str) -> str:
    """Нормализовать телефон: только цифры."""
    return re.sub(r"\D", "", phone)


def normalize_email(email: str) -> str:
    """Нормализовать email."""
    return email.strip().lower()


def normalize_fio(fio: str) -> str:
    """Нормализовать ФИО."""
    return re.sub(r"\s+", " ", fio.strip().lower())


def hash_identifier(value: str) -> str:
    """Хешировать идентификатор гостя (SHA-256)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def classify_channel(channel_name: str, channels_map: ChannelsMap) -> str:
    """Классифицировать канал: direct / aggregator / unknown."""
    name_lower = channel_name.strip().lower()
    for ch in channels_map.direct:
        if ch.lower() in name_lower or name_lower in ch.lower():
            return "direct"
    for ch in channels_map.aggregator:
        if ch.lower() in name_lower or name_lower in ch.lower():
            return "aggregator"
    return "unknown"


def match_returning_guest(
    guest: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Найти повторного гостя по телефону → email → ФИО.

    guest: {phone?, email?, fio?}
    history: список записей с phone_hash, email_hash, fio_hash
    """
    phone = guest.get("phone")
    if phone:
        ph = hash_identifier(normalize_phone(phone))
        for record in history:
            if record.get("phone_hash") == ph:
                return record

    email = guest.get("email")
    if email:
        eh = hash_identifier(normalize_email(email))
        for record in history:
            if record.get("email_hash") == eh:
                return record

    fio = guest.get("fio")
    if fio:
        fh = hash_identifier(normalize_fio(fio))
        for record in history:
            if record.get("fio_hash") == fh:
                return record

    return None
