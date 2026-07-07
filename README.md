# hotel-report-bot

Автономный сервис отчётности для апарт-отеля (44 квартиры, 6 категорий).

## Возможности

- **Ежедневно:** сбор загрузки, броней и цен → сводка со светофором (🟢🟡🔴) в мессенджер Max
- **Еженедельно:** HTML-отчёт (Occupancy, ADR, RevPAR, ALS, каналы, повторные гости) → email
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

## Этапы реализации (каждый = отдельный PR)

- [ ] **Этап 0** — среда, CI, каркас
- [ ] **Этап 1** — Google Sheets (`gspread`)
- [ ] **Этап 2** — метрики + тесты формул
- [ ] **Этап 3** — snapshot цен (BeautifulSoup) + анти-блок
- [ ] **Этап 4** — SQLite, миграции, retention 90 дней
- [ ] **Этап 5** — Max Bot + dry-run
- [ ] **Этап 6** — email-отчёт (HTML)
- [ ] **Этап 7** — TravelLine API (цены, доход, каналы, гости)
- [ ] **Этап 8** — веб-админка (полный функционал)
- [ ] **Этап 9** — планировщик + Docker
- [ ] **Этап 10** — обработка ошибок, fallback на snapshot
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
├── scheduler.py        # APScheduler (MSK)
└── main.py             # точка входа
```

## Лицензия

Проприетарный проект апарт-отеля 1apart.ru.
