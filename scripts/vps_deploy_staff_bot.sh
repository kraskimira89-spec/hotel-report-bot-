#!/usr/bin/env bash
# Деплой staff_bot / first-connect на VPS
set -euo pipefail
APP=/opt/1apart/hotel-report-bot
CID=$(docker ps -qf name=docker-app-1 | head -1)
echo "CID=$CID"
docker exec "$CID" mkdir -p /app/src/staff_bot
docker cp "$APP/src/staff_bot/." "$CID:/app/src/staff_bot/"
docker cp "$APP/src/notifiers/max_api.py" "$CID:/app/src/notifiers/max_api.py"
docker cp "$APP/src/notifiers/max_webhook.py" "$CID:/app/src/notifiers/max_webhook.py"
docker cp "$APP/src/config.py" "$CID:/app/src/config.py"
docker cp "$APP/src/storage/models.py" "$CID:/app/src/storage/models.py"
docker cp "$APP/src/storage/db.py" "$CID:/app/src/storage/db.py"
docker cp "$APP/config/settings.yaml" "$CID:/app/config/settings.yaml"
docker restart "$CID"
sleep 5
docker exec "$CID" python -c "from src.storage.db import init_db; init_db(); from src.config import reload_config, get_config; reload_config(); c=get_config(); print('ok', c.staff_bot.enabled, c.staff_bot.dry_run)"
docker exec "$CID" python scripts/max_subscribe_webhook.py || true
docker exec "$CID" python scripts/max_set_commands.py || true
echo DONE
