"""Тесты повторных гостей и хеширования."""

from src.metrics.guests import hash_identifier, match_returning_guest, normalize_phone


def test_hash_deterministic() -> None:
    h1 = hash_identifier("79001234567")
    h2 = hash_identifier("79001234567")
    assert h1 == h2
    assert len(h1) == 64


def test_normalize_phone() -> None:
    assert normalize_phone("+7 (900) 123-45-67") == "79001234567"


def test_match_by_phone() -> None:
    phone = "79001234567"
    history = [{"phone_hash": hash_identifier(phone), "email_hash": None, "fio_hash": None}]
    guest = {"phone": "+7 900 123-45-67"}
    assert match_returning_guest(guest, history) is not None


def test_match_by_email() -> None:
    email = "guest@example.com"
    history = [{"phone_hash": None, "email_hash": hash_identifier(email), "fio_hash": None}]
    guest = {"email": "Guest@Example.com"}
    assert match_returning_guest(guest, history) is not None


def test_match_by_fio() -> None:
    fio = "иванов иван иванович"
    history = [{"phone_hash": None, "email_hash": None, "fio_hash": hash_identifier(fio)}]
    guest = {"fio": "Иванов Иван Иванович"}
    assert match_returning_guest(guest, history) is not None


def test_no_match() -> None:
    history = [{"phone_hash": "abc", "email_hash": None, "fio_hash": None}]
    guest = {"phone": "79999999999"}
    assert match_returning_guest(guest, history) is None
