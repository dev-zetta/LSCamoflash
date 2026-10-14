"""Recording CGI fixtures open only synthetic temporary directories and MP4 bytes."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'SOURCE/src/contrib/fullhan-recordings/fullhan_recordings.c'
QEMU = shutil.which(os.environ.get('BACKUP_QEMU', os.environ.get('QEMU_ARM', 'qemu-arm')))
ARM_CC = shutil.which(os.environ.get('ARM_CC', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-gcc')))
HOST_CC = shutil.which(os.environ.get('CC', 'cc'))
NAME = '20261014120000-20261014120500.mp4'
DATA = bytes(range(256)) * 300


class RecordingCases:
    arm = False

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='fullhan-recordings-')
        cls.fixture = Path(cls.temporary.name)
        cls.card = cls.fixture / 'card'
        cls.dcim = cls.card / 'DCIM'
        cls.binary = cls.fixture / 'fullhan-recordings'
        compiler = ARM_CC if cls.arm else HOST_CC
        command = [compiler, '-std=c99', '-Os', '-Wall', '-Wextra', '-Werror',
                   '-DFULLHAN_RECORDINGS_FIXTURE_ROOT=' + json.dumps(str(cls.dcim))]
        if cls.arm:
            command += ['-static', '-march=armv5te', '-mtune=arm926ej-s', '-mfloat-abi=soft', '-marm']
        subprocess.run(command + [str(SOURCE), '-o', str(cls.binary)], check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        if self.card.is_symlink():
            self.card.unlink()
        elif self.card.exists():
            shutil.rmtree(self.card)
        self.day = self.dcim / '2026/10/14'
        self.day.mkdir(parents=True)
        (self.day / NAME).write_bytes(DATA)
        self.private = self.fixture / 'private-config'
        self.private.write_bytes(b'PRIVATE-CONFIG-DO-NOT-EXPOSE')

    def call(self, query='', method='GET', byte_range=None, user='fixture-user'):
        env = {'PATH': '/nonexistent', 'REQUEST_METHOD': method, 'QUERY_STRING': query}
        if user is not None:
            env['REMOTE_USER'] = user
        if byte_range is not None:
            env['HTTP_RANGE'] = byte_range
        command = ([QEMU, '-cpu', 'arm1176'] if self.arm else []) + [str(self.binary)]
        result = subprocess.run(command, env=env, capture_output=True, timeout=10)
        headers, body = result.stdout.split(b'\r\n\r\n', 1)
        header = dict(line.decode().split(': ', 1) for line in headers.split(b'\r\n'))
        return result, header, body

    def list_files(self, **extra):
        return self.call(urlencode({'action': 'list', 'day': '2026-10-14', **extra}))

    def download(self, **options):
        return self.call(urlencode({'action': 'download', 'day': '2026-10-14', 'file': NAME}), **options)

    def assert_error(self, response, status):
        result, headers, body = response
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(headers['Status'].startswith(str(status)), response)
        if body:
            self.assertEqual(set(json.loads(body)), {'error'})
        self.assertNotIn(b'PRIVATE-CONFIG', result.stdout)
        self.assertNotIn(str(self.fixture).encode(), result.stdout)

    def test_list_days_and_finalized_files_only(self):
        (self.dcim / 'session.log').write_bytes(b'PRIVATE-CONFIG')
        (self.dcim / '.info').write_bytes(b'PRIVATE-CONFIG')
        (self.day / 'tmp_1234567890123.mp4').write_bytes(DATA)
        (self.day / 'config.mp4').write_bytes(b'PRIVATE-CONFIG')
        (self.day / '20261014130000-20261014130500.mp4').write_bytes(b'')
        (self.dcim / '2026/02/30').mkdir(parents=True)
        result, _, body = self.call()
        self.assertEqual(result.returncode, 0)
        data = json.loads(body)
        self.assertEqual(data['kind'], 'days')
        self.assertEqual(data['days'], [{'name': '2026-10-14'}])
        self.assertIsNone(data['next_offset'])
        result, _, body = self.list_files()
        self.assertEqual(result.returncode, 0)
        data = json.loads(body)
        self.assertEqual(data['kind'], 'files')
        self.assertEqual(data['files'], [{'name': NAME, 'bytes': len(DATA),
                         'download': 'recordings.cgi?action=download&day=2026-10-14&file=' + NAME}])
        self.assertFalse(data['scan_truncated'])

    def test_download_exact_bytes_and_head_without_body(self):
        result, headers, body = self.download()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body, DATA)
        self.assertEqual(headers['Content-Type'], 'video/mp4')
        self.assertEqual(headers['Content-Length'], str(len(DATA)))
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        self.assertIn(NAME, headers['Content-Disposition'])
        result, headers, body = self.download(method='HEAD')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(headers['Content-Length'], str(len(DATA)))
        self.assertEqual(body, b'')
        result, _, body = self.call(method='HEAD')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(body, b'')

    def test_single_ranges_closed_open_suffix_and_clamped_end(self):
        for request, first, last in [('bytes=7-31', 7, 31), ('bytes=70000-', 70000, len(DATA)-1),
                                     ('bytes=-17', len(DATA)-17, len(DATA)-1),
                                     ('bytes=76000-999999', 76000, len(DATA)-1),
                                     ('bytes=-999999', 0, len(DATA)-1)]:
            with self.subTest(request=request):
                result, headers, body = self.download(byte_range=request)
                self.assertEqual(result.returncode, 0)
                self.assertTrue(headers['Status'].startswith('206'))
                self.assertEqual(body, DATA[first:last+1])
                self.assertEqual(headers['Content-Range'], f'bytes {first}-{last}/{len(DATA)}')
                self.assertEqual(int(headers['Content-Length']), len(body))
        result, headers, body = self.download(method='HEAD', byte_range='bytes=10-20')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(headers['Content-Length'], '11')
        self.assertEqual(body, b'')

    def test_bad_ranges_fail_without_recording_bytes(self):
        for value in ('bytes=999999-', 'bytes=9-1', 'bytes=-0', 'bytes=0-1,3-4',
                      'bytes=0--1', 'items=0-1', 'bytes= 0-1', 'bytes=18446744073709551616-', 'x'*129):
            with self.subTest(value=value):
                response = self.download(byte_range=value)
                self.assert_error(response, 416)
                self.assertEqual(response[1]['Content-Range'], 'bytes */' + str(len(DATA)))

    def test_strict_methods_auth_query_parameters_and_decoding(self):
        self.assert_error(self.call(method='POST'), 405)
        self.assert_error(self.call(method='DELETE'), 405)
        self.assert_error(self.call(user=None), 401)
        self.assert_error(self.call(user=''), 401)
        for query in ('delete=all', 'action=delete', 'day=../etc', 'day=2026-02-30',
                      'day=%2e%2e%2fetc', 'day=2026-10-14%00', 'day=2026-10-14%0a',
                      'day=%ZZ', 'day=', 'day=2026-10-14&day=2026-10-13',
                      'limit=101', 'limit=0', 'offset=-1', 'offset=4097',
                      'offset=18446744073709551616', 'file='+NAME, 'action=download',
                      'action=download&day=2026-10-14&file='+NAME+'&limit=1',
                      'action=list&', 'x'*4097):
            with self.subTest(query=query):
                self.assert_error(self.call(query), 400)
        self.assert_error(self.call('action=download&day=2026-10-14&file=%2fetc%2fconf'), 400)

    def test_root_and_intermediate_directory_symlinks_never_followed(self):
        outside = self.fixture / 'outside'
        outside.mkdir(exist_ok=True)
        moved = self.card / 'old-DCIM'
        self.dcim.rename(moved)
        self.dcim.symlink_to(moved, target_is_directory=True)
        self.assert_error(self.call(), 403)
        self.dcim.unlink(); moved.rename(self.dcim)
        moved_card = self.fixture / 'saved-card'
        self.card.rename(moved_card); self.card.symlink_to(moved_card, target_is_directory=True)
        self.assert_error(self.call(), 403)
        self.card.unlink(); moved_card.rename(self.card)
        for component in ('2026', '2026/10', '2026/10/14'):
            path = self.dcim / component
            saved = self.fixture / ('saved-' + component.replace('/', '-'))
            path.rename(saved); path.symlink_to(saved, target_is_directory=True)
            self.assert_error(self.download(), 403)
            result, _, body = self.call()
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(body)['days'], [])
            path.unlink(); saved.rename(path)

    def test_symlink_hardlink_fifo_and_nonrecording_files_are_excluded(self):
        path = self.day / NAME
        path.unlink(); path.symlink_to(self.private)
        self.assert_error(self.download(), 404)
        self.assertEqual(json.loads(self.list_files()[2])['files'], [])
        path.unlink(); os.link(self.private, path)
        self.assert_error(self.download(), 404)
        path.unlink(); os.mkfifo(path)
        self.assert_error(self.download(), 404)
        self.assertEqual(json.loads(self.list_files()[2])['files'], [])
        self.assertEqual(self.private.read_bytes(), b'PRIVATE-CONFIG-DO-NOT-EXPOSE')

    def test_absent_days_and_files_are_safe_errors(self):
        self.assert_error(self.call('day=2025-01-01'), 404)
        (self.day / NAME).unlink()
        self.assert_error(self.download(), 404)

    def test_sorted_pagination_has_at_most_100_and_no_overlap(self):
        start = datetime.datetime(2026, 10, 14, 0, 0)
        names = []
        for i in range(125):
            a = start + datetime.timedelta(minutes=i)
            b = a + datetime.timedelta(seconds=30)
            name = a.strftime('%Y%m%d%H%M%S') + '-' + b.strftime('%Y%m%d%H%M%S') + '.mp4'
            (self.day / name).write_bytes(b'fixture mp4')
            names.append(name)
        names.append(NAME)
        first = json.loads(self.list_files()[2])
        second = json.loads(self.list_files(offset=first['next_offset'])[2])
        self.assertEqual(len(first['files']), 100)
        self.assertEqual(first['next_offset'], 100)
        self.assertIsNone(second['next_offset'])
        self.assertEqual([f['name'] for f in first['files'] + second['files']], sorted(names, reverse=True))
        self.assertEqual(json.loads(self.list_files(offset=4096)[2])['files'], [])

    def test_global_scan_budget_reports_truncation(self):
        for i in range(8200):
            (self.dcim / ('ignored-' + str(i))).touch()
        result, _, body = self.call()
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(body)['scan_truncated'])
        self.assertLessEqual(len(body), 16384)

    def test_file_inventory_count_cap_is_explicit(self):
        start = datetime.datetime(2026, 10, 14)
        for i in range(4097):
            a = start + datetime.timedelta(seconds=i)
            b = a + datetime.timedelta(seconds=1)
            name = a.strftime('%Y%m%d%H%M%S') + '-' + b.strftime('%Y%m%d%H%M%S') + '.mp4'
            (self.day / name).write_bytes(b'mp4')
        result, _, body = self.list_files(offset=4000)
        self.assertEqual(result.returncode, 0)
        data = json.loads(body)
        self.assertEqual(len(data['files']), 96)
        self.assertTrue(data['scan_truncated'])
        self.assertIsNone(data['next_offset'])
        self.assertEqual(json.loads(self.list_files(offset=4096)[2])['files'], [])

    def test_day_inventory_count_cap_is_explicit(self):
        start = datetime.date(2023, 1, 1)
        for i in range(1025):
            day = start + datetime.timedelta(days=i)
            (self.dcim / day.strftime('%Y/%m/%d')).mkdir(parents=True, exist_ok=True)
        result, _, body = self.call('offset=1000')
        self.assertEqual(result.returncode, 0)
        data = json.loads(body)
        self.assertEqual(len(data['days']), 24)
        self.assertTrue(data['scan_truncated'])
        self.assertIsNone(data['next_offset'])


@unittest.skipUnless(HOST_CC, 'Host C compiler required')
class HostRecordingTests(RecordingCases, unittest.TestCase):
    pass


@unittest.skipUnless(QEMU and ARM_CC, 'ARM compiler and qemu-arm required')
class ArmRecordingTests(RecordingCases, unittest.TestCase):
    arm = True


if __name__ == '__main__':
    unittest.main()
