#!/usr/bin/env python3
"""Create local authentication files without committing credentials."""
import argparse
import base64
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import string

ROOT = Path(__file__).resolve().parents[1]


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError('Invalid .env line. Use KEY=value, without shell commands.')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def validate_domain(domain):
    if not re.fullmatch(r'(?=.{1,200}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', domain) or len(domain.split('.')) < 3 or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-') for label in domain.split('.')):
        raise ValueError('Use a dedicated subdomain, e.g. media.home.arpa or media.example.com.')
    return domain


def generate(root, domain, username, digest, email):
    validate_domain(domain)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', username):
        raise ValueError('Username must contain only letters, digits, underscores or hyphens.')
    if not re.fullmatch(r'\$argon2id\$v=19\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]+', digest):
        raise ValueError('Paste only the complete $argon2id$ digest from Authelia.')
    if '@' not in email or '\n' in email:
        raise ValueError('Enter a valid email address.')
    folder = root / 'provision/authelia'
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'configuration.yml').exists() or (folder / 'users_database.yml').exists():
        raise ValueError('Authentication is already configured. Edit the existing files; setup will not replace users or keys.')
    folder.chmod(0o700)
    def private(name, data):
        path = folder / name
        with path.open('x') as f:
            f.write(data)
        path.chmod(0o600)
    config = (root / 'deploy/authelia.template.yml').read_text().replace('${MEDIA_DOMAIN}', domain)
    private('configuration.yml', config)
    private('users_database.yml', json.dumps({'users': {username: {'displayname': username,
        'password': digest, 'email': email, 'groups': ['admins']}}}, indent=2) + '\n')
    for filename in ['session.secret', 'storage.secret', 'jwt.secret']:
        if not (folder / filename).exists():
            private(filename, ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(64)))
    for name in ['movies', 'tv', 'music', 'kids', 'movies favorite']:
        (root / 'content/media' / name).mkdir(parents=True, exist_ok=True)
    for name in ['movies', 'tv', 'music']:
        (root / 'content/torrents' / name).mkdir(parents=True, exist_ok=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    os.umask(0o077)
    envfile = ROOT / '.env'
    if not envfile.exists():
        raise SystemExit('First copy .env.example to .env and add your Surfshark manual WireGuard settings.')
    env = read_env(envfile)
    domain = validate_domain(env.get('MEDIA_DOMAIN', ''))
    try:
        key = base64.b64decode(env.get('WIREGUARD_PRIVATE_KEY', ''), validate=True)
        if len(key) != 32:
            raise ValueError()
        ipaddress.ip_interface(env['WIREGUARD_ADDRESSES'])
    except (ValueError, KeyError):
        raise SystemExit('Add a valid Surfshark WireGuard private key and IPv4/CIDR address in .env.') from None
    print('Generate a password hash in another terminal (your password stays local):')
    print('docker run --rm -it authelia/authelia:4.39.28 authelia crypto hash generate argon2')
    username = input('Login username: ').strip()
    email = input('Account email: ').strip()
    digest = getpass.getpass('Paste the Digest value ($argon2id$…, without "Digest:"): ').strip()
    generate(ROOT, domain, username, digest, email)
    envfile.chmod(0o600)
    print('Authentication created. Next run: docker compose config --quiet')
    print('Then validate Authelia and Caddy as described in README.md before starting services.')


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
