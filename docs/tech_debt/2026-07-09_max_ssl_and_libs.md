# 🧾 Техдолг: Max API — библиотеки и SSL (2026-07-09)

## ✅ Что установлено
- Зависимости проекта из `requirements.txt`
- Community Python-клиент: `python-max-bot` (официально в [доке Max](https://dev.max.ru/docs) — JS/TS и Go)
- SSL-хелперы: `pip-system-certs`, `truststore`
- Сертификаты Минцифры: `data/certs/*.cer` + бандл `data/certs/russian_trusted_ca_bundle.pem`
- Проверка: `GET /me` → **200** (бот `id8905998693_bot`, user_id `366484126`)

## ⚠️ Важно
- `platform-api2.max.ru` требует доверенный сертификат Минцифры ([docs-api](https://dev.max.ru/docs-api)).
- Официальный источник сертификатов: [gosuslugi.ru/crt](https://www.gosuslugi.ru/crt).
- Для httpx/Python: `verify=data/certs/russian_trusted_ca_bundle.pem` (или `SSL_CERT_FILE`).
- `chat_id` из ссылки бота не берётся — только из `bot_started` / `bot_added` через `GET /updates` или webhook.

## 🧩 Следующие шаги
1. ~~Написать боту `/start` в Max.~~
2. ~~Вызвать `GET /updates` и сохранить `chat_id`~~ — `364502022` в settings.yaml.
3. ~~Вшить CA-бандл~~ — `src/utils/ssl_certs.py` + `src/notifiers/max_api.py`.
4. Для production: `max_bot.webhook_url` + `MAX_WEBHOOK_SECRET` → `python scripts/max_subscribe_webhook.py`.
