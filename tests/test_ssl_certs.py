"""Тесты SSL CA bundle для Max API."""

from __future__ import annotations

from pathlib import Path

from src.utils.ssl_certs import build_russian_ca_bundle, get_max_api_verify


def test_build_russian_ca_bundle() -> None:
    bundle = build_russian_ca_bundle(force=True)
    assert bundle is not None
    assert bundle.is_file()
    text = bundle.read_text(encoding="utf-8")
    assert text.count("-----BEGIN CERTIFICATE-----") >= 3


def test_get_max_api_verify_returns_bundle_path() -> None:
    get_max_api_verify.cache_clear()
    verify = get_max_api_verify()
    assert isinstance(verify, str)
    assert Path(verify).is_file()
