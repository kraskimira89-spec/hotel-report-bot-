# Стартовый промпт для Cursor — каркас проекта «hotel-report-bot»

> Скопируйте текст ниже (от строки `====` до конца) в чат Cursor (Agent / Composer, режим редактирования всего проекта) и запустите. Промпт создаёт готовый каркас по утверждённому ТЗ v2.2, чтобы сразу приступить к разработке.

====

Ты — старший Python-разработчик. Создай с нуля каркас проекта автономного сервиса отчётности для апарт-отеля по описанию ниже. Сгенерируй ВСЮ структуру папок, файлы-заглушки с докстрингами и TODO, конфиги, зависимости, тесты и Docker. Не пиши бизнес-логику полностью — сделай рабочий скелет, который запускается, проходит пустые тесты и готов к поэтапной реализации. Пиши комментарии и докстринги на русском.

## Контекст проекта

Сервис работает автономно на VPS и по расписанию (таймзона Europe/Moscow):
1. Ежедневно собирает загрузку, брони и цены → шлёт короткую сводку со «светофором» (🟢🟡🔴) в мессенджер Max.
2. Еженедельно формирует HTML-отчёт (Occupancy, ADR, RevPAR, ALS, каналы, повторные гости, тренды, конкуренты) → шлёт на email.
3. Даёт веб-админку (FastAPI) для просмотра истории snapshot цен, метрик и логов, с переключателем dry-run.

Объект: апарт-отель на 44 квартиры, 6 категорий. Юридически — жильё (аренда квартир). Учёт — Google Sheets + TravelLine.

## Жёсткие технические требования (соблюдать строго)

- **Python 3.11+.**
- **Google Sheets:** `gspread` + сервисный аккаунт (JSON-ключ вне репозитория).
- **Сбор цен с сайта 1apart.ru — ДВА разных источника:**
  - Базовые цены по 6 категориям = **статический HTML** страниц категорий → **`httpx` + `BeautifulSoup`**, БЕЗ браузера.
  - Цены на конкретные даты (динамические, Price Optimizer) = **брать из TravelLine API**, НЕ парсить виджет.
- **Сбор цен конкурентов (автономно, без ручного ввода):**
  - `static` — httpx + BeautifulSoup (Петровские, Гоголь, Кухтерин).
  - `tl_widget` — Playwright для TravelLine-виджетов.
  - `wubook_widget` — Playwright для WuBook.
- **TravelLine API:** REST через `httpx` — Universal WebPMS API (аналитика/платежи/доход) + Read Reservation API (брони, каналы, гости). Для «новых броней сегодня» — `dateKind=2` (по дате создания).
- **История:** **SQLite** (модуль в `src/storage/`), хранить минимум 90 дней.
- **Админка:** **FastAPI** + Jinja2, авторизация по логину/паролю (или токену).
- **Планировщик:** APScheduler внутри приложения (cron на VPS как альтернатива).
- **Уведомления:** Max Bot API (`POST /messages` на `platform-api2.max.ru`, заголовок Authorization, Markdown/HTML, лимит 4000 символов) и email через `smtplib`.
- **Деплой:** **Docker + docker-compose** (папка `docker/`), подключается на финальном этапе, но каркас создать сразу.
- **Playwright:** нужен только для виджетов конкурентов; в Docker должен устанавливаться Chromium.
- **Конфигурация:** всё вынести в `config/settings.yaml` + `.env`. Никакого хардкода токенов, порогов, chat_id, email, лимитов сбора. Секреты — только в `.env`, который в `.gitignore`.
- **Git/CI:** `.github/workflows/ci.yml` — линтер (ruff) + pytest на push/PR.

## Ключевые правила бизнес-логики (заложить как константы/структуры и TODO)

- **Формулы** (unit = квартира, unit-night = квартира×ночь):
  - Occupancy = продано unit-nights / доступно unit-nights × 100%
  - ADR = доход за проживание / продано unit-nights
  - RevPAR = доход / доступно unit-nights (или ADR × Occupancy)
  - ALS = дней пребывания / кол-во броней
  - Доход: приоритет — факт из TravelLine (`prepaidSum`/платежи); MVP-fallback — snapshot-цена × занятые unit-nights, с пометкой «оценочный».
- **Каналы:** классификация в `config` (`channels_map`), метки `direct`/`aggregator`. Прямые: сайт 1apart.ru, звонки, мессенджеры. Агрегаторы: Островок, Яндекс Путешествия, Авито, Суточно.ру и пр.
- **Повторный гость:** совпадение по телефону ИЛИ email ИЛИ ФИО (приоритет: телефон→email→ФИО). Идентификаторы хранить в хешированном виде.
- **Snapshot цен:** 1 раз/день (по умолчанию 09:00 MSK), отклонение «к вчера» — только между двумя зафиксированными snapshot.
- **Светофор:** пороги в `config.yaml` (загрузка %, отклонение цены, число новых броней).
- **Dry-run:** флаг в `config.yaml` + переключатель в админке; при `true` расчёт полный, отправка в тестовый чат/себе.
- **Анти-блок при сборе с сайта:** задержка 2–3 сек между запросами к домену, случайные паузы, реалистичный User-Agent, уважать robots.txt (у 1apart.ru закрыт только `/manager/`), обработка 403/429/503 с backoff и переходом на последний успешный snapshot. Все лимиты — в config.
- **Защита от сбоев:** при недоступности источника — последний успешный snapshot + пометка + уведомление; критический источник недоступен → отчёт не считается полным.

## Требуемая структура репозитория (создай точно так)

```
hotel-report-bot/
├── .github/workflows/ci.yml
├── config/
│   ├── settings.example.yaml    # пороги светофора, время, channels_map, dry_run, лимиты сбора, chat_id, email
│   └── .env.example             # секреты: MAX_TOKEN, GOOGLE_SA_JSON_PATH, TL_API_KEY, SMTP_*, ADMIN_PASSWORD
├── src/
│   ├── __init__.py
│   ├── config.py                # загрузка settings.yaml + .env (pydantic-settings)
│   ├── data_sources/
│   │   ├── __init__.py
│   │   ├── sheets.py            # gspread: чтение «Заселяемость» и «Брони статистика»
│   │   ├── site_prices.py       # httpx+BeautifulSoup: базовые цены категорий (статика). БЕЗ Playwright
│   │   ├── travelline.py        # httpx: Universal WebPMS API + Read Reservation API; цены на даты, доход, каналы, гости
│   │   ├── tl_ibe.py            # Playwright: сбор цен из виджетов (TravelLine/WuBook)
│   │   └── market_trends.py     # сбор новостей/трендов и цен конкурентов (для email)
│   ├── metrics/
│   │   ├── __init__.py
│   │   ├── occupancy.py         # Occupancy, статусы-светофор
│   │   ├── revenue.py           # ADR, RevPAR, ALS (факт из TL или оценка по snapshot)
│   │   └── guests.py            # классификация каналов, повторные гости (хеши)
│   ├── notifiers/
│   │   ├── __init__.py
│   │   ├── max_bot.py           # POST /messages на platform-api2.max.ru; dry-run; backoff 429/5xx
│   │   └── email_sender.py      # smtplib, HTML-письмо + текстовый дубль; dry-run
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── db.py                # инициализация SQLite, миграции
│   │   └── models.py            # таблицы: price_snapshots, metrics_daily, bookings_daily, guests, reports_log, errors_log
│   ├── web/
│   │   ├── __init__.py
│   │   ├── app.py               # FastAPI: авторизация, дашборд, история snapshot, метрики, каналы, логи, отчёты, настройки, dry-run toggle
│   │   └── templates/           # Jinja2-шаблоны (base.html, dashboard.html и т.д.)
│   ├── scheduler.py             # APScheduler: 09:00 snapshot, 09:05 Max, Пн 08:00 email (MSK); различать дату отчёта/запуска/периода
│   └── main.py                  # точка входа: запуск планировщика и/или веб-сервера
├── tests/
│   ├── __init__.py
│   ├── test_metrics.py          # проверка формул на примерах (граничные случаи, деление на 0)
│   ├── test_channels.py         # direct/aggregator по channels_map
│   ├── test_guests.py           # матчинг повторных гостей
│   └── test_site_prices.py      # парсинг статического HTML категорий (на сохранённом фикстур-HTML)
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── requirements.txt
├── .gitignore                   # .env, *.db, .venv/, __pycache__/, service_account.json
└── README.md                    # запуск, настройка, переменные окружения, этапы
```

## requirements.txt (включи как минимум)

```
gspread
google-auth
httpx
beautifulsoup4
lxml
playwright
fastapi
uvicorn
jinja2
apscheduler
pydantic-settings
python-dotenv
pyyaml
pytest
ruff
```
(Playwright нужен для виджетов конкурентов; установить Chromium в Docker.)

## Что должно работать сразу после генерации

1. `pip install -r requirements.txt` проходит без ошибок.
2. `pytest` запускается и проходит (пустые/базовые тесты зелёные).
3. `python -m src.main` стартует без падений (планировщик регистрирует задачи, задачи — заглушки с TODO и логами).
4. `uvicorn src.web.app:app` поднимает админку с страницей входа и пустым дашбордом.
5. `docker compose -f docker/docker-compose.yml up --build` собирает и запускает контейнер.
6. `config/settings.example.yaml` и `config/.env.example` содержат все ключи с комментариями; реальные файлы `.env`/`settings.yaml` в `.gitignore`.

## Порядок реализации (отрази в README как чек-лист этапов, каждый = отдельный PR)

Этап 0 среда/CI → 1 Sheets → 2 метрики+тесты → 3 snapshot цен (BeautifulSoup) + анти-блок → 4 SQLite → 5 Max Bot + dry-run → 6 email → 7 TravelLine API (цены на даты, факт-доход, каналы, гости) → 8 админка → 9 планировщик + Docker → 10 обработка ошибок → 11 тестовый прогон 1–2 недели и приёмка.

Сгенерируй все файлы каркаса сейчас. В каждом модуле оставь докстринг с назначением, сигнатуры ключевых функций и `# TODO:` по соответствующему этапу. Заглушки должны импортироваться и запускаться без ошибок.
