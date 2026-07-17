"""Тесты русских подписей категорий."""

from __future__ import annotations

from src.utils.category_labels import (
    category_label,
    category_short_label,
    room_type_label,
)


def test_category_label_known_slugs() -> None:
    assert "Однокомнатные" in category_label("1room23")
    assert "Однокомнатные" in category_label("/1room")
    assert "Двухкомнатн" in category_label("dvuxkomnatnyie-kvartiryi-3")
    assert "люкс" in category_label("80m2-apartamentyi").lower()


def test_category_label_no_raw_english() -> None:
    label = category_label("1room23")
    assert "1room" not in label.lower()
    assert "room" not in label.lower()


def test_room_type_label_luxe() -> None:
    assert room_type_label("Luxe") == "Люкс"
    assert room_type_label("1-комн. 23 кв.м.") == "1-комн. 23 кв.м."


def test_category_short_label_max() -> None:
    assert category_short_label("Двухкомнатная квартира (2 кровати)") == "2-КК (2кр)"
    assert category_short_label("Двухкомнатная квартира (3 кровати)") == "2-КК (3кр)"
    assert category_short_label("Однокомнатные квартиры 23 м²") == "1-КК 23"
    assert category_short_label("Однокомнатные квартиры 27 м²") == "1-КК 27"
    assert category_short_label("Улучшенные однокомнатные квартиры") == "1-КК ул."
    assert category_short_label("Однокомнатные квартиры с диванчиком") == "1-КК диван"
    assert category_short_label("Двухкомнатные квартиры люкс") == "2-КК люкс"
    assert category_short_label("1room23") == "1-КК 23"
    assert category_short_label("Итого") == "Итого"
    assert category_short_label("Люкс") == "Люкс"
