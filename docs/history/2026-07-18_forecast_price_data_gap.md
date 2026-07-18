# Почему в /forecast цены «текущая = рекомендованная» и «данных недостаточно»

Дата: 2026-07-18

## Причина

В `build_price_recommendation` при `confidence=low` и `history_days < 30`
ставится `manual_review` и `rec_min = rec_max = current_price`
(текст: «Данных недостаточно — не менять автоматически»).

На VPS:
- `metrics_daily` тип `daily` — **366** дней (качество run = good)
- по категориям `category:*` — только **~23** дня
- прогноз по категории брал короткую историю → `history_days≈11`, `confidence=low`
- все **2826** price_recommendations — `manual_review` / `low`

## Что включить / добрать

1. **TravelLine** — закрыть `http_error` в `errors_log` (на момент проверки ~63 открытых).
2. **Job `metrics_daily`** (ежедневно) — без `--fast`, чтобы писались категории.
3. **Backfill категорий** (один раз):
   `python scripts/backfill_metrics_from_tl.py --days 365`
   (не `--fast` — иначе снова только `daily`).
4. **Цены свои** — `price_snapshot` (уже есть текущие цены в рекомендациях).
5. **Конкуренты** — `competitor_prices` (для market_gap и increase/decrease).
6. **События** — `events` pipeline (опционально усиливает рекомендации).

Порог для категорий: ≥ `max(30, min_history_days/4)` ≈ **91** день при `min_history_days=365`.

## Исправление в коде

`forecast_horizon`: если по категории мало дней — fallback на историю объекта
с пометкой в `factors.notes`, чтобы рекомендации не блокировались.

После деплоя: `python scripts/run_forecast.py` (или кнопка «Пересчитать» на `/forecast`).
