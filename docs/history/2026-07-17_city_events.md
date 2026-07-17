# Модуль «События Томска»

Дата: 2026-07-17

## Сделано

- SCHEMA v11: `city_events`, `event_sources`, `event_review_log`, `event_source_state`
- SCHEMA **v12**: overnight / online / attendance / location_confirmed (см. `2026-07-17_my_business_mass_events.md`)
- Пакет `src/events/`: parsers, collector, normalize, impact, service
- Конфиг `events:` в settings.example.yaml (Kassy, Ticketland, филармония, ТУСУР,
  Мой бизнес, спорт, библиотеки, регион, РИА verification_only)
- Админка `/events`: календарь, фильтры, approve/reject, ручное создание
- Прогноз: `city_events_boost` × overnight, маркеры, онлайн/вне Томска исключены
- Scheduler: `job_events_pipeline` в 06:00 MSK
- Тесты: `tests/test_events.py`, фикстуры HTML
- Скрипт: `scripts/run_events.py`

## Ограничения этапа 1

- Калибровка коэффициентов по факту — не реализована (флаг `events_calibrated=false`)
- Playwright не используется; только httpx + BeautifulSoup
- Ticketland: 403 antibot — не обходим
- Региональный календарь gosuslugi — JS-тяжёлый, best-effort парсер
- При сбое источника пайплайн продолжает работу, ошибка в `errors_log`

## Деплой

1. `python scripts/patch_events_settings.py` на VPS
2. `docker compose up -d --build` (или `docker cp` ключевых модулей)
3. `docker exec docker-app-1 python -m scripts.run_events`
