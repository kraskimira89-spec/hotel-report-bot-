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

## UI списка (тот же день)

- Word убран из строк таблицы; Word + Excel — сверху и снизу списка
- В карточке остаётся подробный Word конкретной рекомендации
- Кнопки действий цветом: Подробнее (синий), Принять (зелёный), Отложить (янтарный), Отклонить (красный)

## Устранение дублей в карточке (тот же день)

- `render.dedupe_texts`: шаблон + `success_criteria_json` / `rollback_plan` без повторов
- билдеры больше не копируют критерии/откат из шаблона в JSON
- `trend_pilot`: в «Что происходит» только контекст (без пилота/метрик/условия)
- промпты `00_system_base` и `03_recommendations`: запрет дублировать выводы

## Тесты

`pytest tests/test_recommendations_center.py`

## Деплой

VPS `91.229.11.147`, container `docker-app-1` (scp + docker cp + restart)
