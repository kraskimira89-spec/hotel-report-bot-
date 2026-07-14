# 2026-07-14 — Загрузка Max ↔ TravelLine + русские категории

## Проблема
В ежедневной сводке Max загрузка была 🔴 0%, статусы не совпадали с TravelLine —
брались пустые дни из Google Sheets («Заселяемость»).

## Исправление
- Приоритет загрузки: живой TravelLine (`analytics/services`, dateKind=1) → фолбэк Sheets
- Русские названия категорий вместо slug (`1room` → «Однокомнатные квартиры…»)
- `category_slug_map` / `room_type_aliases` в settings

## Файлы
- `src/data_sources/travelline.py` — `get_stay_occupancy`
- `src/notifiers/max_bot.py` — приоритет TL + русские подписи цен
- `src/utils/category_labels.py`
