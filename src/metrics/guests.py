"""Классификация каналов и повторные гости."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel

from src.config import ChannelsMap


class GuestIdentifiers(BaseModel):
    """Хеши идентификаторов гостя (для хранения без PII)."""

    phone_hash: str | None = None
    email_hash: str | None = None
    fio_hash: str | None = None


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


def hash_guest_identifiers(
    phone: str | None = None,
    email: str | None = None,
    fio: str | None = None,
) -> GuestIdentifiers:
    """Построить хеши идентификаторов гостя."""
    return GuestIdentifiers(
        phone_hash=hash_identifier(normalize_phone(phone)) if phone else None,
        email_hash=hash_identifier(normalize_email(email)) if email else None,
        fio_hash=hash_identifier(normalize_fio(fio)) if fio else None,
    )


def classify_channel(channel_name: str, channels_map: ChannelsMap) -> str:
    """Классифицировать канал: direct / aggregator / unknown."""
    if not channel_name or not channel_name.strip():
        return "unknown"

    name_lower = channel_name.strip().lower()
    for ch in channels_map.direct:
        ch_lower = ch.lower()
        if ch_lower in name_lower or name_lower in ch_lower:
            return "direct"
    for ch in channels_map.aggregator:
        ch_lower = ch.lower()
        if ch_lower in name_lower or name_lower in ch_lower:
            return "aggregator"
    return "unknown"


def classify_channels(
    channel_names: list[str],
    channels_map: ChannelsMap,
) -> dict[str, str]:
    """Классифицировать список каналов: имя → direct/aggregator/unknown."""
    return {name: classify_channel(name, channels_map) for name in channel_names}


def match_returning_guest(
    guest: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Найти повторного гостя по телефону → email → ФИО.

    guest: {phone?, email?, fio?}
    history: список записей с phone_hash, email_hash, fio_hash
    """
    if not history:
        return None

    phone = guest.get("phone")
    if phone:
        ph = hash_identifier(normalize_phone(str(phone)))
        for record in history:
            if record.get("phone_hash") == ph:
                return record

    email = guest.get("email")
    if email:
        eh = hash_identifier(normalize_email(str(email)))
        for record in history:
            if record.get("email_hash") == eh:
                return record

    fio = guest.get("fio")
    if fio:
        fh = hash_identifier(normalize_fio(str(fio)))
        for record in history:
            if record.get("fio_hash") == fh:
                return record

    return None


def is_returning_guest(
    guest: dict[str, Any],
    history: list[dict[str, Any]],
) -> bool:
    """Проверить, является ли гость повторным."""
    return match_returning_guest(guest, history) is not None
