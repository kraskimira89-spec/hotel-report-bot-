#!/usr/bin/env bash
# Деплой ежедневной сверки сводки vs TravelLine на VPS
set -euo pipefail
APP=/opt/1apart/hotel-report-bot
CID=$(docker ps -qf name=docker-app-1 | head -1)
echo "CID=$CID"

docker exec "$CID" mkdir -p /app/src/data_sources /app/scripts /app/config

for f in \
  src/data_sources/summary_reconcile.py \
  src/scheduler.py \
  src/config.py \
  scripts/reconcile_summary_travelline.py \
  scripts/run_daily_pipeline.py \
  config/settings.yaml
do
  docker cp "$APP/$f" "$CID:/app/$f"
done

docker restart "$CID"
sleep 5

docker exec "$CID" python -c "
from src.config import get_config
from src.scheduler import job_summary_travelline_reconcile
cfg = get_config()
print('dry_run', cfg.dry_run)
print('summary_reconcile_cron', cfg.scheduler.summary_reconcile_cron)
print('job', job_summary_travelline_reconcile.__name__)
"

echo DONE
