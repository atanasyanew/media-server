import importlib.util
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


setup = module('setup')
profiles = module('language_profiles')
# Public fixture only, never a deployment credential.
DIGEST = '$argon2id$v=19$m=65536,t=3,p=4$Hjc8e7WYcBFcJmEDUOsS9A$ozM7RyZR1EyDR8cuyVpDDfmLrGPGFgo5E2NNqRumui4'


class SetupTests(unittest.TestCase):
    def test_generates_private_config_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'deploy').mkdir()
            (root / 'deploy/authelia.template.yml').write_text((ROOT / 'deploy/authelia.template.yml').read_text())
            setup.generate(root, 'media.home.arpa', 'admin', DIGEST, 'admin@example.com')
            folder = root / 'provision/authelia'
            config = yaml.safe_load((folder / 'configuration.yml').read_text())
            self.assertEqual(config['session']['remember_me'], '30d')
            self.assertEqual(config['access_control']['default_policy'], 'deny')
            self.assertEqual((folder / 'storage.secret').stat().st_mode & 0o777, 0o600)
            self.assertEqual(len((folder / 'session.secret').read_text()), 64)
            with self.assertRaises(ValueError):
                setup.generate(root, 'media.home.arpa', 'admin', DIGEST, 'admin@example.com')

    def test_vpn_files_share_one_key_and_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup.vpn_files(root)
            key = (root / 'provision/vpn/control.key').read_text()
            self.assertIn(f'apikey = "{key}"', (root / 'provision/gluetun/auth/config.toml').read_text())
            self.assertEqual((root / 'provision/vpn').stat().st_mode & 0o777, 0o700)
            setup.vpn_files(root)
            self.assertEqual((root / 'provision/vpn/control.key').read_text(), key)

    def test_domain_injection_rejected(self):
        for value in ['localhost', 'example.com', 'x\npolicy: bypass', 'media.*.com', 'media.bad-.com']:
            with self.assertRaises(ValueError):
                setup.validate_domain(value)

    def test_env_is_data_not_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / '.env'
            p.write_text("PLEX_TOKEN='$(touch unexpected)'\n")
            self.assertEqual(setup.read_env(p)['PLEX_TOKEN'], '$(touch unexpected)')


class ProfileTests(unittest.TestCase):
    def test_strict_profile_has_no_fallback_and_does_not_mutate_template(self):
        template = {'id': 1, 'items': [{'quality': {'id': 4, 'name': 'HDTV-1080p'}, 'allowed': True},
            {'id': 20, 'items': [{'quality': {'id': 5, 'name': 'WEBDL-1080p'}, 'allowed': False}]}]}
        result = profiles.strict_profile(template, 9, 'German', True)
        self.assertEqual(result['minFormatScore'], 10000)
        self.assertEqual(result['formatItems'][0]['score'], 10000)
        self.assertFalse(result['items'][0]['allowed'])
        self.assertTrue(result['items'][1]['items'][0]['allowed'])
        self.assertEqual(result['cutoff'], 20)
        self.assertEqual(result['language']['name'], 'Any')
        self.assertFalse(template['items'][1]['items'][0]['allowed'])

    def test_unknown_quality_schema_fails_safely(self):
        with self.assertRaises(ValueError):
            profiles.strict_profile({'items': []}, 9, 'German', False)

    def test_rerun_preserves_existing_profiles(self):
        def call(endpoint, data=None):
            self.assertIsNone(data)
            return {'language': [{'name': x, 'id': i} for i, x in enumerate(profiles.LANGUAGES)],
                'customformat/schema': [{'implementation': 'LanguageSpecification'}],
                'qualityprofile/schema': [{}], 'customformat': [],
                'qualityprofile': [{'name': profiles.PREFIX + x} for x in profiles.LANGUAGES]}[endpoint]
        self.assertTrue(all('unchanged' in x for x in profiles.create_profiles(call)))


class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
        cls.services = cls.stack['services']

    def test_downloads_cannot_bypass_vpn_namespace(self):
        q = self.services['qbittorrent']
        self.assertEqual(q['network_mode'], 'service:gluetun')
        self.assertNotIn('networks', q)
        self.assertNotIn('ports', q)
        self.assertEqual(q['depends_on']['gluetun']['condition'], 'service_healthy')
        self.assertEqual(self.services['gluetun']['environment']['FIREWALL'], 'on')

    def test_portal_and_authentication_are_not_published(self):
        for key in ['portal', 'authelia', 'redis']:
            self.assertNotIn('ports', self.services[key])
        self.assertTrue(self.stack['networks']['auth-network']['internal'])

    def test_admin_ports_are_loopback_only(self):
        for name, service in self.services.items():
            if name in {'plex', 'caddy'}:
                continue
            for port in service.get('ports', []):
                self.assertTrue(port.startswith('127.0.0.1:'), (name, port))

    def test_optional_services_are_opt_in(self):
        for name in ['ombi', 'jackett', 'huntarr', 'suggestarr', 'heimdall', 'lidarr', 'flaresolverr']:
            self.assertEqual(self.services[name]['profiles'], ['extras'])

    def test_shared_data_mount_and_least_privilege(self):
        self.assertIn('./content:/data', self.services['qbittorrent']['volumes'])
        self.assertNotIn('privileged', self.services['plex'])


if __name__ == '__main__':
    unittest.main()
