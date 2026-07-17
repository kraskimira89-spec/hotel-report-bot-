"""Проверка секретов перед запуском в production."""

from __future__ import annotations

import sys

from src.config import get_env_settings

MIN_SECRET_KEY_BYTES = 32

_FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "",
        "change-me",
        "change_me",
        "change-me-in-production",
        "change_me_in_production",
        "generate_a_random_secret_key_here",
        "your-secret-key",
        "secret",
        "dev",
        "test",
        "admin",
    }
)


class SecretKeyError(RuntimeError):
    """Небезопасный SECRET_KEY для production."""


def is_production_env() -> bool:
    """Production: HTTPS принудительно (VPS / публичный деплой)."""
    return bool(get_env_settings().web_force_https)


def validate_secret_key(secret_key: str) -> None:
    """Проверить SECRET_KEY; при ошибке — SecretKeyError."""
    normalized = secret_key.strip().lower().replace("_", "-")
    forbidden = {k.replace("_", "-") for k in _FORBIDDEN_SECRET_KEYS}
    if not secret_key.strip():
        raise SecretKeyError("SECRET_KEY не задан")
    if normalized in forbidden:
        raise SecretKeyError("SECRET_KEY совпадает с небезопасным шаблоном")
    if len(secret_key.encode("utf-8")) < MIN_SECRET_KEY_BYTES:
        raise SecretKeyError(
            f"SECRET_KEY короче {MIN_SECRET_KEY_BYTES} байт "
            f"(сейчас {len(secret_key.encode('utf-8'))})"
        )


def ensure_production_secret_key() -> None:
    """В production завершить процесс при небезопасном SECRET_KEY."""
    if not is_production_env():
        return
    env = get_env_settings()
    try:
        validate_secret_key(env.secret_key)
    except SecretKeyError as exc:
        print(
            f"ОШИБКА: {exc}. Задайте уникальный SECRET_KEY в config/.env "
            f'(python -c "import secrets; print(secrets.token_urlsafe(32))") '
            "и перезапустите сервис.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
