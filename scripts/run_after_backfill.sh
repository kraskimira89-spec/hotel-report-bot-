#!/bin/bash
set -euo pipefail
cd /app
export PYTHONPATH=/app
echo "=== START $(date -Iseconds) ==="
python scripts/backfill_metrics_from_tl.py --days 365 --delay 0.2
echo "=== BACKFILL DONE $(date -Iseconds) ==="
python scripts/run_forecast.py
echo "=== FORECAST DONE $(date -Iseconds) ==="
python - <<'PY'
import sys
sys.path.insert(0, "/app")
from src.storage.db import get_connection
c = get_connection()
print("category days:")
for r in c.execute(
    """
    SELECT metric_type, COUNT(DISTINCT report_date) AS days
    FROM metrics_daily
    WHERE metric_type LIKE 'category:%'
    GROUP BY metric_type
    ORDER BY days DESC
    """
):
    print(dict(r))
print("rec types new:", [dict(x) for x in c.execute(
    "SELECT recommendation_type, COUNT(*) n FROM price_recommendations WHERE status='new' GROUP BY 1"
)])
print("tl open", c.execute(
    "SELECT COUNT(*) FROM errors_log WHERE source='travelline' AND resolved=0"
).fetchone()[0])
PY
echo "=== ALL DONE $(date -Iseconds) ==="
