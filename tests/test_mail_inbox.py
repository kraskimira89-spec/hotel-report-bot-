"""Тесты почты: классификация и парсер TravelLine."""

from __future__ import annotations

from src.data_sources.mail_inbox import classify_mail
from src.data_sources.mail_report_parsers import parse_travelline_report


def test_classify_service_report_by_sender() -> None:
    cls, for_rev = classify_mail(
        "noreply@travelline.ru",
        "Ежедневный отчёт",
        "Текст",
        ["@travelline.ru"],
    )
    assert cls == "service_report"
    assert for_rev is False


def test_classify_review() -> None:
    cls, for_rev = classify_mail(
        "guest@example.com",
        "Новый отзыв о проживании",
        "Гость оставил отзыв",
        [],
    )
    assert cls == "review"
    assert for_rev is True


def test_classify_inquiry() -> None:
    cls, for_rev = classify_mail(
        "a@b.ru",
        "Жалоба на заселение",
        "Прошу разобраться",
        [],
    )
    assert cls == "inquiry"
    assert for_rev is True


def test_parse_travelline_report_numbers() -> None:
    body = (
        "Отчёт TravelLine за день.\n"
        "Новые брони: 13\n"
        "Отмены: 2\n"
        "Выручка: 125 000 ₽\n"
    )
    parsed = parse_travelline_report("TravelLine daily", body)
    assert parsed is not None
    assert parsed.provider == "travelline"
    assert parsed.bookings == 13
    assert parsed.cancellations == 2
    assert parsed.amount == 125000.0
