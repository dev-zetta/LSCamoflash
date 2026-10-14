"""Real authenticated HTTP/CGI Range fixtures on loopback only; no camera access."""
import base64
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
CANDIDATE = Path(os.environ.get('FULLHAN_RANGE_BUSYBOX', str(REPO / 'SOURCE/fullhan-busybox/bin/busybox')))
QEMU = shutil.which(os.environ.get('BACKUP_QEMU', os.environ.get('QEMU_ARM', 'qemu-arm')))
NAME = '20261014120000-20261014120500.mp4'
DATA = bytes(range(256)) * 256


@unittest.skipUnless(CANDIDATE.is_file() and shutil.which('cc') and shutil.which('openssl'),
                     'Build the isolated Fullhan BusyBox and provide host cc/OpenSSL')
class FullhanBusyBoxRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='fullhan-http-range-')
        cls.root = Path(cls.temporary.name)
        cls.server = None
        cls.addClassCleanup(cls.cleanup)
        elf = CANDIDATE.read_bytes()[:20]
        arm = elf[:4] == b'\x7fELF' and len(elf) >= 20 and int.from_bytes(elf[18:20], 'little') == 40
        if arm and not QEMU:
            raise unittest.SkipTest('qemu-arm required for the isolated ARM BusyBox')
        cls.command = ([QEMU, '-cpu', 'arm1176'] if arm else []) + [str(CANDIDATE)]
        cls.dcim = cls.root / 'DCIM'
        day = cls.dcim / '2026/10/14'
        day.mkdir(parents=True)
        (day / NAME).write_bytes(DATA)
        www = cls.root / 'www'
        (www / 'cgi-bin').mkdir(parents=True)
        (www / 'index.html').write_text('synthetic read-only fixture\n')
        (www / 'static.bin').write_bytes(DATA)
        helper = cls.root / 'recordings-helper'
        subprocess.run(['cc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-DFULLHAN_RECORDINGS_FIXTURE_ROOT='+json.dumps(str(cls.dcim)),
                        str(REPO / 'SOURCE/src/contrib/fullhan-recordings/fullhan_recordings.c'),
                        '-o', str(helper)], check=True, capture_output=True, timeout=30)
        cgi = www / 'cgi-bin/recordings.cgi'
        cgi.write_text('#!/bin/sh\nexec "'+str(helper)+'"\n')
        cgi.chmod(0o755)
        hashed = subprocess.run(['openssl', 'passwd', '-1', '-stdin'], input=b'fixture-range-password\n',
                                check=True, capture_output=True).stdout.decode().strip()
        config = cls.root / 'httpd.conf'
        config.write_text('I:index.html\n/:fixture:'+hashed+'\n')
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                cls.port = sock.getsockname()[1]
        except PermissionError:
            raise unittest.SkipTest('Loopback socket permission required') from None
        cls.server = subprocess.Popen([*cls.command, 'httpd', '-f', '-p', '127.0.0.1:'+str(cls.port),
                                       '-h', str(www), '-c', str(config)], stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise AssertionError('Isolated BusyBox HTTP server failed to start')
            try:
                status, _, _ = cls.request('/cgi-bin/recordings.cgi', authenticate=False)
                if status == 401:
                    break
            except OSError:
                pass
            time.sleep(0.02)
        else:
            raise AssertionError('Isolated BusyBox HTTP server did not become ready')

    @classmethod
    def cleanup(cls):
        if cls.server and cls.server.poll() is None:
            os.killpg(cls.server.pid, signal.SIGTERM)
            try:
                cls.server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(cls.server.pid, signal.SIGKILL)
                cls.server.wait(timeout=3)
        cls.temporary.cleanup()

    @classmethod
    def request(cls, path, method='GET', byte_range=None, authenticate=True):
        headers = {}
        if authenticate:
            headers['Authorization'] = 'Basic '+base64.b64encode(b'fixture:fixture-range-password').decode()
        if byte_range is not None:
            headers['Range'] = byte_range
        connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=5)
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def download(self, **options):
        return self.request('/cgi-bin/recordings.cgi?action=download&day=2026-10-14&file='+NAME, **options)

    def test_cgi_closed_range_is_forwarded_and_returns_only_requested_bytes(self):
        status, headers, body = self.download(byte_range='bytes=0-31')
        self.assertEqual(status, 206)
        self.assertEqual(headers['Content-Range'], 'bytes 0-31/'+str(len(DATA)))
        self.assertEqual(headers['Content-Length'], '32')
        self.assertEqual(body, DATA[:32])

    def test_cgi_suffix_and_open_ranges_preserve_original_header(self):
        for value, expected in (('bytes=-17', DATA[-17:]), ('bytes=65500-', DATA[65500:])):
            with self.subTest(value=value):
                status, headers, body = self.download(byte_range=value)
                self.assertEqual(status, 206)
                self.assertEqual(int(headers['Content-Length']), len(expected))
                self.assertEqual(body, expected)

    def test_invalid_and_multiple_ranges_reach_helper_and_return_416(self):
        for value in ('bytes=999999-', 'bytes=0-1,3-4', 'bytes=-0', 'bytes=3-1'):
            with self.subTest(value=value):
                status, headers, body = self.download(byte_range=value)
                self.assertEqual(status, 416)
                self.assertEqual(headers['Content-Range'], 'bytes */'+str(len(DATA)))
                self.assertEqual(set(json.loads(body)), {'error'})

    def test_head_range_preserves_headers_and_has_no_body(self):
        status, headers, body = self.download(method='HEAD', byte_range='bytes=2-8')
        self.assertEqual(status, 206)
        self.assertEqual(headers['Content-Length'], '7')
        self.assertEqual(body, b'')

    def test_authentication_is_preserved_for_range_requests(self):
        status, _, body = self.download(byte_range='bytes=0-31', authenticate=False)
        self.assertEqual(status, 401)
        self.assertNotEqual(body, DATA[:32])

    def test_static_file_range_behavior_is_unchanged(self):
        status, headers, body = self.request('/static.bin', byte_range='bytes=0-31')
        self.assertEqual(status, 206)
        self.assertEqual(headers['Content-Length'], '32')
        self.assertEqual(body, DATA[:32])

    def test_no_range_returns_complete_recording_and_listing_stays_json(self):
        status, headers, body = self.download()
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Length'], str(len(DATA)))
        self.assertEqual(body, DATA)
        status, _, body = self.request('/cgi-bin/recordings.cgi', byte_range='bytes=0-31')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['kind'], 'days')


if __name__ == '__main__':
    unittest.main()
