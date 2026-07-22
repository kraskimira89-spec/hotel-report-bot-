#!/usr/bin/env bash
# Деплой weekly email v2 на VPS (docker cp + restart)
set -euo pipefail
APP=/opt/1apart/hotel-report-bot
CID=$(docker ps -qf name=docker-app-1 | head -1)
echo "CID=$CID"

docker exec "$CID" mkdir -p \
  /app/src/notifiers/weekly \
  /app/src/data_sources \
  /app/src/web/templates \
  /app/prompts \
  /app/data/report_snapshots

FILES=(
  src/notifiers/weekly/__init__.py
  src/notifiers/weekly/models.py
  src/notifiers/weekly/data.py
  src/notifiers/weekly/html.py
  src/notifiers/weekly/plain.py
  src/notifiers/weekly/subject.py
  src/notifiers/weekly/executive.py
  src/notifiers/weekly/data_quality.py
  src/notifiers/weekly/formatting.py
  src/notifiers/email_sender.py
  src/data_sources/industry_trends.py
  src/data_sources/industry_trends_llm.py
  src/scheduler.py
  src/config.py
  src/storage/db.py
  src/storage/models.py
  src/web/app.py
  src/web/queries.py
  src/web/templates/reports.html
  src/web/templates/trends.html
  prompts/05_weekly_executive.md
  prompts/06_industry_trends.md
  config/settings.yaml
)

for f in "${FILES[@]}"; do
  docker cp "$APP/$f" "$CID:/app/$f"
done

docker restart "$CID"
sleep 8

docker exec "$CID" python -c "
from src.config import get_config
from src.scheduler import job_weekly_email
cfg = get_config()
print('timezone', cfg.property.timezone)
print('weekly_email_cron', cfg.scheduler.weekly_email_cron)
print('email.use_llm', cfg.email.use_llm)
print('market_news.enrich_with_llm', cfg.market_news.enrich_with_llm)
print('job', job_weekly_email.__name__)
"

echo DONE
