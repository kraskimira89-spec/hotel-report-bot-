# Почему в /forecast цены «текущая = рекомендованная» и «данных недостаточно»

Дата: 2026-07-18

## Причина

В `build_price_recommendation` при `confidence=low` и `history_days < 30`
ставится `manual_review` и `rec_min = rec_max = current_price`
(текст: «Данных недостаточно — не менять автоматически»).

На VPS (до доработки):
- `metrics_daily` тип `daily` — **366** дней (качество run = good)
- по категориям `category:*` — только **~23** дня
- прогноз по категории брал короткую историю → `history_days≈11`, `confidence=low`

## Баг backfill

После `--fast` дни с уже существующим `daily` **пропускались** целиком —
категории не добирались без `--force`.

## Исправление

1. `forecast_horizon`: fallback на историю объекта при короткой категории.
2. `collect_metrics_for_date(..., fill_categories=True)`: если есть `daily`,
   но `category:*` нет / меньше ожидаемых slug — дописать только категории.
3. CLI: `python scripts/backfill_metrics_from_tl.py --days 365`
   (`--fill-categories` по умолчанию; `--no-fill-categories` / `--fast` отключают).
4. После успешного collect — `resolve_errors_log(travelline/http_error)` за дату.

## Что включить / добрать

1. TravelLine API (ключ / property_id) — закрывать `http_error` в `errors_log`.
2. Job `metrics_daily` — уже без fast, пишет категории.
3. Backfill категорий 365 дн. (без `--fast`).
4. `price_snapshot` и `competitor_prices` — для цен и market_gap.
5. После backfill — `python scripts/run_forecast.py`.

Порог для категорий: ≥ `max(30, min_history_days/4)` ≈ **91** день при `min_history_days=365`.

## TravelLine http_error (разбор 2026-07-18)

Открыто ~71. Типы:
- `404` на `read-reservation/.../reservations/search` (часто)
- редко `401 Invalid api key` на analytics
- `302` на неверные пути WebPMS dictionary (пробы URL)

Рабочий путь occupancy (`analytics/services` + `rooms` + `bookings`) на backfill отвечает **200**.
После успешного дня collect помечает `travelline/http_error` за эту дату как resolved.

## Статус VPS (2026-07-18)

- Backfill категорий запущен в фоне: `/var/log/1apart/backfill_categories_365.log`
- Порог готовности (≥91 дн. на slug) **достигнут** (~98 дн. в процессе добора)
- Промежуточный `run_forecast_refresh` выполнен: есть `decrease` с разными ценами
- Полный прогон до 365 дн. + финальный forecast — в том же фоне (`run_after_backfill.sh`)

Критерий: по каждой `category:{slug}` ≥ 91 день; у `decrease`/`increase` текущая ≠ рекомендованная.
