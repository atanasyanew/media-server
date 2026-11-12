#!/usr/bin/env bash
# Builds and starts the whole stack. Safe to run again at any time.
set -euo pipefail
cd -- "$(dirname -- "$0")"

if [ ! -f .env ]; then
  echo 'First run: cp .env.example .env and set MEDIA_DOMAIN (see README).' >&2
  exit 1
fi
if [ ! -f provision/authelia/configuration.yml ] || [ ! -f provision/vpn/control.key ]; then
  python3 scripts/setup.py
fi

if [ -f provision/vpn/openvpn_user ]; then
  docker compose up -d --build
  exit
fi

# No Surfshark credentials yet: qBittorrent waits for the VPN, so start everything else first.
docker compose up -d --build $(docker compose config --services | grep -vx qbittorrent)
domain=$(sed -n 's/^MEDIA_DOMAIN=//p' .env | tr -d "\"'")
echo "Open https://$domain, enter your Surfshark credentials and press Connect."
echo 'Waiting for them (Ctrl+C to stop; running ./start.sh later also works)...'
until [ -f provision/vpn/openvpn_user ] && [ "$(docker compose ps --format '{{.Health}}' gluetun)" = healthy ]; do sleep 5; done
docker compose up -d
