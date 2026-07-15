# История: Google Sheets в контексте аналитики

Дата: 2026-07-15

## Сделано
- `GoogleSheetsClient.read_occupancy_range` / `read_bookings_records_range`
- `_collect_context` подмешивает Sheets (приоритет для загрузки и каналов)
- Карточки LLM опираются на живые цифры таблицы
- VPS refresh: загрузка **56,1%**, прямые **78,9%** из Sheets

## Проверка
- `tests/test_analytics_sheets.py` — passed
- Открыть `/analytics` → Обновить: цифры из Google, не «unavailable»
