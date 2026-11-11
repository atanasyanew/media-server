"""Generate public dummy credentials for CI config validation, never for use."""
import base64
from pathlib import Path
from test_setup import setup, DIGEST

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    if (ROOT / '.env').exists() or (ROOT / 'provision/authelia/configuration.yml').exists():
        raise SystemExit('Refusing to replace local configuration. Use a clean CI checkout.')
    (ROOT / '.env').write_text('MEDIA_DOMAIN=media.home.arpa\nWIREGUARD_PRIVATE_KEY=' + base64.b64encode(bytes(32)).decode() + '\nWIREGUARD_ADDRESSES=10.14.0.2/16\n')
    setup.generate(ROOT, 'media.home.arpa', 'ci-only', DIGEST, 'ci@example.com')
