#!/bin/bash
# На VPS: деплой кода → backfill категорий 365 → run_forecast
set -euo pipefail
CID=$(docker ps -qf name=docker-app-1)
test -n "$CID"

docker cp /tmp/metrics_history.py "$CID:/app/src/forecast/metrics_history.py"
docker cp /tmp/db.py "$CID:/app/src/storage/db.py"
docker cp /tmp/backfill_metrics_from_tl.py "$CID:/app/scripts/backfill_metrics_from_tl.py"
docker cp /tmp/storage_init.py "$CID:/app/src/storage/__init__.py"
docker cp /tmp/engine.py "$CID:/app/src/forecast/engine.py"
docker cp /tmp/_sample_tl_errors.py "$CID:/app/scripts/_sample_tl_errors.py"
docker cp /tmp/run_after_backfill.sh "$CID:/app/scripts/run_after_backfill.sh"

docker exec -w /app "$CID" python scripts/_sample_tl_errors.py

mkdir -p /var/log/1apart
LOG=/var/log/1apart/backfill_categories_365.log
chmod +x /tmp/run_after_backfill.sh
docker cp /tmp/run_after_backfill.sh "$CID:/app/scripts/run_after_backfill.sh"

nohup docker exec -w /app "$CID" bash scripts/run_after_backfill.sh > "$LOG" 2>&1 &
echo "STARTED pid=$! log=$LOG"
sleep 8
tail -n 30 "$LOG" || true
