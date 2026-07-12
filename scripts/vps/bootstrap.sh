#!/usr/bin/env bash
# Первичная настройка VPS (Ubuntu/Debian, reg.ru и аналоги).
# Запуск на сервере: sudo bash scripts/vps/bootstrap.sh
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Запустите от root: sudo bash $0"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl gnupg ufw nginx certbot python3-certbot-nginx git

# Docker (официальный репозиторий)
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi

source /etc/os-release
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} \
  ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

systemctl enable docker nginx
systemctl start docker

# Firewall: SSH + HTTP/HTTPS
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

mkdir -p /opt/1apart
echo "Bootstrap готов. Далее: клонировать репозиторий в /opt/1apart/hotel-report-bot и запустить deploy.sh"
