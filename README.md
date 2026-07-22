# hotel-report-bot

Автономный сервис отчётности для апарт-отеля (44 квартиры, 6 категорий).

## Возможности

- **Ежедневно:** сбор загрузки, броней и цен → сводка со светофором (🟢🟡🔴) в мессенджер Max
- **Еженедельно:** HTML-отчёт v2 (9 блоков: KPI, прогноз 14д, рекомендации, тренды отрасли, LLM-резюме) → email, пн 08:00 Tomsk
- **Веб-админка:** история snapshot цен, метрик, логов; переключатель dry-run

## Быстрый старт

```bash
cd hotel-report-bot
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

cp config/settings.example.yaml config/settings.yaml
cp config/.env.example config/.env
# Отредактируйте config/.env и config/settings.yaml
```

## Запуск

```bash
# Тесты
pytest

# Планировщик + веб-сервер
python -m src.main --all

# Только планировщик
python -m src.main --scheduler

# Только веб-админка
uvicorn src.web.app:app --host 0.0.0.0 --port 8000

# Docker
docker compose -f docker/docker-compose.yml up --build
```

## Переменные окружения

См. [`config/.env.example`](config/.env.example). Секреты только в `.env`, пороги и расписание — в `settings.yaml`.

Ключевые переменные:
- `MAX_TOKEN` — токен Max Bot
- `GOOGLE_SA_JSON_PATH` — путь к сервисному аккаунту Google Sheets
- `TL_API_KEY` или `TL_CLIENT_ID`/`TL_CLIENT_SECRET` — TravelLine API
- `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD`
- `ADMIN_PASSWORD` или `ADMIN_TOKEN` — доступ в админку
- `SECRET_KEY` — сессии FastAPI
- `WEB_FORCE_HTTPS` — редирект на HTTPS за reverse proxy

## Чек-лист приёмки (этап 11)

1. **Dry-run 1–2 недели**: `dry_run=true`, сводки → тестовый чат/почта.
2. **Сверка цифр**: Occupancy/ADR/RevPAR/каналы vs отчёт TravelLine «Доходность и загрузка».
   ```bash
   python scripts/reconcile_summary_travelline.py --date YYYY-MM-DD
   ```
   JSON: `data/reconcile/reconcile_YYYY-MM-DD.json` (авто 09:12 MSK, cron `summary_reconcile_cron`).
3. **Пороги светофора**: скорректировать `traffic_light.*` по факту.
4. **Сценарии отказа**:
   - расхождение источников → предупреждение и запись в `errors_log`;
   - недоступность Sheets → отчёт не считается полным, отправляется инцидент;
   - повторная отправка из админки;
   - переключение dry-run без рестарта.
5. **Финальные проверки**:
   - `ruff check src tests`
   - `pytest -q`
6. **Переход в бой**: после подтверждения заказчика → `dry_run=false`.

## Этапы реализации (каждый = отдельный PR)

- [x] **Этап 0** — среда, CI, каркас
- [x] **Этап 1** — Google Sheets (`gspread`)
- [x] **Этап 2** — метрики + тесты формул
- [x] **Этап 3** — snapshot цен (BeautifulSoup) + анти-блок
- [x] **Этап 4** — SQLite, миграции, retention 90 дней
- [x] **Этап 5** — Max Bot + dry-run
- [x] **Этап 6** — email-отчёт v2 (HTML 640px, 9 блоков, preview/test-send, trend moderation)
- [x] **Этап 7** — TravelLine API (цены, доход, каналы, гости)
- [x] **Этап 8** — веб-админка (полный функционал)
- [x] **Этап 9** — планировщик + Docker
- [x] **Этап 10** — обработка ошибок, fallback на snapshot
- [ ] **Этап 11** — тестовый прогон 1–2 недели, приёмка

## Структура

```
src/
├── config.py           # загрузка settings.yaml + .env
├── data_sources/       # Sheets, сайт, TravelLine, тренды
├── metrics/            # Occupancy, ADR, RevPAR, ALS, гости
├── notifiers/          # Max Bot, email
├── storage/            # SQLite
├── web/                # FastAPI + Jinja2
├── scheduler.py        # APScheduler (Europe/Tomsk)
└── main.py             # точка входа
```

## Лицензия

Проприетарный проект апарт-отеля 1apart.ru.
