#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
echo 'VPN container health:'
docker compose ps gluetun qbittorrent
echo 'Public IP seen inside the downloader network namespace:'
docker compose exec -T qbittorrent curl --fail --max-time 15 https://api.ipify.org
echo
echo 'Confirm this is a Surfshark exit IP, not your home IP. See README for the outage test.'
