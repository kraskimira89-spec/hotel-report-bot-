# 🧾 Техдолг: предупреждения pytest (2026-07-08)

## ✅ Контекст
- Прогон: `python -m pytest`
- Итог: `133 passed`, 3 предупреждения

## ⚠️ Предупреждения
1. **StarletteDeprecationWarning** — `fastapi.testclient` использует deprecated httpx
   - Источник: `fastapi/testclient.py`
   - Сообщение: использовать `httpx2`
2. **DeprecationWarning** — `@app.on_event("startup")` устарел
   - Источник: `src/web/app.py`
   - Рекомендация: перейти на lifespan events

## 🧩 План исправления
- Перевести startup/shutdown на lifespan handler в `src/web/app.py`.
- Проверить, нужен ли `httpx2` или перейти на рекомендованный способ тестирования FastAPI.

## 🔍 Приоритет
- Низкий (только предупреждения, функционал не ломается).
