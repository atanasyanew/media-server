"""Loopback-only browser-test fixture. Never used by the deployment image."""
import os
from copy import deepcopy
from xml.etree import ElementTree as ET
from test_portal import app

VIDEOS = {
    '1': ET.fromstring('''<Video><Media id="101" videoResolution="1080"><Part id="201">
      <Stream id="301" streamType="2" languageCode="deu" selected="1"/>
      <Stream id="302" streamType="2" languageCode="eng"/>
      <Stream id="303" streamType="3" languageCode="eng"/>
      <Stream id="304" streamType="3" languageCode="deu"/>
      </Part></Media></Video>'''),
    '2': ET.fromstring('''<Video><Media id="102" videoResolution="1080"><Part id="202">
      <Stream id="305" streamType="2" languageCode="jpn" selected="1"/>
      <Stream id="306" streamType="3" languageCode="eng" selected="1"/>
      </Part></Media></Video>'''),
    '3': ET.fromstring('''<Video><Media id="103" videoResolution="720"><Part id="203">
      <Stream id="307" streamType="2"/>
      </Part></Media></Video>'''),
}
RealPlex = app.Plex


class FixturePlex(RealPlex):
    def libraries(self):
        return [{'id': '1', 'title': 'Demo movies', 'type': 'movie'}]

    def items(self, section, start, search):
        items = [{'id': '1', 'title': 'Across the mountains', 'year': '2024'},
                 {'id': '2', 'title': 'A summer in Kyoto', 'year': '2025'},
                 {'id': '3', 'title': 'Family archive', 'year': '2020'}]
        items = [x for x in items if search.lower() in x['title'].lower()]
        return {'items': items[start:start + 50], 'start': start, 'total': len(items)}

    def metadata(self, item):
        return deepcopy(VIDEOS[item])

    def request(self, path, params=None, method='GET'):
        if path == '/':
            return ET.fromstring('<MediaContainer machineIdentifier="demo"/>')
        part_id = path.rsplit('/', 1)[1]
        for video in VIDEOS.values():
            for part in video.findall('Media/Part'):
                if part.get('id') == part_id:
                    for stream in part.findall('Stream'):
                        chosen = params['audioStreamID'] if stream.get('streamType') == '2' else params['subtitleStreamID']
                        stream.set('selected', '1' if stream.get('id') == chosen else '0')
                    return ET.Element('MediaContainer')
        raise ValueError('Invalid demo part')


class FixtureHandler(app.Handler):
    def handle_request(self, write):
        self.headers['Remote-User'] = 'browser-test'
        return super().handle_request(write)


if __name__ == '__main__':
    app.Plex = FixturePlex
    os.environ['PORTAL_ORIGIN'] = 'http://127.0.0.1:8099'
    os.environ['MEDIA_DOMAIN'] = 'media.home.arpa'
    app.ThreadingHTTPServer(('127.0.0.1', 8099), FixtureHandler).serve_forever()
