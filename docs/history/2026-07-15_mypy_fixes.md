# 2026-07-15 — Исправление 30 ошибок mypy

## Контекст

После подключения mypy первый прогон по `src` дал 30 замечаний. Это не баги runtime, а типы: `Optional`, reuse переменных, Protocol vs `httpx.Client`, `Any` от `.json()`.

## Что сделано

- `storage/db.py` — `lastrowid or 0` (sqlite может вернуть `None`)
- `tl_ibe.py` — проверка `browser is None` перед `.new_context`
- `sheets.py` — `unit_type_col` вместо повторного `type_col: int`
- `site_prices.py` — безопасный разбор attrs BeautifulSoup; `cast(HttpClient, …)`; разные имена переменных parsed
- `competitor_prices.py` — `cast(HttpClient, …)`
- `market_trends.py` — явные аннотации `price: float | None` и соседних полей
- `travelline.py` — `source_code/source_type: str | None`; ignore return-value для Client; проверка `dict` после `.json()`
- `max_api.py` — нормализация ответа `.json()` в `dict`
- `max_bot.py` — `for warning in recon_warnings` (не переиспользовать `item`)
- `web/app.py` — `cast(Response, …)` для middleware

## Результат

```text
Success: no issues found in 38 source files
```
