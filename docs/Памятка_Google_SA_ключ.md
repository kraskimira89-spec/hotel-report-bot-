# Памятка: ключ Google Sheets (service account)

Куда положить JSON-ключ сервисного аккаунта и что прописать в `.env`.  
Ключ **никогда не коммитить** — в `.gitignore` есть `service_account.json` и `config/primeval-rain-*.json`.

---

## 1. Файл ключа

1. Скачайте JSON из Google Cloud Console (сервисный аккаунт).
2. Переименуйте в **`service_account.json`**.
3. Поделитесь таблицей «Апарт отель для Сергея» с email сервисного аккаунта правами **Читатель**.

---

## 2. Куда положить

| Среда | Путь |
|-------|------|
| **VPS (рекомендуется)** | `/etc/1apart/service_account.json` |
| Локально (тест) | `hotel-report-bot/config/service_account.json` |
| Docker на VPS | файл на хосте + путь в `config/.env`; том `../config` уже смонтирован — удобнее `config/service_account.json` внутри каталога приложения |

На VPS:
```bash
sudo mkdir -p /etc/1apart
sudo scp service_account.json root@VPS:/etc/1apart/service_account.json
# или через SFTP в /etc/1apart/
sudo chmod 600 /etc/1apart/service_account.json
```

В каталоге проекта (если ключ рядом с `.env`):
```bash
# на VPS, из каталога приложения
# scp локальный файл → /opt/1apart/hotel-report-bot/config/service_account.json
chmod 600 config/service_account.json
```

---

## 3. Прописать в `.env`

Файл: **`config/.env`** (не `.env.example`). Одна строка, без дубликатов:

```env
# VPS вне репозитория
GOOGLE_SA_JSON_PATH=/etc/1apart/service_account.json

# или в volume проекта (Docker)
# GOOGLE_SA_JSON_PATH=config/service_account.json

# Windows локально
# GOOGLE_SA_JSON_PATH=C:/secrets/1apart-sheets-sa.json
```

---

## 4. Перезапуск

```bash
cd /opt/1apart/hotel-report-bot
docker compose -f docker/docker-compose.yml up -d --force-recreate
```

Локально — перезапустить процесс / контейнер, чтобы подхватить `.env`.

---

## 5. Проверка

```bash
# в контейнере или venv
python scripts/sheets_smoke_test.py
```

Успех:
- smoke test без `SheetsReadError`;
- в логах нет ошибок доступа к Google Sheets;
- на дашборде админки есть данные загрузки из листов «Заселяемость» / «Брони статистика».

Ошибка «доступ» — проверьте путь к JSON, права на файл и шаринг таблицы на email из `client_email` внутри JSON.
