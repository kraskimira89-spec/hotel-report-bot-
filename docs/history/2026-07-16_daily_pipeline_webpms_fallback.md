# 16.07.2026 — dry-run пайплайна и фолбэк WebPMS

## Проблема
`run_daily_pipeline.py --all` падал на `[2/3]` из‑за `404` Read Reservation API (`property_id=8134`), хотя WebPMS (`TL_API_KEY`) работает.

## Исправление
В `get_reservations(date_kind=2)` при OAuth и ошибке с `404` — фолбэк на `_get_reservations_via_webpms`.

## Прогон на VPS (16.07.2026 MSK)
- Сверка: TL=13, Sheets=0 → предупреждение (порог 10%)
- Сводка: `status: sent`, `dry_run: True`, `occupancy: 0.0`, `bookings: 0`
- В Max не уходило (dry_run)

## Заметка
Цифры сводки берутся из Sheets/локальных данных; за сегодня Sheets по броням = 0, загрузка в сводке 0%.
