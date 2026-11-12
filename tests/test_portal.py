import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('portal', ROOT / 'portal/app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def video(audio='deu', subtitle='eng', extra='', forced='0'):
    return ET.fromstring(f'''<Video ratingKey="7"><Media id="8" videoResolution="1080"><Part id="9">
      <Stream id="10" streamType="2" languageCode="{audio}" selected="1"/>
      <Stream id="11" streamType="3" languageCode="{subtitle}" forced="{forced}" selected="1"/>
      {extra}</Part></Media></Video>''')


class AvailabilityTests(unittest.TestCase):
    def test_german_audio_with_english_subtitles(self):
        self.assertEqual(app.availability(video(), 'de', 'en')['state'], 'available')

    def test_languages_and_aliases(self):
        for key, aliases in app.LANGUAGES.items():
            for alias in aliases:
                self.assertEqual(app.availability(video(alias), key, 'en')['state'], 'available')

    def test_japanese_requires_subtitles(self):
        with self.assertRaises(ValueError):
            app.availability(video('jpn'), 'ja', 'none')

    def test_missing_audio_has_no_fallback(self):
        result = app.availability(video('eng'), 'de', 'none')
        self.assertEqual(result['state'], 'missing_audio')
        self.assertIn('in your library', result['message'])
        self.assertFalse(result['versions'][0]['available'])

    def test_missing_subtitles(self):
        self.assertEqual(app.availability(video('jpn', 'ger'), 'ja', 'en')['state'], 'missing_subtitles')

    def test_forced_subtitles_do_not_count_as_full(self):
        self.assertEqual(app.availability(video('jpn', forced='1'), 'ja', 'en')['state'], 'missing_subtitles')

    def test_unknown_audio_is_not_reported_as_nonexistent(self):
        self.assertEqual(app.availability(video(''), 'de', 'none')['state'], 'unknown')
        self.assertEqual(app.availability(ET.fromstring('<Video/>'), 'de', 'none')['state'], 'unknown')

    def test_language_tag(self):
        v = video('')
        v.find('Media/Part/Stream').set('languageTag', 'de-DE')
        self.assertEqual(app.availability(v, 'de', 'none')['state'], 'available')

    def test_untagged_subtitles_remain_unknown(self):
        self.assertEqual(app.availability(video('jpn', ''), 'ja', 'en')['state'], 'unknown')

    def test_multipart_requires_audio_in_every_part(self):
        v = video()
        v.find('Media').append(video('eng').find('Media/Part'))
        self.assertEqual(app.availability(v, 'de', 'none')['state'], 'missing_audio')

    def test_cannot_mix_audio_and_subtitles_across_versions(self):
        v = video('jpn', 'deu')
        second = video('eng', 'eng').find('Media')
        second.set('id', '99')
        v.append(second)
        self.assertEqual(app.availability(v, 'ja', 'en')['state'], 'missing_subtitles')

    def test_commentary_does_not_count_as_dub(self):
        v = video()
        v.find('Media/Part/Stream').set('commentary', '1')
        self.assertEqual(app.availability(v, 'de', 'none')['state'], 'missing_audio')

    def test_subtitles_off_needs_no_subtitle_track(self):
        v = video()
        p = v.find('Media/Part')
        p.remove(p.findall('Stream')[1])
        self.assertEqual(app.availability(v, 'de', 'none')['state'], 'available')


class SelectionTests(unittest.TestCase):
    def test_unavailable_selection_never_writes_to_plex(self):
        p = app.Plex()
        with patch.object(p, 'metadata', return_value=video('eng')), patch.object(p, 'request') as req:
            with self.assertRaises(ValueError):
                p.select('7', 'de', 'none', '8')
            req.assert_not_called()

    def test_save_and_readback(self):
        p = app.Plex()
        with patch.object(p, 'metadata', return_value=video()), patch.object(p, 'request', return_value=ET.fromstring('<MediaContainer machineIdentifier="server"/>')) as req:
            result = p.select('7', 'de', 'en', '8')
            req.assert_any_call('/library/parts/9', {'audioStreamID': '10', 'subtitleStreamID': '11', 'allParts': 0}, 'PUT')
            self.assertIn('server/server/details', result['plexUrl'])

    def test_unconfirmed_write_is_an_error(self):
        p = app.Plex()
        v = video()
        v.find('Media/Part/Stream').set('selected', '0')
        with patch.object(p, 'metadata', return_value=v), patch.object(p, 'request'):
            with self.assertRaises(app.UpstreamError):
                p.select('7', 'de', 'en', '8')

    def test_path_traversal_is_rejected(self):
        for value in ['../7', '7?x=1', '７', '-1', '']:
            with self.assertRaises(ValueError):
                app.numeric(value)

    def test_missing_plex_token_is_configuration_error(self):
        with patch.dict(os.environ, {'PLEX_TOKEN': ''}):
            with self.assertRaises(app.UpstreamError):
                app.Plex().request('/')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, data=None, headers=None):
        req = Request(self.base + path, data=data, headers=headers or {})
        try:
            with urlopen(req) as r:
                return r.status, r.headers, r.read()
        except HTTPError as r:
            return r.code, r.headers, r.read()

    def test_unauthenticated_library_is_denied(self):
        self.assertEqual(self.request('/api/libraries')[0], 401)

    def test_cross_origin_write_is_denied(self):
        with patch.dict(os.environ, {'PORTAL_ORIGIN': 'https://media.home.arpa'}):
            code, _, _ = self.request('/api/select', b'{}', {'Remote-User': 'admin', 'Origin': 'https://attacker.test', 'X-Media-Request': '1'})
            self.assertEqual(code, 403)

    def test_security_headers_and_no_store(self):
        code, headers, body = self.request('/', headers={'Remote-User': 'admin'})
        self.assertEqual(code, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn(b'X-Plex-Token', body)

    def test_invalid_json_is_handled(self):
        with patch.dict(os.environ, {'PORTAL_ORIGIN': 'https://media.home.arpa'}):
            code, _, _ = self.request('/api/select', b'{', {'Remote-User': 'admin', 'Origin': 'https://media.home.arpa', 'X-Media-Request': '1', 'Content-Type': 'application/json'})
            self.assertEqual(code, 400)

    def test_upstream_error_never_becomes_missing_language(self):
        with patch.object(app.Plex, 'metadata', side_effect=app.UpstreamError('Connection unavailable')):
            code, _, body = self.request('/api/availability?item=7&audio=de&subtitle=none', headers={'Remote-User': 'admin'})
            self.assertEqual(code, 502)
            self.assertIn(b'Connection unavailable', body)


class VPNTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / 'control.key').write_text('secret-key')
        self.env = patch.dict(os.environ, {'VPN_DIR': self.tmp.name, 'GLUETUN_URL': 'http://gluetun.test:8000'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_save_writes_private_files_and_applies_live(self):
        with patch.object(app, 'urlopen') as opened:
            opened.return_value.__enter__.return_value.read.return_value = b'ok'
            result = app.VPN().save(' user1 ', 'pass word')
        self.assertIn('reconnecting', result['message'])
        self.assertEqual((self.folder / 'openvpn_user').read_text(), 'user1')
        self.assertEqual((self.folder / 'openvpn_password').read_text(), 'pass word')
        self.assertEqual((self.folder / 'openvpn_password').stat().st_mode & 0o777, 0o600)
        req = opened.call_args[0][0]
        self.assertEqual((req.full_url, req.get_method(), req.get_header('X-api-key')), ('http://gluetun.test:8000/v1/vpn/settings', 'PUT', 'secret-key'))
        self.assertEqual(json.loads(req.data), {'openvpn': {'user': 'user1', 'password': 'pass word'}})

    def test_save_while_vpn_is_down_waits_for_restart(self):
        with patch.object(app, 'urlopen', side_effect=app.URLError('refused')):
            self.assertIn('within a minute', app.VPN().save('u', 'p')['message'])
        self.assertTrue((self.folder / 'openvpn_user').exists())

    def test_invalid_credentials_are_not_saved(self):
        for user, password in [('', 'p'), ('u', ''), ('u\nx', 'p'), ('u', 'p' * 201)]:
            with self.assertRaises(ValueError):
                app.VPN().save(user, password)
        self.assertFalse((self.folder / 'openvpn_user').exists())

    def test_status_when_gluetun_is_unreachable(self):
        with patch.object(app, 'urlopen', side_effect=app.URLError('refused')):
            self.assertEqual(app.VPN().status(), {'configured': False, 'status': 'unreachable', 'ip': '', 'country': ''})


if __name__ == '__main__':
    unittest.main()
