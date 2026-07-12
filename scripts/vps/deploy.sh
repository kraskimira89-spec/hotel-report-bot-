#!/usr/bin/env bash
# Деплой/обновление hotel-report-bot на VPS.
# Пример:
#   DOMAIN=report-bot.1apart.ru APP_DIR=/opt/1apart/hotel-report-bot bash scripts/vps/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/1apart/hotel-report-bot}"
DOMAIN="${DOMAIN:-}"
REPO_URL="${REPO_URL:-git@github.com:kraskimira89-spec/hotel-report-bot-.git}"
COMPOSE_FILE="docker/docker-compose.yml"

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Клонирование в $APP_DIR ..."
  mkdir -p "$(dirname "$APP_DIR")"
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git pull --ff-only

if [[ ! -f config/.env ]]; then
  echo "ОШИБКА: нет config/.env — скопируйте с локальной машины (scp/rsync)."
  echo "  scp config/.env user@VPS:$APP_DIR/config/.env"
  echo "  scp config/primeval-rain-*.json user@VPS:$APP_DIR/config/"
  exit 1
fi

if [[ -n "$DOMAIN" ]]; then
  if ! grep -q '^MAX_WEBHOOK_URL=' config/.env || grep -q '^MAX_WEBHOOK_URL=$' config/.env; then
    echo "Подсказка: задайте MAX_WEBHOOK_URL=https://${DOMAIN}/api/max/webhook в config/.env"
  fi
  if [[ -f docker/nginx.example.conf ]]; then
    sudo sed "s/report-bot.1apart.ru/${DOMAIN}/g" docker/nginx.example.conf \
      | sudo tee "/etc/nginx/sites-available/${DOMAIN}" >/dev/null
    sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}" "/etc/nginx/sites-enabled/${DOMAIN}"
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t
    sudo systemctl reload nginx
    if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
      echo "Выпуск SSL для ${DOMAIN} (нужна A-запись DNS на этот сервер)..."
      sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@${DOMAIN}" || true
    fi
  fi
fi

docker compose -f "$COMPOSE_FILE" up -d --build

echo ""
echo "Контейнер запущен. Проверка:"
docker compose -f "$COMPOSE_FILE" ps
echo ""
echo "Webhook (после MAX_WEBHOOK_URL и SSL):"
echo "  docker compose -f $COMPOSE_FILE exec app python scripts/max_subscribe_webhook.py"
echo "  docker compose -f $COMPOSE_FILE exec app python scripts/max_webhook_status.py"
