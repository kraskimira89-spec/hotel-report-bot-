# Weekly email v2

Дата: 2026-07-22

## Изменения

- Модуль `src/notifiers/weekly/` — 9 блоков управленческого отчёта
- SCHEMA 18: расширен `reports_log` (snapshots, data_quality, recipient_count)
- SCHEMA 19: расширен `trends`, таблица `trend_email_log` (dedup 4 недели)
- `src/data_sources/industry_trends.py` — Block 9, max 3 approved тренда
- Таймзона: `Europe/Tomsk`
- Cron: weekly email пн 08:00, pre-step forecast(14d) + recommendations + events + trends enrich
- Админка: превью HTML, test-send, approve/reject трендов, create-pilot-rec
- `enrich_pending_trends()` — pre-step перед weekly email
- `tests/test_industry_trends.py` — dedup, leading badge, pilot rec

- **LLM:** `email.use_llm` / `market_news.enrich_with_llm` в settings.yaml (по умолчанию false)

## Операции

```bash
# Dry-run локально (нужна БД)
python scripts/send_weekly_dry_run.py --init-db

# Одобрить тренды для Block 9
python scripts/approve_pending_trends.py --enrich --min-score 60

# Деплой на VPS
bash scripts/vps_deploy_weekly_email.sh
```
