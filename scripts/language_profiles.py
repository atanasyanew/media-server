#!/usr/bin/env python3
"""Create separate strict audio profiles using the apps' current API schemas.

Does not change existing movie/series profiles, start downloads or delete files.
Japanese subtitle availability is checked after import by the portal, not inferred
from release names. Configure Bazarr separately to fetch full EN/DE subtitles.
"""
import argparse
import copy
import getpass
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

LANGUAGES = {'German': 'de', 'English': 'en', 'Japanese': 'ja'}
PREFIX = 'Media audio · '


def strict_profile(template, format_id, name, radarr):
    profile = copy.deepcopy(template)
    profile.pop('id', None)
    profile.update(name=PREFIX + name, upgradeAllowed=False, minFormatScore=10000,
                   cutoffFormatScore=10000, formatItems=[{'format': format_id, 'name': PREFIX + name, 'score': 10000}])
    allowed_names = {'WEBDL-720p', 'WEBRip-720p', 'Bluray-720p', 'WEBDL-1080p', 'WEBRip-1080p', 'Bluray-1080p'}
    def allow(item):
        children = item.get('items', [])
        if children:
            matches = [allow(child) for child in children]
            item['allowed'] = any(matches)
        else:
            item['allowed'] = item.get('quality', {}).get('name') in allowed_names
        return item['allowed']
    for item in profile['items']:
        allow(item)
    enabled = [item for item in profile['items'] if item['allowed']]
    if not enabled:
        raise ValueError('The app returned no supported HD WEB/Bluray qualities. No profile was created.')
    profile['cutoff'] = enabled[-1].get('id') or enabled[-1]['quality']['id']
    if radarr:
        profile['language'] = {'id': -1, 'name': 'Any'}
    return profile


def create_profiles(call, radarr=False):
    languages = {x['name'].lower(): x['id'] for x in call('language')}
    schema = next(s for s in call('customformat/schema') if s.get('implementation') == 'LanguageSpecification')
    template = call('qualityprofile/schema')[0]
    formats = {x['name']: x for x in call('customformat')}
    profiles = {x['name']: x for x in call('qualityprofile')}
    results = []
    for name in LANGUAGES:
        fullname = PREFIX + name
        # Be conservative on reruns: never overwrite a profile or format an admin edited.
        if fullname in profiles:
            results.append(fullname + ': already exists; unchanged')
            continue
        fmt = formats.get(fullname)
        if fmt is None:
            spec = copy.deepcopy(schema)
            spec.pop('id', None)
            spec.update(name=name, required=True, negate=False)
            field = next(f for f in spec['fields'] if f['name'] == 'value')
            field['value'] = languages[name.lower()]
            fmt = call('customformat', {'name': fullname, 'includeCustomFormatWhenRenaming': False, 'specifications': [spec]})
        else:
            specs = fmt.get('specifications', [])
            if len(specs) != 1 or specs[0].get('implementation') != 'LanguageSpecification' or specs[0].get('negate') or next((f.get('value') for f in specs[0].get('fields', []) if f.get('name') == 'value'), None) != languages[name.lower()]:
                raise ValueError(fullname + ': existing custom format differs; review it manually.')
        profile = strict_profile(template, fmt['id'], name, radarr)
        call('qualityprofile', profile)
        results.append(fullname + ': created (required audio; no fallback)')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', choices=['sonarr', 'radarr'])
    parser.add_argument('--url', help='App base URL; defaults to localhost bootstrap port')
    args = parser.parse_args()
    base = (args.url or ('http://127.0.0.1:' + ('8989' if args.app == 'sonarr' else '7878'))).rstrip('/')
    u = urlsplit(base)
    if u.scheme != 'https' and u.hostname not in {'127.0.0.1', 'localhost'}:
        raise SystemExit('Use HTTPS or the local bootstrap port.')
    key = getpass.getpass('App API key (input hidden): ')
    def call(path, data=None):
        req = Request(base + '/api/v3/' + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'X-Api-Key': key, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    for line in create_profiles(call, args.app == 'radarr'):
        print(line)
    print('Select the desired profile per movie/series in the app. No existing assignments were changed.')


if __name__ == '__main__':
    main()
