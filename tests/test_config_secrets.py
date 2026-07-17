"""Тесты проверки SECRET_KEY в production."""

from __future__ import annotations

import pytest

from src.config_secrets import (
    SecretKeyError,
    ensure_production_secret_key,
    validate_secret_key,
)


def test_validate_secret_key_accepts_strong_key() -> None:
    key = "x" * 32
    validate_secret_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "change-me",
        "change_me",
        "generate_a_random_secret_key_here",
        "short",
    ],
)
def test_validate_secret_key_rejects_weak(key: str) -> None:
    with pytest.raises(SecretKeyError):
        validate_secret_key(key)


def test_ensure_production_secret_key_skips_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.config_secrets.get_env_settings",
        lambda: type("E", (), {"web_force_https": False, "secret_key": ""})(),
    )
    ensure_production_secret_key()


def test_ensure_production_secret_key_exits_on_weak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.config_secrets.get_env_settings",
        lambda: type(
            "E",
            (),
            {"web_force_https": True, "secret_key": "change-me"},
        )(),
    )
    with pytest.raises(SystemExit) as exc:
        ensure_production_secret_key()
    assert exc.value.code == 1


def test_ensure_production_secret_key_ok_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.config_secrets.get_env_settings",
        lambda: type(
            "E",
            (),
            {
                "web_force_https": True,
                "secret_key": "a" * 43,
            },
        )(),
    )
    ensure_production_secret_key()
