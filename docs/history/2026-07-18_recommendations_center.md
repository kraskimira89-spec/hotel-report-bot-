# Центр рекомендаций

Дата: 2026-07-18

## Что сделано

- SCHEMA 15: таблица `recommendations`
- Пакет `src/recommendations/` — шаблоны, render, sync price/system/trends
- UI `/recommendations` + карточка + Word
- Редирект `/forecast/recommendation/{id}` → универсальная карточка
- Промпт `03_recommendations.md`: внешние тренды только из БД, пилот для Томска
- Виджет на дашборде и пункт меню

## Доработка external_trends (тот же день)

- LLM slim-context всегда получает `external_trends` (в т.ч. `[]`)
- В user-prompt явный запрет выдумывать практики при пустом списке
- Rule-based карточка `market_trends` — формат гипотезы/пилота, не «внедрите как в Москве»
- `_row_to_trend`: дата из `created_at`, если нет `published_at`
- Тесты: payload из БД, `trend_pilot`, секция промпта про Томск

## Тесты

`pytest tests/test_recommendations_center.py` — 12 passed

## Деплой

VPS `91.229.11.147`, container `docker-app-1` (scp + docker cp + restart)
