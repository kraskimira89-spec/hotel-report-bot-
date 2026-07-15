# 2026-07-15 — Логи в папку `logs/`

## Что сделано

- `src/utils/logging_setup.py` — консоль + ротация файлов
- `logs/app.log` — все сообщения INFO+
- `logs/error.log` — WARNING+
- подключение в `src/main.py` и startup веб-админки
- том `../logs:/app/logs` в docker-compose
- `logs/` в `.gitignore` (кроме `.gitkeep`)
