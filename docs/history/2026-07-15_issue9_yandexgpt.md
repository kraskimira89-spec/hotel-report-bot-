# История: Issue #9 YandexGPT Lite

Дата: 2026-07-15

## Сделано
- `_build_llm_headers` / `_resolve_llm_settings` в `src/analytics/ai_insights.py`
- Заголовки Yandex: `Authorization: Api-Key` + `OpenAI-Project`
- Env: `LLM_API_KEY`, `LLM_FOLDER_ID`, `LLM_BASE_URL`, `LLM_MODEL` (+ фолбэк OPENAI_*)
- `config/.env.example` с folder_id и моделью Lite
- Тесты `tests/test_llm_headers.py` — 2 passed

## Не в git
- Секретный `LLM_API_KEY` — только в локальном/VPS `.env` (лично разработчику)

## Следующее
- ~~Прописать ключ ~~ ✅ локально + на VPS
- ~~«Обновить»~~ ✅ на VPS: `run_insights_refresh` → **10 карточек** (≈24 с)
- Smoke API: HTTP 200 YandexGPT Lite
- При слабом качестве: модель Pro одной строкой
- Параллельно: TravelLine API (Issue #8) — ключи в `.env` есть, но 401/404
