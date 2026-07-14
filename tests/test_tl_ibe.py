"""Тесты TravelLine IBE / виджет-сбора (этап 6А)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from src.config import CompetitorConfig, SitePricesConfig
from src.data_sources.tl_ibe import (
    cleanup_old_screenshots,
    competitor_slug,
    detect_tl_context,
    extract_min_price_from_text,
    parse_widget_with_screenshot,
    screenshot_rel_path,
)

FIXTURES = Path(__file__).parent / "fixtures" / "competitors"


def test_detect_tl_context_set_context() -> None:
    html = (FIXTURES / "bonapart_tl.html").read_text(encoding="utf-8")
    assert detect_tl_context(html) == "TL-INT-bonapart.new"


def test_detect_tl_context_context_item_name() -> None:
    html = (FIXTURES / "central_tl.html").read_text(encoding="utf-8")
    assert detect_tl_context(html) == "TL-INT-centraltomsk"


def test_detect_tl_context_missing() -> None:
    assert detect_tl_context("<html><body>no widget</body></html>") is None


def test_extract_min_price_from_text() -> None:
    assert extract_min_price_from_text("от 4 500 ₽ / ночь, люкс 12 000 руб") == 4500.0


def test_screenshot_rel_path() -> None:
    path = screenshot_rel_path(date(2026, 7, 13), "Bon Apart (Банапарт)")
    assert path.startswith("competitors/2026-07-13/")
    assert path.endswith(".png")
    assert competitor_slug("Xander Hotel") == "xander_hotel"


def test_parse_widget_graceful_without_playwright(monkeypatch, tmp_path) -> None:
    """В CI без Chromium — не падаем."""
    competitor = CompetitorConfig(
        name="Bon Apart",
        type="direct",
        url="https://www.bon-apart.ru/",
        parser="tl_widget",
    )
    site_cfg = SitePricesConfig(
        request_delay_min_sec=0,
        request_delay_max_sec=0,
    )

    def _boom():
        raise ImportError("no playwright")

    monkeypatch.setattr(
        "src.data_sources.tl_ibe._import_sync_playwright",
        _boom,
    )
    monkeypatch.chdir(tmp_path)

    result = parse_widget_with_screenshot(
        competitor,
        site_cfg=site_cfg,
        snapshot_date=date(2026, 7, 13),
    )
    assert result.available is False
    assert result.error == "playwright_not_installed"


def test_cleanup_old_screenshots(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    old_dir = tmp_path / "data" / "screenshots" / "competitors" / "2020-01-01"
    new_dir = tmp_path / "data" / "screenshots" / "competitors" / date.today().isoformat()
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "x.png").write_bytes(b"png")
    (new_dir / "y.png").write_bytes(b"png")
    removed = cleanup_old_screenshots(retention_days=90)
    assert removed == 1
    assert not (old_dir / "x.png").exists()
    assert (new_dir / "y.png").exists()


@pytest.mark.integration
def test_widget_live_bonapart_optional() -> None:
    """Живой сбор (вручную): pytest -m integration."""
    competitor = CompetitorConfig(
        name="Bon Apart",
        type="direct",
        url="https://www.bon-apart.ru/",
        parser="tl_widget",
    )
    result = parse_widget_with_screenshot(
        competitor,
        check_in=date.today() + timedelta(days=7),
        check_out=date.today() + timedelta(days=8),
        site_cfg=SitePricesConfig(
            request_delay_min_sec=0,
            request_delay_max_sec=0,
        ),
    )
    assert result.screenshot_path is not None or result.error
