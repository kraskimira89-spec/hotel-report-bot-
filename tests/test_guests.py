"""Тесты повторных гостей и хеширования."""

from src.metrics.guests import (
    hash_guest_identifiers,
    hash_identifier,
    is_returning_guest,
    match_returning_guest,
    normalize_email,
    normalize_fio,
    normalize_phone,
)


def test_hash_deterministic() -> None:
    h1 = hash_identifier("79001234567")
    h2 = hash_identifier("79001234567")
    assert h1 == h2
    assert len(h1) == 64


def test_normalize_phone() -> None:
    assert normalize_phone("+7 (900) 123-45-67") == "79001234567"


def test_normalize_email() -> None:
    assert normalize_email("  Guest@Example.com ") == "guest@example.com"


def test_normalize_fio() -> None:
    assert normalize_fio("  Иванов   Иван  ") == "иванов иван"


def test_hash_guest_identifiers() -> None:
    ids = hash_guest_identifiers(
        phone="+7 900 123-45-67",
        email="Guest@Example.com",
        fio="Иванов Иван",
    )
    assert ids.phone_hash == hash_identifier("79001234567")
    assert ids.email_hash == hash_identifier("guest@example.com")
    assert ids.fio_hash == hash_identifier("иванов иван")


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


def test_phone_priority_over_email() -> None:
    """Телефон имеет приоритет над email."""
    phone_record = {"id": 1, "phone_hash": hash_identifier("79001111111")}
    email_record = {"id": 2, "email_hash": hash_identifier("guest@example.com")}
    history = [email_record, phone_record]
    guest = {
        "phone": "79001111111",
        "email": "guest@example.com",
    }
    assert match_returning_guest(guest, history) == phone_record


def test_no_match() -> None:
    history = [{"phone_hash": "abc", "email_hash": None, "fio_hash": None}]
    guest = {"phone": "79999999999"}
    assert match_returning_guest(guest, history) is None


def test_empty_history() -> None:
    assert match_returning_guest({"phone": "79001234567"}, []) is None
    assert is_returning_guest({"phone": "79001234567"}, []) is False


def test_is_returning_guest() -> None:
    history = [{"phone_hash": hash_identifier("79001234567")}]
    assert is_returning_guest({"phone": "79001234567"}, history) is True
    assert is_returning_guest({"phone": "79999999999"}, history) is False
