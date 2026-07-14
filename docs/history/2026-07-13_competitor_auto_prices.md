# 2026-07-13 — Автосбор цен конкурентов (#5)

## Что сделано
- Модуль `src/data_sources/tl_ibe.py`: `detect_tl_context`, `parse_widget_with_screenshot`, vision-fallback
- `collect_competitor_prices` собирает static + виджеты; скриншоты в `data/screenshots/competitors/`
- Еженедельная задача `job_competitor_prices` (cron пн 09:30), убрана из ежедневного snapshot
- Playwright + Chromium в Dockerfile; graceful-фолбэк без браузера
- Тесты `tests/test_tl_ibe.py` + обновление `test_competitor_prices.py`

## Связанные issues
- #5 Автосбор — этот PR
- #2 Аналитика — PR #6
- #3/#4 — код уже на main (закрытие issue вручную, если нет прав API)
