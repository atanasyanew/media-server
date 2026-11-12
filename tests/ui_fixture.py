"""Loopback-only browser-test fixture. Never used by the deployment image."""
import os
from copy import deepcopy
from test_portal import app

ID = {n: str(n) * 32 for n in range(1, 4)}


def video(item, *streams):
    return {'Id': ID[item], 'Type': 'Movie', 'MediaSources': [{'Id': ID[item], 'MediaStreams': [
        {'Type': 'Video', 'Height': 1080}, *({'Type': t, 'Language': lang} for t, lang in streams)]}]}


VIDEOS = {
    ID[1]: video(1, ('Audio', 'ger'), ('Audio', 'eng'), ('Subtitle', 'eng'), ('Subtitle', 'ger')),
    ID[2]: video(2, ('Audio', 'jpn'), ('Subtitle', 'eng')),
    ID[3]: video(3, ('Audio', None)),
}
RealJellyfin = app.Jellyfin


class FixtureJellyfin(RealJellyfin):
    config = {}

    def libraries(self):
        return [{'id': 'a' * 32, 'title': 'Demo movies', 'type': 'movies'}]

    def items(self, section, start, search):
        items = [{'id': ID[1], 'title': 'Across the mountains', 'year': '2024'},
                 {'id': ID[2], 'title': 'A summer in Kyoto', 'year': '2025'},
                 {'id': ID[3], 'title': 'Family archive', 'year': '2020'}]
        items = [x for x in items if search.lower() in x['title'].lower()]
        return {'items': items[start:start + 50], 'start': start, 'total': len(items)}

    def metadata(self, item):
        return deepcopy(VIDEOS[item])

    def user(self):
        return 'b' * 32

    def request(self, path, params=None, body=None):
        if body is not None:
            FixtureJellyfin.config = body
        return {'Configuration': FixtureJellyfin.config}


class FixtureHandler(app.Handler):
    def handle_request(self, write):
        self.headers['Remote-User'] = 'browser-test'
        return super().handle_request(write)


if __name__ == '__main__':
    app.Jellyfin = FixtureJellyfin
    os.environ['PORTAL_ORIGIN'] = 'http://127.0.0.1:8099'
    os.environ['MEDIA_DOMAIN'] = 'media.home.arpa'
    app.ThreadingHTTPServer(('127.0.0.1', 8099), FixtureHandler).serve_forever()
