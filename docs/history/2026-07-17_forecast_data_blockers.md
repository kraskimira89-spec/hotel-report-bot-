# Доработка прогноза: история, блокеры, пробелы

**Дата:** 17.07.2026

## Блокер данных

- `retention_days` default **730** (`StorageConfig`, `settings.example.yaml`)
- `scripts/patch_forecast_settings.py` — дописать `forecast` + retention в рабочий `settings.yaml`
- `src/forecast/metrics_history.py` — сбор `metrics_daily` из TravelLine (объект + категории)
- `scripts/backfill_metrics_from_tl.py` — backfill за N дней
- Job `metrics_daily` (09:25) перед `forecast_refresh` (09:30)

## Точность

- `manual_events` подключены в `engine.forecast_day`
- Прогноз по категориям: `metric_type=category:{slug}` из TL backfill

## Технические пробелы

- SCHEMA v9: `price_recommendations.horizon_days`
- `forecast_id` связывается при сохранении рекомендаций
- Фильтр рекомендаций по горизонту в `/forecast`
- UI: предупреждение если история < 365 дн.

## VPS

```bash
python scripts/patch_forecast_settings.py
python scripts/backfill_metrics_from_tl.py --days 365
python scripts/run_forecast.py
```
