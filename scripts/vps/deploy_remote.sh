#!/usr/bin/env bash
# Деплой на VPS с локальной машины или CI (SSH + git pull + docker compose).
# Требует: SSH-ключ, git push в origin/main до деплоя.
set -euo pipefail

VPS_HOST="${VPS_HOST:-91.229.11.147}"
VPS_USER="${VPS_USER:-root}"
VPS_APP_DIR="${VPS_APP_DIR:-/opt/1apart/hotel-report-bot}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/docker-compose.yml}"

REMOTE="cd ${VPS_APP_DIR} && git pull --ff-only && docker compose -f ${COMPOSE_FILE} up -d --build"

echo "Деплой → ${VPS_USER}@${VPS_HOST}:${VPS_APP_DIR}"
ssh -o BatchMode=yes "${VPS_USER}@${VPS_HOST}" "${REMOTE}"
echo "Готово."
