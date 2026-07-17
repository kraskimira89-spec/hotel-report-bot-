"""Ручной прогон сбора входящей почты (Issue #13)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_sources.mail_inbox import collect_and_save_mail_inbox  # noqa: E402
from src.storage.db import get_mail_messages, init_db  # noqa: E402


def main() -> None:
    init_db()
    end = date.today()
    start = end - timedelta(days=7)
    n = collect_and_save_mail_inbox(start, end)
    print(f"saved={n}")
    for row in get_mail_messages(limit=10):
        print(
            f"- [{row.mail_class}] {row.mailbox} | {row.subject[:60]!r} "
            f"| reviews={row.for_reviews}"
        )


if __name__ == "__main__":
    main()
