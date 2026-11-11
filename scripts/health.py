#!/usr/bin/env python3
"""Run locally from cron/systemd. Reports disk and container problems.

Set ALERT_WEBHOOK in the environment to opt into JSON webhook notifications.
It is never read from the repository or sent by default.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def inspect():
    problems = []
    disk = shutil.disk_usage(ROOT / 'content' if (ROOT / 'content').exists() else ROOT)
    if disk.free < max(10 * 1024 ** 3, disk.total * 0.1):
        problems.append('Media storage is low: less than 10 GiB or 10% free.')
    result = subprocess.run(['docker', 'compose', 'ps', '--all', '--format', 'json'], cwd=ROOT, capture_output=True, text=True, check=True)
    raw = result.stdout.strip()
    rows = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines() if line]
    if not rows:
        problems.append('No media containers found.')
    required = {'plex', 'radarr', 'sonarr', 'prowlarr', 'bazarr', 'qbittorrent', 'gluetun', 'portal', 'caddy', 'authelia', 'redis', 'overseerr'}
    present = {row.get('Service') for row in rows}
    for service in sorted(required - present):
        problems.append(f'{service}: container is missing.')
    for row in rows:
        if row.get('State') != 'running' or row.get('Health') == 'unhealthy':
            problems.append(f"{row.get('Service', 'container')}: {row.get('State')} {row.get('Health', '')}")
    return problems


if __name__ == '__main__':
    try:
        problems = inspect()
    except (OSError, subprocess.CalledProcessError, ValueError):
        problems = ['Unable to inspect Docker Compose. Check Docker and server configuration.']
    if problems:
        print('\n'.join(problems))
        webhook = os.environ.get('ALERT_WEBHOOK', '')
        if webhook:
            if not webhook.startswith('https://'):
                raise SystemExit('ALERT_WEBHOOK must use HTTPS.')
            with urlopen(Request(webhook, data=json.dumps({'text': '\n'.join(problems)}).encode(), headers={'Content-Type': 'application/json'}), timeout=15):
                pass
        raise SystemExit(1)
    print('Containers and disk space are healthy.')
