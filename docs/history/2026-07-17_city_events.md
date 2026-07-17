# Модуль «События Томска»

Дата: 2026-07-17

## Сделано

- SCHEMA v11: `city_events`, `event_sources`, `event_review_log`, `event_source_state`
- Пакет `src/events/`: parsers, collector, normalize, impact, service
- Конфиг `events:` в settings.example.yaml (Kassy, Ticketland, филармония, ТУСУР)
- Админка `/events`: календарь, фильтры, approve/reject, ручное создание
- Прогноз: `city_events_boost`, маркеры на графике, блок «Факторы — события»
- Рекомендации по ценам с учётом подтверждённых событий (impact ≥ 60)
- Scheduler: `job_events_pipeline` в 06:00 MSK
- Тесты: `tests/test_events.py`, фикстуры HTML
- Скрипт: `scripts/run_events.py`

## Ограничения этапа 1

- Калибровка коэффициентов по факту — не реализована (флаг `events_calibrated=false`)
- Playwright не используется; только httpx + BeautifulSoup
- При сбое источника пайплайн продолжает работу, ошибка в `errors_log`

## Деплой

1. Добавить секцию `events:` в `config/settings.yaml` на VPS
2. `docker compose up -d --build`
3. `docker exec docker-app-1 python -m scripts.run_events`
