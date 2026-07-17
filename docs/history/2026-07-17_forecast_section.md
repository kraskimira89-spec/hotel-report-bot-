# Раздел «Прогноз» (/forecast)

**Дата:** 2026-07-17

## Сделано

- SQLite SCHEMA v8: `forecast_runs`, `forecast_daily`, `price_recommendations`
- `retention_days: 730` в `settings.example.yaml`; cleanup для `competitor_prices` и прогнозов
- Пакет `src/forecast/`: детерминированная модель, рекомендации, quality (MAE/MAPE), service
- Страница `/forecast`: KPI, график с диапазоном, факторы, таблица рекомендаций, Принять/Отклонить/Отложить
- Job `forecast_refresh` (cron `30 9 * * *`), скрипт `scripts/run_forecast.py`
- Тесты: `tests/test_forecast.py`, расширен `test_web_app.py`

## Ограничения этапа 1

- Цены в TravelLine не записываются — только рекомендации
- Загрузка по типам квартир наследует объектный прогноз; per-category метрик в БД пока нет
- Праздники/события — заготовка в `forecast.manual_events` (логика коэффициентов — следующий этап)

## Деплой

```bash
python scripts/run_forecast.py
# или дождаться job forecast_refresh после daily pipeline
```

На VPS обновить `config/settings.yaml`: `storage.retention_days: 730`, секция `forecast`.
