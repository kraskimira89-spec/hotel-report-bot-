"""Отправить письмо с доступом к админке (одноразово)."""

from __future__ import annotations

import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import get_config, get_env_settings  # noqa: E402

TO = "pisanko@1apart.ru"
SUBJECT = "Доступ к панели отчётности 1apart"
LETTER = ROOT / "docs" / "letters" / "2026-07-18_dostup_ekaterina.html"

TEXT_PLAIN = """Екатерина, добрый день!

Открываем доступ к веб-панели апарт-отеля 1apart.

Вход: https://bot.masterklepa.online/login
Логин: admin
Пароль: 1234567890

Разделы:
- Аналитика: https://bot.masterklepa.online/analytics
- Рекомендации: https://bot.masterklepa.online/recommendations
- Прогноз: https://bot.masterklepa.online/forecast
- События: https://bot.masterklepa.online/events
- Конкуренты: https://bot.masterklepa.online/competitors
- Цены: https://bot.masterklepa.online/snapshots

Ежедневные сводки также приходят в мессенджер Max.

С уважением,
команда 1apart
"""


def main() -> None:
    cfg = get_config()
    env = get_env_settings()
    html_body = LETTER.read_text(encoding="utf-8")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = SUBJECT
    msg["From"] = cfg.email.from_address
    msg["To"] = TO
    msg.attach(MIMEText(TEXT_PLAIN, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    use_ssl = bool(env.smtp_use_ssl) or int(env.smtp_port) == 465
    if use_ssl:
        with smtplib.SMTP_SSL(env.smtp_host, env.smtp_port) as server:
            server.login(env.smtp_user, env.smtp_password)
            server.sendmail(cfg.email.from_address, [TO], msg.as_string())
    else:
        with smtplib.SMTP(env.smtp_host, env.smtp_port) as server:
            if env.smtp_use_tls:
                server.starttls()
            server.login(env.smtp_user, env.smtp_password)
            server.sendmail(cfg.email.from_address, [TO], msg.as_string())

    print(f"OK: письмо отправлено на {TO}")


if __name__ == "__main__":
    main()
