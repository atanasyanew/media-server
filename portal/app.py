"""Language selector for a single Plex account, behind Caddy + Authelia.

No media files, API keys or arbitrary upstream URLs are exposed to the browser.
Plex itself remains the player. Stream selections apply to PLEX_TOKEN's account.
"""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

LANGUAGES = {'de': {'de', 'deu', 'ger'}, 'en': {'en', 'eng'}, 'ja': {'ja', 'jpn'}}
NAMES = {'de': 'German', 'en': 'English', 'ja': 'Japanese'}


class UpstreamError(Exception):
    pass


def numeric(value):
    value = str(value)
    if not value.isascii() or not value.isdigit() or len(value) > 20:
        raise ValueError('Invalid item identifier.')
    return value


def language(stream):
    code = stream.get('languageCode', '').lower()
    tag = stream.get('languageTag', '').lower().split('-')[0]
    for key, aliases in LANGUAGES.items():
        if code in aliases or tag in aliases:
            return key
    # Known other languages must not be mistaken for untagged audio.
    return code or tag or 'unknown'


def stream_match(part, kind, lang):
    candidates = [s for s in part.findall('Stream')
                  if s.get('streamType') == str(kind) and language(s) == lang
                  and (kind != 3 or s.get('forced', '0') != '1')]
    # Prefer full audio to commentary/descriptive tracks, then selected tracks.
    candidates = [s for s in candidates if s.get('commentary', '0') != '1'
                  and s.get('visualImpaired', '0') != '1'] if kind == 2 else candidates
    candidates.sort(key=lambda s: s.get('selected', '0') != '1')
    return candidates[0] if candidates else None


def availability(video, audio, subtitle):
    """A version is playable only when EVERY part has the requested tracks."""
    if audio not in LANGUAGES or subtitle not in {*LANGUAGES, 'none'}:
        raise ValueError('Choose German, English or Japanese and a subtitle language.')
    if audio == 'ja' and subtitle == 'none':
        raise ValueError('Choose a subtitle language for Japanese audio.')
    versions = []
    unknown = False
    for media in video.findall('Media'):
        parts = media.findall('Part')
        if not parts:
            unknown = True
            continue
        tracks = []
        for part in parts:
            streams = part.findall('Stream')
            unknown |= not any(s.get('streamType') == '2' for s in streams)
            unknown |= any(s.get('streamType') == '2' and language(s) == 'unknown' for s in streams)
            if subtitle != 'none':
                unknown |= any(s.get('streamType') == '3' and language(s) == 'unknown' for s in streams)
            a = stream_match(part, 2, audio)
            sub = stream_match(part, 3, subtitle) if subtitle != 'none' else None
            tracks.append({'part': part.get('id'), 'audio': a.get('id') if a is not None else None,
                           'subtitle': sub.get('id') if sub is not None else '0' if subtitle == 'none' else None})
        audio_ok = all(t['audio'] for t in tracks)
        subtitle_ok = all(t['subtitle'] is not None for t in tracks)
        versions.append({'id': media.get('id'), 'resolution': media.get('videoResolution', 'unknown'),
                         'available': audio_ok and subtitle_ok, 'audioAvailable': audio_ok,
                         'subtitlesAvailable': subtitle_ok, 'tracks': tracks})
    playable = [v for v in versions if v['available']]
    if playable:
        state, message = 'available', 'Available in your library.'
    elif unknown or not versions:
        state, message = 'unknown', 'Language availability is unknown: some tracks are untagged or not analyzed. Analyze the file in Plex.'
    elif any(v['audioAvailable'] for v in versions):
        state, message = 'missing_subtitles', f'{NAMES[subtitle]} subtitles are not available with {NAMES[audio]} audio in your library.'
    else:
        state, message = 'missing_audio', f'{NAMES[audio]} audio is not available in your library.'
    return {'state': state, 'message': message, 'versions': versions}


class Plex:
    def __init__(self):
        self.base = os.environ.get('PLEX_URL', 'http://plex:32400').rstrip('/')
        self.token = os.environ.get('PLEX_TOKEN', '')

    def request(self, path, params=None, method='GET'):
        if not self.token:
            raise UpstreamError('Plex connection is not configured. Add PLEX_TOKEN on the server.')
        url = self.base + path + ('?' + urlencode(params) if params else '')
        req = Request(url, headers={'X-Plex-Token': self.token, 'Accept': 'application/xml'}, method=method)
        try:
            with urlopen(req, timeout=20) as response:
                data = response.read(16 * 1024 * 1024 + 1)
            if len(data) > 16 * 1024 * 1024:
                raise UpstreamError('Plex response is too large. Narrow your search.')
            if not data.strip():
                return ET.Element('MediaContainer')
            return ET.fromstring(data)
        except (HTTPError, URLError, TimeoutError, ET.ParseError):
            raise UpstreamError('Plex could not be reached or rejected the request. Check its connection and token.') from None

    def metadata(self, item):
        root = self.request('/library/metadata/' + numeric(item))
        video = root.find('Video')
        if video is None:
            raise ValueError('This item has no playable movie or episode.')
        return video

    def libraries(self):
        return [{'id': d.get('key'), 'title': d.get('title'), 'type': d.get('type')}
                for d in self.request('/library/sections').findall('Directory')
                if d.get('type') in {'movie', 'show'}]

    def items(self, section, start, search):
        library = next((s for s in self.libraries() if s['id'] == section), None)
        if not library:
            raise ValueError('Library not found.')
        params = {'type': 1 if library['type'] == 'movie' else 4,
                  'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 50,
                  'includeGuids': 1, 'sort': 'titleSort'}
        if search:
            params['title'] = search[:200]
        root = self.request('/library/sections/' + numeric(section) + '/all', params)
        items = []
        for v in root.findall('Video'):
            title = v.get('title', 'Untitled')
            if v.get('type') == 'episode':
                title = f"{v.get('grandparentTitle', '')} · S{v.get('parentIndex', '?')} E{v.get('index', '?')} · {title}"
            items.append({'id': v.get('ratingKey'), 'title': title, 'year': v.get('year', '')})
        return {'items': items, 'total': int(root.get('totalSize', root.get('size', len(items)))), 'start': start}

    def select(self, item, audio, subtitle, media_id):
        video = self.metadata(item)
        result = availability(video, audio, subtitle)
        version = next((v for v in result['versions'] if v['id'] == media_id and v['available']), None)
        if not version:
            raise ValueError('The requested audio/subtitles are not available in this version. Nothing was changed.')
        # Validate every part and stream before making any write. Never substitute a language.
        for track in version['tracks']:
            for value in track.values():
                numeric(value)
        try:
            for track in version['tracks']:
                self.request('/library/parts/' + track['part'],
                             {'audioStreamID': track['audio'], 'subtitleStreamID': track['subtitle'], 'allParts': 0}, 'PUT')
            refreshed = self.metadata(item)
            parts = {p.get('id'): p for p in refreshed.findall('Media/Part')}
            for track in version['tracks']:
                p = parts.get(track['part'])
                if p is None:
                    raise UpstreamError('The file changed during selection. Refresh and try again.')
                selected = {s.get('id') for s in p.findall('Stream') if s.get('selected') == '1'}
                selected_sub = {s.get('id') for s in p.findall('Stream') if s.get('streamType') == '3' and s.get('selected') == '1'}
                if track['audio'] not in selected or (track['subtitle'] != '0' and track['subtitle'] not in selected_sub) or (track['subtitle'] == '0' and selected_sub):
                    raise UpstreamError('Plex did not confirm the selected tracks. Check them in the Plex player.')
        except UpstreamError:
            raise UpstreamError('Plex could not confirm all track changes. Some parts may have changed; check the Plex player before watching.') from None
        machine = self.request('/').get('machineIdentifier', '')
        if not machine:
            raise UpstreamError('Tracks were saved, but Plex did not provide its server ID. Open the title directly in Plex.')
        return {'message': 'Audio and subtitles saved for your connected Plex account. Open Plex and choose the matching version if prompted.',
                'plexUrl': 'https://app.plex.tv/desktop/#!/server/' + quote(machine, safe='') + '/details?key=' + quote('/library/metadata/' + numeric(item), safe='')}


class VPN:
    """Surfshark credentials saved for Gluetun, applied live through its control server."""
    def __init__(self):
        self.folder = Path(os.environ.get('VPN_DIR', '/vpn'))
        self.base = os.environ.get('GLUETUN_URL', 'http://gluetun:8000')

    def request(self, path, body=None):
        key = (self.folder / 'control.key').read_text().strip()
        req = Request(self.base + path, data=None if body is None else json.dumps(body).encode(), method='GET' if body is None else 'PUT',
                      headers={'X-API-Key': key, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=10) as response:
            return response.read(65536)

    def status(self):
        configured = all((self.folder / name).exists() for name in ('openvpn_user', 'openvpn_password'))
        try:
            state = json.loads(self.request('/v1/vpn/status')).get('status', 'unknown')
            ip = json.loads(self.request('/v1/publicip/ip')) if state == 'running' else {}
        except (OSError, ValueError):
            state, ip = 'unreachable', {}
        return {'configured': configured, 'status': state, 'ip': ip.get('public_ip', ''), 'country': ip.get('country', '')}

    def save(self, username, password):
        username, password = username.strip(), password.strip()
        if not all(0 < len(v) <= 200 and v.isprintable() for v in (username, password)):
            raise ValueError('Enter the Surfshark manual-setup username and password.')
        try:
            for name, value in (('openvpn_user', username), ('openvpn_password', password)):
                tmp = self.folder / (name + '.tmp')
                tmp.unlink(missing_ok=True)
                with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
                    f.write(value)
                os.replace(tmp, self.folder / name)
        except OSError:
            raise UpstreamError('Could not save the credentials. Run scripts/setup.py as the PUID user so provision/vpn is writable.') from None
        try:
            self.request('/v1/vpn/settings', {'openvpn': {'user': username, 'password': password}})
        except HTTPError:
            raise UpstreamError('Saved, but the VPN rejected them. Check the Surfshark manual-setup credentials.') from None
        except URLError:
            return {'message': 'Saved. The VPN starts with these credentials within a minute.'}
        except OSError:
            raise UpstreamError('Saved. Run scripts/setup.py, then: docker compose restart gluetun') from None
        return {'message': 'Saved. The VPN is reconnecting with these credentials.'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'MediaPortal'

    def log_message(self, fmt, *args):
        # Do not log URLs, cookies or request bodies.
        print('portal request', self.command, flush=True)

    def send(self, code, value, content_type='application/json'):
        data = json.dumps(value).encode() if content_type == 'application/json' else value
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.handle_request(False)

    def do_POST(self):
        self.handle_request(True)

    def handle_request(self, write):
        self.connection.settimeout(30)
        parsed = urlsplit(self.path)
        if parsed.path == '/healthz' and not write:
            return self.send(200, {'status': 'ok'})
        if not self.headers.get('Remote-User'):
            return self.send(401, {'error': 'Sign in through the secure media address.'})
        if write:
            origin = os.environ.get('PORTAL_ORIGIN', '')
            if not origin or not hmac.compare_digest(self.headers.get('Origin', ''), origin) or self.headers.get('X-Media-Request') != '1':
                return self.send(403, {'error': 'Request origin was rejected.'})
        q = parse_qs(parsed.query)
        get = lambda key, default='': q.get(key, [default])[0]
        try:
            plex = Plex()
            if not write and parsed.path == '/':
                return self.send(200, Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
            if not write and parsed.path == '/api/config':
                domain = os.environ.get('MEDIA_DOMAIN', '')
                return self.send(200, {'apps': {key: f'https://{sub}.{domain}' for key, sub in
                    [('Series', 'sonarr'), ('Movies', 'radarr'), ('Sources', 'prowlarr'), ('Subtitles', 'bazarr'), ('Requests', 'requests'), ('Downloads', 'downloads'), ('Account / sign out', 'auth')]}})
            if not write and parsed.path == '/api/libraries':
                return self.send(200, plex.libraries())
            if not write and parsed.path == '/api/items':
                start = int(get('start', '0'))
                if start < 0 or start > 1000000:
                    raise ValueError('Invalid page.')
                return self.send(200, plex.items(numeric(get('section')), start, get('search')))
            if not write and parsed.path == '/api/availability':
                return self.send(200, availability(plex.metadata(get('item')), get('audio', 'de'), get('subtitle', 'none')))
            if not write and parsed.path == '/api/vpn':
                return self.send(200, VPN().status())
            if write and parsed.path in {'/api/select', '/api/vpn'}:
                size = int(self.headers.get('Content-Length', '0'))
                if size < 1 or size > 4096 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Invalid request body.')
                data = json.loads(self.rfile.read(size))
                if parsed.path == '/api/vpn':
                    try:
                        return self.send(200, VPN().save(str(data['username']), str(data['password'])))
                    except (ValueError, KeyError, TypeError):
                        return self.send(400, {'error': 'Enter the Surfshark manual-setup username and password.'})
                return self.send(200, plex.select(numeric(data['item']), data['audio'], data['subtitle'], numeric(data['media'])))
            return self.send(404, {'error': 'Not found.'})
        except (ValueError, KeyError, TypeError, UnicodeError):
            return self.send(400, {'error': 'Invalid selection. Refresh the page and choose a listed item, language and version.'})
        except UpstreamError as error:
            return self.send(502, {'error': str(error)})


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8090), Handler).serve_forever()
