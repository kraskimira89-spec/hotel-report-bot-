#!/usr/bin/env bash
# Деплой карточки внедрения рекомендации на VPS
set -euo pipefail
APP=/opt/1apart/hotel-report-bot
CID=$(docker ps -qf name=docker-app-1 | head -1)
echo "CID=$CID"

docker exec "$CID" mkdir -p /app/src/forecast /app/src/notifiers /app/src/web/templates

for f in \
  src/storage/models.py \
  src/storage/db.py \
  src/config.py \
  src/forecast/recommendations.py \
  src/forecast/recommendation_instructions.py \
  src/forecast/service.py \
  src/notifiers/docx_export.py \
  src/web/app.py \
  src/web/queries.py \
  src/web/templates/forecast.html \
  src/web/templates/recommendation_detail.html \
  requirements.txt
do
  docker cp "$APP/$f" "$CID:/app/$f"
done

docker restart "$CID"
sleep 5

docker exec "$CID" python -c "
from src.storage.db import init_db
from src.storage.models import SCHEMA_VERSION
init_db()
print('schema', SCHEMA_VERSION)
"

docker exec "$CID" python -c "
import importlib.util
spec = importlib.util.find_spec('docx')
print('python-docx', 'ok' if spec else 'MISSING')
"

docker exec "$CID" python -c "
from src.forecast.recommendation_instructions import STATUS_LABELS
from src.web import queries
print('reco_card', len(STATUS_LABELS), hasattr(queries, 'fetch_recommendation_card'))
"

echo DONE
