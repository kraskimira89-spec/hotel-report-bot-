# Сверка первой сводки с TravelLine (post #18)

Дата: 2026-07-22

## Контекст

Issue **#18** закрыт 17.07.2026: сводка переведена на TravelLine (occupancy/bookings).
Сверка с отчётом «Доходность и загрузка» отложена до стабильной работы TL API — сейчас API работает.

## Скрипт

```bash
python scripts/reconcile_summary_travelline.py [--date YYYY-MM-DD]
```

Сравнивает `prepare_daily_summary_data()` с прямым запросом TravelLine:
загрузка, занято номеров, новые брони, выручка/ADR/RevPAR.

## Прогон VPS (22.07.2026)

| Дата | Загрузка | Брони | Выручка | ADR | RevPAR | Итог |
|------|----------|-------|---------|-----|--------|------|
| 2026-07-17 | 34.09% = 34.09% | 8 = 8 | 106 200 ₽ | 7 080 | 2 413.64 | **OK** |
| 2026-07-21 | 47.73% = 47.73% | 11 = 11 | 72 508 ₽ | 3 452.76 | 1 647.91 | **OK** |
| 2026-07-22 | 45.45% = 45.45% | 6 = 6 | 0 ₽* | — | — | **OK** |

\* 22.07 — выручка 0 в analytics (день ещё не закрыт / нет начислений). Загрузка и брони совпадают.

Источники сводки на всех датах: `occupancy=travelline`, `bookings=travelline`.

## Read Reservation API

`read-reservation/.../search` → **404**; брони и каналы берутся через **WebPMS fallback** — цифры сходятся.

## JSON-отчёты

`docs/presentations/build/reconcile_2026-07-17.json`  
`docs/presentations/build/reconcile_2026-07-21.json`  
`docs/presentations/build/reconcile_2026-07-22.json`

## Следующий шаг (этап 11)

1. Вручную сверить **21.07** с UI TravelLine «Доходность и загрузка» (скрин/цифры заказчика).
2. **Ежедневный reconcile** в планировщике: `summary_reconcile_cron: 12 9 * * *` (09:12 MSK после сводки).
   JSON: `data/reconcile/reconcile_YYYY-MM-DD.json`, retention 90 дней.
3. Dry-run 1–2 недели (`dry_run=true`), затем → `dry_run=false`.

## Планировщик

- Job: `summary_travelline_reconcile` (`job_summary_travelline_reconcile`)
- Cron: `12 9 * * *` (Europe/Moscow)
- CLI: `python scripts/reconcile_summary_travelline.py`
- Пайплайн: `python scripts/run_daily_pipeline.py --all` (шаг 4/4)

## Деплой 22.07.2026

- VPS `91.229.11.147`, контейнер `docker-app-1`
- `dry_run=true`, `summary_reconcile_cron: 12 9 * * *`
- Ручной прогон 22.07: **OK** (загрузка 45.45%, брони 6, выручка 0)
- JSON: `data/reconcile/reconcile_2026-07-22.json` в контейнере
