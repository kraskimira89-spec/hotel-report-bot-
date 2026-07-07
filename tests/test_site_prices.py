"""Тесты парсинга статического HTML категорий."""

from pathlib import Path

from src.data_sources.site_prices import parse_category_html

FIXTURE = Path(__file__).parent / "fixtures" / "category_page.html"


def test_parse_data_price_attribute() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    result = parse_category_html(html, "studio")
    assert result is not None
    assert result["category"] == "studio"
    assert result["price"] == 4500.0
    assert result["currency"] == "RUB"


def test_parse_missing_price() -> None:
    html = "<html><body><h1>Нет цены</h1></body></html>"
    assert parse_category_html(html, "studio") is None


def test_parse_text_price() -> None:
    html = '<div class="price-value">3 200 ₽</div>'
    result = parse_category_html(html, "comfort")
    assert result is not None
    assert result["price"] == 3200.0
