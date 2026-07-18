"""Зарегистрировать команды бота Max (кнопка «Начать» / меню /)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import reload_config
from src.notifiers.max_api import DEFAULT_BOT_COMMANDS, build_max_api_client


def main() -> int:
    reload_config()
    client = build_max_api_client()
    if client is None:
        print("MAX_TOKEN не задан", file=sys.stderr)
        return 1
    print("Команды:", DEFAULT_BOT_COMMANDS)
    result = client.set_my_commands()
    print(result)
    me = client.get_me()
    print(f"Бот: {me.name} (@{me.username}) id={me.user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
