# Центр рекомендаций

Дата: 2026-07-18

## Что сделано

- SCHEMA 15: таблица `recommendations`
- Пакет `src/recommendations/` — шаблоны, render, sync price/system/trends
- UI `/recommendations` + карточка + Word
- Редирект `/forecast/recommendation/{id}` → универсальная карточка
- Промпт `03_recommendations.md`: внешние тренды только из БД, пилот для Томска
- Виджет на дашборде и пункт меню

## Тесты

`tests/test_recommendations_center.py` + обновление `test_recommendation_card.py`
