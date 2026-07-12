#!/usr/bin/env bash
set -euo pipefail
DOMAIN=bot.masterklepa.online
APP_DIR=/opt/1apart/hotel-report-bot
ENV_FILE="$APP_DIR/config/.env"

if grep -q '^MAX_WEBHOOK_URL=' "$ENV_FILE"; then
  sed -i "s|^MAX_WEBHOOK_URL=.*|MAX_WEBHOOK_URL=https://${DOMAIN}/api/max/webhook|" "$ENV_FILE"
else
  echo "MAX_WEBHOOK_URL=https://${DOMAIN}/api/max/webhook" >> "$ENV_FILE"
fi
if grep -q '^WEB_FORCE_HTTPS=' "$ENV_FILE"; then
  sed -i 's|^WEB_FORCE_HTTPS=.*|WEB_FORCE_HTTPS=true|' "$ENV_FILE"
else
  echo 'WEB_FORCE_HTTPS=true' >> "$ENV_FILE"
fi

cat > /etc/apache2/sites-available/bot.masterklepa.online.conf <<EOF
<VirtualHost *:80>
    ServerName ${DOMAIN}

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:4444/
    ProxyPassReverse / http://127.0.0.1:4444/

    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"

    ErrorLog \${APACHE_LOG_DIR}/bot.masterklepa.online-error.log
    CustomLog \${APACHE_LOG_DIR}/bot.masterklepa.online-access.log combined
</VirtualHost>
EOF

a2enmod proxy proxy_http headers ssl 2>/dev/null || true
a2ensite bot.masterklepa.online.conf
apache2ctl configtest
systemctl reload apache2

if ! command -v certbot >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq certbot python3-certbot-apache
fi
certbot --apache -d "$DOMAIN" --non-interactive --agree-tos -m "admin@masterklepa.online" --redirect

docker compose -f "$APP_DIR/docker/docker-compose.yml" up -d --force-recreate
sleep 3
echo "HTTP:" $(curl -s -o /dev/null -w "%{http_code}" "http://${DOMAIN}/health")
echo "HTTPS:" $(curl -sk -o /dev/null -w "%{http_code}" "https://${DOMAIN}/health")
curl -sk "https://${DOMAIN}/health"
echo
