"""HTTP checks for the static landing and the Compose nginx front door.

Run: python -m unittest scripts.test_robots -v (requires Docker and nginx:alpine).
"""
import contextlib
import functools
import http.client
import http.server
import json
import os
import pathlib
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
# The tag docker-compose.yaml pins; add_header_inherit needs 1.29.3 or newer.
NGINX_IMAGE = 'nginx:1.29.6-alpine'
POLICY = 'User-agent: *\nDisallow: /\n'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url, timeout=30):
    """(status, headers, body) for any status, redirects not followed, certificate not verified."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))
    try:
        with opener.open(url, timeout=timeout) as response:
            return response.status, response.headers, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read().decode()


@contextlib.contextmanager
def nginx(mounts, ports=(80,)):
    """A throwaway nginx on loopback ports; yields {container_port: 'host:port'}."""
    args = ['docker', 'run', '-d']
    for port in ports:
        args += ['-p', f'127.0.0.1::{port}']
    for source, target in mounts:
        args += ['-v', f'{source}:{target}:ro']
    container = subprocess.run(args + [NGINX_IMAGE], capture_output=True, text=True, check=True).stdout.strip()
    try:
        addresses = {}
        for port in ports:
            line = subprocess.run(['docker', 'port', container, f'{port}/tcp'], capture_output=True, text=True,
                check=True).stdout.strip().splitlines()[0]
            addresses[port] = line
        wait_for_nginx(container, addresses[ports[0]])
        yield addresses
    finally:
        subprocess.run(['docker', 'rm', '-f', container], capture_output=True, check=False)


def wait_for_nginx(container, address, seconds=15):
    deadline = time.monotonic() + seconds
    while True:
        try:
            fetch(f'http://{address}/robots.txt')
            return
        except (urllib.error.URLError, ConnectionResetError, http.client.RemoteDisconnected):
            running = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', container],
                capture_output=True, text=True).stdout.strip()
            if running != 'true':
                logs = subprocess.run(['docker', 'logs', container], capture_output=True, text=True)
                raise AssertionError(f'nginx container exited before serving:\n{logs.stdout}{logs.stderr}')
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.headers.get_content_type(), response.read().decode()


def get_when_ready(url, container, seconds=10):
    deadline = time.monotonic() + seconds
    while True:
        try:
            return get(url)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionResetError, http.client.RemoteDisconnected):
            running = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', container],
                capture_output=True, text=True).stdout.strip()
            if running != 'true':
                logs = subprocess.run(['docker', 'logs', container], capture_output=True, text=True)
                raise AssertionError(f'nginx container exited before serving:\n{logs.stdout}{logs.stderr}')
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


class GetWhenReadyTest(unittest.TestCase):
    def test_http_error_response_fails_fast_instead_of_retrying(self):
        class NotFound(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_error(404)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), NotFound)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            started = time.monotonic()
            with self.assertRaises(urllib.error.HTTPError) as caught:
                get_when_ready(f'http://127.0.0.1:{server.server_port}/robots.txt', 'no-such-container')
            self.assertEqual(caught.exception.code, 404)
            self.assertLess(time.monotonic() - started, 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class RobotsTest(unittest.TestCase):
    def test_landing_robots_is_served_as_text_and_allows_crawling(self):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / 'front_end/landing'))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, content_type, body = get(f'http://127.0.0.1:{server.server_port}/robots.txt')
            self.assertEqual((status, content_type), (200, 'text/plain'))
            self.assertIn('User-agent: *', body)
            self.assertIn('Allow: /', body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_compose_front_door_serves_disallow_policy(self):
        result = subprocess.run(['docker', 'run', '-d', '-p', '127.0.0.1::80',
            '-v', f'{ROOT}/nginx.conf:/etc/nginx/nginx.conf:ro',
            '-v', f'{ROOT}/nginx-harvis.conf:/etc/nginx/harvis.conf:ro',
            NGINX_IMAGE], capture_output=True, text=True, check=True)
        container = result.stdout.strip()
        try:
            address = subprocess.run(['docker', 'port', container, '80/tcp'], capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]
            status, content_type, body = get_when_ready(f'http://{address}/robots.txt', container)
            self.assertEqual((status, content_type), (200, 'text/plain'))
            self.assertEqual(body, 'User-agent: *\nDisallow: /\n')
        finally:
            subprocess.run(['docker', 'rm', '-f', container], capture_output=True, check=False)


BASE_MOUNTS = [(ROOT / 'nginx.conf', '/etc/nginx/nginx.conf'), (ROOT / 'nginx-harvis.conf', '/etc/nginx/harvis.conf')]
# Every response gets these, on every listener, whichever location answers.
HARDENING = {
    'X-Robots-Tag': 'noindex, nofollow',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'SAMEORIGIN',
    'Content-Security-Policy': "frame-ancestors 'self'; object-src 'none'; base-uri 'self'",
}


def static_site(tmp):
    site = pathlib.Path(tmp) / 'hermes'
    (site / 'assets').mkdir(parents=True)
    (site / 'index.html').write_text('<!doctype html><title>x</title>')
    (site / 'assets' / 'a.js').write_text('1')
    return site


class FrontDoorHeadersTest(unittest.TestCase):
    def assert_hardened(self, headers, path):
        for name, value in HARDENING.items():
            self.assertEqual(headers.get(name), value, f'{name} on {path}')

    def test_every_response_carries_the_headers_even_where_a_location_sets_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = static_site(tmp)
            with nginx(BASE_MOUNTS + [(site, '/usr/share/nginx/hermes')]) as address:
                host = address[80]
                # /harvis/ and /harvis/assets/ set Cache-Control themselves; /audio/ is a bare 404.
                for path, cache in (('/harvis/', 'no-cache'), ('/harvis/assets/a.js', 'public, immutable'), ('/audio/x.wav', None),
                                    ('/favicon.ico', None)):
                    status, headers, _ = fetch(f'http://{host}{path}')
                    self.assert_hardened(headers, path)
                    if cache:
                        self.assertEqual(status, 200, path)
                        # `expires` adds its own max-age to the same header.
                        self.assertIn(cache, ', '.join(headers.get_all('Cache-Control') or []), path)

    def test_sandbox_app_keeps_only_the_crawler_header_so_its_own_sandbox_policy_stands(self):
        # Read from the config nginx actually loads rather than over HTTP: the location proxies to
        # a backend that is not in this test, and nginx waits 30 s on the missing DNS first.
        args = ['docker', 'run', '--rm']
        for source, target in BASE_MOUNTS:
            args += ['-v', f'{source}:{target}:ro']
        dump = subprocess.run(args + [NGINX_IMAGE, 'nginx', '-T'], capture_output=True, text=True, check=True).stdout
        block = dump.split('location /hermes-api/sandbox-app/ {', 1)[1].split('proxy_pass', 1)[0]
        self.assertIn('add_header_inherit off;', block)
        self.assertEqual([line.strip() for line in block.splitlines() if 'add_header ' in line],
                         ['add_header X-Robots-Tag "noindex, nofollow" always;'])

    def test_robots_policy_and_header_on_the_http_door_and_the_tunnel_entrance(self):
        with nginx(BASE_MOUNTS, ports=(80, 8081)) as address:
            for port in (80, 8081):
                status, headers, body = fetch(f'http://{address[port]}/robots.txt')
                self.assertEqual((status, body), (200, POLICY), port)
                self.assertEqual(headers.get_content_type(), 'text/plain', port)
                self.assert_hardened(headers, f'robots :{port}')
            # The tunnel entrance refuses everything else without an Access token.
            status, headers, _ = fetch(f'http://{address[8081]}/')
            self.assertNotEqual(status, 200)
            self.assert_hardened(headers, 'tunnel /')

    def test_prebuilt_compose_nginx_mounts_the_same_config_and_pins_the_same_image(self):
        env = {'PATH': os.environ['PATH'], 'HOME': tempfile.gettempdir(), 'JWT_SECRET': 'a', 'POSTGRES_PASSWORD': 'b',
               'HARVIS_GATEWAY_TOKEN': 'c'}
        result = subprocess.run(['docker', 'compose', '--env-file', '/dev/null', '-f', str(ROOT / 'docker-compose.prebuilt.yml'),
            'config', '--format', 'json'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        service = json.loads(result.stdout)['services']['nginx']
        targets = {v['target']: pathlib.Path(v['source']) for v in service['volumes']}
        self.assertEqual(targets.get('/etc/nginx/nginx.conf'), ROOT / 'nginx.conf')
        self.assertEqual(targets.get('/etc/nginx/harvis.conf'), ROOT / 'nginx-harvis.conf')
        self.assertNotIn('/tmp', targets)
        self.assertTrue(service['image'].startswith(NGINX_IMAGE), service['image'])
        # ... so the stock-config run above is what that stack serves.


class HttpsLaneTest(unittest.TestCase):
    """What ./scripts/enable-https.sh leaves behind: a listener, a certificate and a redirect file."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which('openssl'):
            raise unittest.SkipTest('openssl is needed to make a throwaway certificate')
        cls.tmp = tempfile.mkdtemp()
        tls = pathlib.Path(cls.tmp) / 'tls'
        tls.mkdir()
        subprocess.run(['openssl', 'req', '-x509', '-nodes', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1',
            '-days', '1', '-subj', '/CN=test', '-keyout', str(tls / 'harvis.key'), '-out', str(tls / 'harvis.crt')],
            capture_output=True, check=True)
        shutil.copy(ROOT / 'nginx/tls/harvis-tls.conf.template', tls / 'harvis-tls.conf')
        (tls / 'harvis-https.redirect').write_text('set $harvis_https_base "https://$host:9443";\n')
        cls.tls = tls

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_plain_lane_redirects_but_keeps_robots_and_the_installers_probes(self):
        with nginx(BASE_MOUNTS + [(self.tls, '/etc/nginx/tls')], ports=(80, 443)) as address:
            status, headers, _ = fetch(f'http://{address[80]}/harvis/?x=1')
            self.assertEqual(status, 301)
            host = address[80].split(':')[0]
            self.assertEqual(headers.get('Location'), f'https://{host}:9443/harvis/?x=1')
            self.assertIsNone(headers.get('Strict-Transport-Security'))
            self.assertEqual(headers.get('X-Robots-Tag'), 'noindex, nofollow')
            status, _, body = fetch(f'http://{address[80]}/robots.txt')
            self.assertEqual((status, body), (200, POLICY))
            for probe in ('/api/health/services', '/api/setup/status'):
                # Not redirected means it went on to the proxy, which has no backend to answer
                # here: a 301 comes back at once, so a stall is the pass.
                try:
                    self.assertNotEqual(fetch(f'http://{address[80]}{probe}', timeout=3)[0], 301, probe)
                except (TimeoutError, urllib.error.URLError):
                    pass

    def test_https_lane_sends_hsts_and_the_same_headers(self):
        with nginx(BASE_MOUNTS + [(self.tls, '/etc/nginx/tls')], ports=(80, 443)) as address:
            status, headers, body = fetch(f'https://{address[443]}/robots.txt')
            self.assertEqual((status, body), (200, POLICY))
            self.assertRegex(headers.get('Strict-Transport-Security', ''), r'^max-age=\d{7,}$')
            for name, value in HARDENING.items():
                self.assertEqual(headers.get(name), value, name)
            status, headers, _ = fetch(f'https://{address[443]}/audio/x.wav')
            self.assertEqual(status, 404)
            self.assertIn('max-age=', headers.get('Strict-Transport-Security', ''))

    def test_without_the_redirect_file_plain_http_serves_the_app_as_before(self):
        bare = pathlib.Path(self.tmp) / 'bare'
        bare.mkdir(exist_ok=True)
        with nginx(BASE_MOUNTS + [(bare, '/etc/nginx/tls')]) as address:
            status, _, _ = fetch(f'http://{address[80]}/audio/x.wav')
            self.assertEqual(status, 404)
            self.assertNotEqual(fetch(f'http://{address[80]}/favicon.ico')[0], 301)
            self.assertNotIn('Strict-Transport-Security', fetch(f'http://{address[80]}/robots.txt')[1])


if __name__ == '__main__':
    unittest.main()
