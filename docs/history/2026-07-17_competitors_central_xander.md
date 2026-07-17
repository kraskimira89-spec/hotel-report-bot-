# Конкуренты: Центральный и Xander — catalog fallback

**Дата:** 2026-07-17

## Сделано

- SCHEMA v10: `price_kind`, `booking_engine`, `check_in/out`, `captured_at`, `raw_url`, `error_message`
- Парсеры `parse_central_catalog`, `parse_xander_catalog` + fallback после сбоя виджета
- `collect_and_save`: dynamic > public_from > cached; не подменять dynamic публичной ценой
- UI: карточки «Центральный» / Xander на `/competitors`
- VPS: `patch_competitor_catalog.py`, probe catalog — **4400 ₽** / **7600 ₽** (public_from)

## VPS прогноз

- `patch_forecast_settings.py` — retention 730, секция forecast
- `backfill_metrics_from_tl --days 365` — **в процессе** (~2 мин/день)
- `run_forecast.py` — первый прогон при history=6, quality=poor; повторить после backfill

## Следующий шаг

1. Дождаться завершения backfill → `run_forecast.py` снова
2. `docker restart docker-app-1` — подхватить UI (после backfill)
3. Playwright-сценарии TL/WuBook по датам (+3/+7/+14) — отдельная задача
