"""Isolated Fullhan pilot fixtures; no camera, real mounts or vendor programs."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tarfile
import tempfile
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'SOURCE/src/fullhan'
SPEC = importlib.util.spec_from_file_location('fullhan_builder', ROOT / 'tools/fullhan/build-kit.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


def start_time(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@unittest.skipUnless(shutil.which('busybox') and shutil.which('openssl'), 'Host BusyBox and OpenSSL required')
class FullhanRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fullhan-runtime-')
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Path(self.temporary.name)
        self.card = self.fixture / 'card'
        self.card.mkdir()
        self.kit = self.card / 'LSCamoflash-fullhan'
        shutil.copytree(SOURCE, self.kit, ignore=shutil.ignore_patterns('*.patch'))
        (self.kit / 'bin').mkdir()
        shutil.copyfile(shutil.which('busybox'), self.kit / 'bin/busybox')
        (self.kit / 'bin/busybox').chmod(0o755)
        self.bb = str(self.kit / 'bin/busybox')
        for helper in ('fullhan-recordings','fullhan-discovery'):
            (self.kit / 'bin' / helper).write_text('#!/bin/sh\nexit 1\n')
            (self.kit / 'bin' / helper).chmod(0o755)
        self.state = self.fixture / 'state'
        self.device = self.fixture / 'mmcblk0p1'
        self.device.touch()
        self.stock = self.fixture / 'dgiot'
        self.stock.write_bytes(b'synthetic identity, never executed\n')
        self.cpu = self.fixture / 'cpuinfo'
        self.cpu.write_text('Processor : ARMv6-compatible\nHardware : FH8626V100\nSerial : PRIVATE-ID\n')
        self.mounts = self.fixture / 'mounts'
        self.mounts.write_text(self.mount_row())
        self.magic = self.fixture / 'magic'
        self.magic.write_text('4d44\n')
        self.visible = self.fixture / 'visible'
        self.visible.write_text(str(179 * 256 + 1) + '\n')
        self.pair = self.fixture / 'pair'
        self.pair.write_text('b3:1\n')
        self.memory = self.fixture / 'meminfo'
        self.memory.write_text('MemTotal: 65536 kB\nMemFree: 4096 kB\nMemAvailable: 20000 kB\nCached: 10000 kB\nPrivatePassword: DO-NOT-LEAK\n')
        self.uptime = self.fixture / 'uptime'
        self.uptime.write_text('123.75 99.00\n')
        self.loadavg = self.fixture / 'loadavg'
        self.loadavg.write_text('1.25 0.50 0.10 1/10 123\n')
        self.ip = self.fixture / 'ip-addresses'
        self.ip.write_text('2: wlan0: <UP>\n    inet 192.0.2.44/24 scope global wlan0\n')
        try:
            self.port = free_port()
            self.network_allowed = True
        except PermissionError:
            self.port = 49151
            self.network_allowed = False
        for path in (self.kit / 'start.sh', self.kit / 'stop.sh', self.kit / 'common.sh', self.kit / 'www/cgi-bin/status.cgi'):
            text = path.read_text().replace('/mnt', str(self.card))
            if path.name == 'common.sh':
                substitutions = {
                    'root_user() { [ "$("$BB" id -u)" = 0 ]; }': 'root_user() { return 0; }',
                    'STATE="/tmp/lscamoflash-fullhan"': f'STATE="{self.state}"',
                    'CPUINFO="/proc/cpuinfo"': f'CPUINFO="{self.cpu}"',
                    'MOUNTS="/proc/mounts"': f'MOUNTS="{self.mounts}"',
                    'MEMINFO="/proc/meminfo"': f'MEMINFO="{self.memory}"',
                    'UPTIME="/proc/uptime"': f'UPTIME="{self.uptime}"',
                    'LOADAVG="/proc/loadavg"': f'LOADAVG="{self.loadavg}"',
                    'STOCK="/usr/bin/dgiot"': f'STOCK="{self.stock}"',
                    BUILD.REPO.joinpath('SOURCE/src/fullhan/common.sh').read_text().split('STOCK_SHA="')[1].split('"')[0]: hashlib.sha256(self.stock.read_bytes()).hexdigest(),
                    'PORT="8080"': f'PORT="{self.port}"',
                    'HTTP_BIND="$PORT"': 'HTTP_BIND="127.0.0.1:$PORT"',
                    '$("$BB" stat -f -c %t "$CARD_MOUNT")': f'$(cat "{self.magic}")',
                    '$("$BB" stat -c %d "$CARD_MOUNT")': f'$(cat "{self.visible}")',
                    '[ "$device" = /dev/mmcblk0p1 ] && [ -b "$device" ]': f'[ "$device" = "{self.device}" ] && [ -f "$device" ]',
                    '$("$BB" stat -c %t:%T "$device")': f'$(cat "{self.pair}")',
                    '"$BB" ip -4 addr show 2>/dev/null': f'cat "{self.ip}"',
                }
                for old, new in substitutions.items():
                    self.assertIn(old, text)
                    text = text.replace(old, new)
            path.write_text(text)
        self.auth = self.kit / 'httpd.conf'
        hashed = subprocess.run(['openssl', 'passwd', '-1', '-stdin'], input=b'fixture-private-password\n',
                                capture_output=True, check=True).stdout.decode().strip()
        self.auth.write_text('I:index.html\n/:admin:' + hashed + '\n')
        (self.kit / 'LICENSE.MIT').write_text('MIT fixture\n')
        (self.kit / 'COPYING.BusyBox').write_text('GPLv2 fixture\n')
        (self.kit / 'manifest.json').write_text('{"format":"fixture"}\n')
        self.checksums()
        self.addCleanup(self.cleanup_server)

    def mount_row(self, options='rw', source=None, kind='vfat'):
        return f'{source or self.device} {self.card} {kind} {options},relatime 0 0\n'

    def checksums(self):
        names = (*BUILD.FILES, 'bin/busybox', 'bin/fullhan-recordings', 'bin/fullhan-discovery', 'LICENSE.MIT', 'COPYING.BusyBox', 'manifest.json')
        (self.kit / 'SHA256SUMS').write_text(''.join(
            hashlib.sha256((self.kit / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in names))

    def run_script(self, name):
        return subprocess.run([self.bb, 'sh', str(self.kit / name)], capture_output=True, text=True, timeout=9)

    def cleanup_server(self):
        if (self.state / 'pid').is_file():
            self.run_script('stop.sh')

    def cgi(self, host='camera.local:8080', method='GET'):
        env = dict(os.environ, REQUEST_METHOD=method, HTTP_HOST=host)
        return subprocess.run([self.bb, 'sh', str(self.kit / 'www/cgi-bin/status.cgi')],
                              env=env, capture_output=True, text=True, timeout=3)

    def body(self, result):
        return json.loads(result.stdout.split('\n\n', 1)[1])

    def test_hardware_binary_auth_and_payload_fail_closed_before_state(self):
        self.cpu.write_text('Hardware : ANYKA\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.cpu.write_text('Hardware : FH8626V100\n')
        self.stock.write_bytes(b'wrong application identity\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.stock.write_bytes(b'synthetic identity, never executed\n')
        self.auth.unlink()
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.auth.write_text('I:index.html\n/:admin:plaintext-is-not-accepted\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertFalse(self.state.exists())
        self.assertFalse((self.kit / 'startup.log').exists())

    def test_mount_guard_covered_tmpfs_readonly_duplicates_and_wrong_visible_device(self):
        for content, magic, visible in (
                (self.mount_row('ro'), '4d44', 45825),
                (self.mount_row() * 2, '4d44', 45825),
                (self.mount_row() + self.mount_row('ro'), '4d44', 45825),
                (self.mount_row(kind='ext4'), 'ef53', 45825),
                (self.mount_row(source='/dev/unrelated'), '4d44', 45825),
                (self.mount_row(), '4d44', 45826)):
            with self.subTest(content=content):
                self.mounts.write_text(content)
                self.magic.write_text(magic)
                self.visible.write_text(str(visible))
                self.assertNotEqual(self.run_script('start.sh').returncode, 0)
                self.assertFalse(self.state.exists())
        self.magic.write_text('4d44')
        self.visible.write_text('45825')
        self.mounts.write_text(f'tmpfs {self.card} tmpfs rw 0 0\n' + self.mount_row())
        if self.network_allowed:
            self.assertEqual(self.run_script('start.sh').returncode, 0)
            self.assertEqual(self.run_script('stop.sh').returncode, 0)
        else:
            result = subprocess.run([self.bb, 'sh', '-c', '. "$1"; trusted_mount', 'fixture', str(self.kit / 'common.sh')],
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_authenticated_http_status_and_owned_stop_leave_other_process_alive(self):
        if not self.network_allowed:
            self.skipTest('Loopback sockets unavailable in this sandbox')
        other = subprocess.Popen([self.bb, 'sleep', '30'])
        self.addCleanup(other.wait)
        self.addCleanup(lambda: other.poll() is None and other.terminate())
        result = self.run_script('start.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(f'http://127.0.0.1:{self.port}/', timeout=3)
        self.assertEqual(denied.exception.code, 401)
        denied.exception.close()
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/cgi-bin/status.cgi')
        request.add_header('Authorization', 'Basic ' + base64.b64encode(b'admin:fixture-private-password').decode())
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.load(response)
        self.assertEqual(data['streams']['main'], 'rtsp://192.0.2.44:8554/main')
        self.assertEqual(data['streams']['sub'], 'rtsp://192.0.2.44:8554/sub')
        self.assertFalse(data['stock_app_managed'])
        original_pid = (self.state / 'pid').read_text()
        pid, stamp = original_pid.split()
        (self.state / 'pid').write_text(f'{pid} {int(stamp)+1}\n')
        self.assertNotEqual(self.run_script('stop.sh').returncode, 0)
        self.assertTrue(Path(f'/proc/{pid}').exists())
        (self.state / 'pid').write_text(original_pid)
        self.assertEqual(self.run_script('stop.sh').returncode, 0)
        self.assertIsNone(other.poll())
        self.assertFalse(self.state.exists())
        other.terminate()
        other.wait(timeout=3)

    def test_stale_or_unrelated_pid_is_not_signalled(self):
        other = subprocess.Popen([self.bb, 'sleep', '30'])
        try:
            self.state.mkdir()
            (self.state / 'pid').write_text(f'{other.pid} {start_time(other.pid)}\n')
            result = self.run_script('stop.sh')
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(other.poll())
            self.assertTrue((self.state / 'pid').exists())
        finally:
            other.terminate()
            other.wait(timeout=3)
            (self.state / 'pid').unlink()
            self.state.rmdir()

    def test_existing_state_symlink_log_and_unknown_document_root_file_are_preserved(self):
        self.state.mkdir()
        sentinel = self.state / 'sentinel'
        sentinel.write_bytes(b'leave existing service state\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertEqual(sentinel.read_bytes(), b'leave existing service state\n')
        sentinel.unlink(); self.state.rmdir()
        outside = self.fixture / 'outside'
        outside.write_bytes(b'do not truncate\n')
        (self.kit / 'startup.log').symlink_to(outside)
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertEqual(outside.read_bytes(), b'do not truncate\n')
        (self.kit / 'startup.log').unlink()
        (self.kit / 'www/private.db').write_bytes(b'not public\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertFalse(self.state.exists())

    def test_root_requirement_auth_overrides_and_payload_tamper_refuse(self):
        common = self.kit / 'common.sh'
        original = common.read_text()
        common.write_text(original.replace('root_user() { return 0; }', 'root_user() { return 1; }'))
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertFalse(self.state.exists())
        common.write_text(original)
        self.auth.write_text(self.auth.read_text() + '*.cgi:/bin/sh\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.auth.write_text(self.auth.read_text().split('*.cgi:')[0])
        (self.kit / 'www/dashboard.js').write_text('changed payload\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertFalse(self.state.exists())

    def test_interrupted_start_cleans_its_http_child_and_owned_state(self):
        if not self.network_allowed:
            self.skipTest('Loopback sockets unavailable in this sandbox')
        import time
        process = subprocess.Popen([self.bb, 'sh', str(self.kit / 'start.sh')],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        http_pid = None
        try:
            until = time.monotonic() + 2
            while time.monotonic() < until and process.poll() is None:
                children = Path(f'/proc/{process.pid}/task/{process.pid}/children').read_text().split()
                for child in children:
                    try:
                        argv = Path(f'/proc/{child}/cmdline').read_bytes().split(b'\0')
                    except FileNotFoundError:
                        continue
                    if len(argv)>1 and argv[1]==b'httpd':
                        http_pid = int(child)
                        break
                if http_pid:
                    break
                time.sleep(.01)
            self.assertIsNotNone(http_pid)
            process.terminate()
            process.communicate(timeout=6)
            self.assertNotEqual(process.returncode, 0)
            self.assertFalse(self.state.exists())
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex(('127.0.0.1', self.port)), 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=6)
            # Only this fixture's exact recorded child may be cleaned up.
            if http_pid and Path(f'/proc/{http_pid}/exe').exists():
                try:
                    if os.readlink(f'/proc/{http_pid}/exe') == self.bb:
                        os.kill(http_pid, 15)
                except ProcessLookupError:
                    pass

    def test_busybox_without_auth_support_is_rejected_before_http(self):
        # Only this test copy substitutes an applet dispatcher. All non-auth
        # applets still execute the real host BusyBox; no server is started.
        binary = self.kit / 'bin/busybox'
        binary.unlink()
        binary.write_text('#!/bin/sh\nif [ "$1" = httpd ] && [ "$2" = -m ]; then exit 1; fi\nexec ' + shutil.which('busybox') + ' "$@"\n')
        binary.chmod(0o755)
        self.checksums()
        result = self.run_script('start.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('authentication support is required', result.stderr)
        self.assertFalse(self.state.exists())

    def test_status_json_redacts_private_fields_and_uses_local_ip_not_http_host(self):
        result = self.cgi(host='attacker.example:1234')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.body(result)
        self.assertEqual(data['ip'], '192.0.2.44')
        self.assertEqual(data['uptime_seconds'], 123)
        self.assertEqual(data['memory']['available_kB'], 20000)
        self.assertEqual(data['memory']['used_kB'], 45536)
        self.assertEqual(data['cpu'], {'load_1m':1.25,'load_5m':0.5,'load_15m':0.1})
        self.assertFalse(data['onvif']['available'])
        self.assertFalse(data['services']['onvif'])
        self.assertNotIn('attacker.example', result.stdout)
        self.assertNotIn('PRIVATE-ID', result.stdout)
        self.assertNotIn('DO-NOT-LEAK', result.stdout)
        self.assertNotIn('fixture-private-password', result.stdout)
        self.assertFalse(data['settings_write'])

    def test_invalid_host_ip_ambiguity_and_post_refuse_without_reflection(self):
        for host in ('', 'camera/../../etc', 'user@camera', 'camera\r\nInjected: yes', 'camera:99999', 'a..b', '999.1.1.1'):
            with self.subTest(host=host):
                result = self.cgi(host=host)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('400 Bad request', result.stdout)
        self.assertIn('405 Method not allowed', self.cgi(method='POST').stdout)
        for content in (' inet 999.1.2.3/24\n', ' inet 192.0.2.44/24\n inet 198.51.100.2/24\n'):
            self.ip.write_text(content)
            result = self.cgi()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('503 Service unavailable', result.stdout)
            self.assertNotIn(content.strip(), result.stdout)

    def test_memory_units_invalid_values_and_missing_available_produce_numbers(self):
        self.memory.write_text('MemTotal: 1000 kB\nMemFree: 100 kB\nCached: 200 kB\nBuffers: 10 kB\nSReclaimable: 20 kB\nShmem: 5 kB\nMemAvailable: SECRET bytes\n')
        data = self.body(self.cgi())
        self.assertEqual(data['memory']['available_kB'], 325)
        self.assertFalse(data['memory']['available_reported'])
        self.assertNotIn('SECRET', json.dumps(data))


class FullhanBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fullhan-builder-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / 'SOURCE/src/fullhan'
        source.parent.mkdir(parents=True)
        shutil.copytree(SOURCE, source)
        (source / 'private.db').write_bytes(b'never package unrelated source files\n')
        (self.root / 'LICENSE').write_bytes(b'MIT fixture\n')
        (self.root / 'SOURCE/Makefile').write_text('BUSYBOX := busybox-1.36.1\n')
        download = self.root / 'SOURCE/download'
        download.mkdir()
        with tarfile.open(download / 'busybox-1.36.1.tar.bz2', 'w:bz2') as archive:
            member = tarfile.TarInfo('busybox-1.36.1/LICENSE'); data = b'GPLv2-only fixture\n'; member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        self.busybox = self.root / 'busybox'
        header = b'\x7fELF\x01\x01\x01' + b'\0' * 9
        header += struct.pack('<HHIIIIIHHHHHH', 2, 40, 1, 0x10000, 52, 0, 0x5000200, 52, 32, 1, 0, 0, 0)
        self.busybox.write_bytes(header + struct.pack('<IIIIIIII', 1, 0, 0x10000, 0x10000, 84, 84, 5, 4096))
        self.busybox_manifest = self.root / 'busybox-manifest.json'
        self.busybox_manifest.write_text(json.dumps({'format':'lscamoflash-fullhan-busybox-v1','sha256':hashlib.sha256(self.busybox.read_bytes()).hexdigest(),'cgi_range_header':True}))
        self.readelf = self.root / 'readelf'
        self.readelf.write_text('#!/bin/sh\necho "Tag_CPU_arch: v5TE"\n')
        self.readelf.chmod(0o755)
        self.output = self.root / 'output/LSCamoflash-fullhan'
        self.compiler = self.root / 'cc'
        self.compiler.write_text('#!/bin/sh\nwhile [ \"$1\" != -o ]; do shift; done\nshift\ncp ' + str(self.busybox) + ' \"$1\"\n')
        self.compiler.chmod(0o755)
        for helper in ('fullhan-recordings/fullhan_recordings.c','fullhan-discovery/discovery.c'):
            destination = self.root / 'SOURCE/src/contrib' / helper
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text('/* fixture compile input */\n')

    def args(self, password=None):
        from types import SimpleNamespace
        return SimpleNamespace(output=self.output, busybox=self.busybox, readelf=str(self.readelf), qemu=None,
                               username='admin', password_file=password, cc=str(self.compiler), busybox_manifest=self.busybox_manifest, onvif_kit=None, onvif_password_file=None)

    def test_builder_curates_payload_checksums_and_has_no_default_credentials(self):
        BUILD.build(self.args(), self.root)
        self.assertFalse((self.output / 'httpd.conf').exists())
        for forbidden in ('private.db', 'hostapd', 'hack.conf', 'anyka_ipc', 'lib', '_ht_ap_mode.conf'):
            self.assertFalse((self.output / forbidden).exists())
        for line in (self.output / 'SHA256SUMS').read_text().splitlines():
            checksum, name = line.split('  ')
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), checksum)
        self.assertEqual((self.output / 'COPYING.BusyBox').read_bytes(), b'GPLv2-only fixture\n')
        self.assertFalse(json.loads((self.output / 'manifest.json').read_text())['credentials_provisioned'])

    @unittest.skipUnless(shutil.which('openssl'), 'Host OpenSSL required')
    def test_password_file_only_produces_private_hash_and_never_replaces_output(self):
        password = self.root / 'private-password'
        password.write_bytes(b'host-only-fixture-secret\n')
        BUILD.build(self.args(password), self.root)
        config = (self.output / 'httpd.conf').read_bytes()
        self.assertNotIn(b'host-only-fixture-secret', config)
        self.assertIn(b'/:admin:$1$', config)
        self.assertEqual((self.output / 'httpd.conf').stat().st_mode & 0o777, 0o600)
        before = config
        with self.assertRaisesRegex(ValueError, 'never replaced'):
            BUILD.build(self.args(password), self.root)
        self.assertEqual((self.output / 'httpd.conf').read_bytes(), before)
        for path in self.output.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'host-only-fixture-secret', path.read_bytes())

    def test_unpatched_or_mismatched_busybox_provenance_is_rejected(self):
        for field,value in (('cgi_range_header',False),('sha256','0'*64)):
            provenance=json.loads(self.busybox_manifest.read_text());provenance[field]=value
            self.busybox_manifest.write_text(json.dumps(provenance))
            with self.assertRaisesRegex(ValueError,'CGI Range header patch'):
                BUILD.build(self.args(),self.root)
            self.assertFalse(self.output.exists())
            self.busybox_manifest.write_text(json.dumps({'format':'lscamoflash-fullhan-busybox-v1','sha256':hashlib.sha256(self.busybox.read_bytes()).hexdigest(),'cgi_range_header':True}))

    def onvif_fixture(self):
        kit = self.root / 'onvif'
        (kit / 'bin').mkdir(parents=True)
        shutil.copyfile(self.busybox, kit / 'bin/onvif_srvd')
        (kit / 'COPYING.ONVIF').write_text('Public source license fixture\n')
        (kit / 'manifest.json').write_text(json.dumps({'format':'lscamoflash-fullhan-onvif-v1','sha256':hashlib.sha256(self.busybox.read_bytes()).hexdigest()}))
        return kit

    def test_optional_onvif_has_no_public_secret_and_preserves_binary_provenance(self):
        args = self.args()
        args.onvif_kit = self.onvif_fixture()
        BUILD.build(args, self.root)
        self.assertTrue((self.output / 'bin/onvif_srvd').exists())
        self.assertFalse((self.output / 'onvif.auth').exists())
        self.assertFalse((self.output / 'onvif.uuid').exists())
        manifest = json.loads((self.output / 'manifest.json').read_text())
        self.assertTrue(manifest['onvif_included'])
        self.assertFalse(manifest['onvif_credentials_provisioned'])
        self.assertEqual(manifest['onvif_provenance']['sha256'],hashlib.sha256(self.busybox.read_bytes()).hexdigest())

    def test_independent_onvif_credentials_remain_outside_web_and_public_checksums(self):
        password = self.root / 'onvif-password'
        password.write_text('private-onvif-fixture\n')
        args = self.args(); args.onvif_kit = self.onvif_fixture(); args.onvif_password_file = password
        BUILD.build(args, self.root)
        self.assertEqual((self.output / 'onvif.auth').read_text(),'admin\nprivate-onvif-fixture\n')
        import uuid
        self.assertEqual(uuid.UUID((self.output / 'onvif.uuid').read_text().strip()).version,4)
        for file in (self.output / 'www').rglob('*'):
            if file.is_file():self.assertNotIn(b'private-onvif-fixture',file.read_bytes())
        self.assertNotIn('onvif.auth',(self.output / 'SHA256SUMS').read_text())
        self.assertNotIn('private-onvif-fixture',(self.output / 'manifest.json').read_text())

    def test_host_or_dynamic_elf_and_renamed_or_symlink_output_are_rejected(self):
        self.busybox.write_bytes(b'not ARM ELF\n')
        self.busybox_manifest.write_text(json.dumps({'format':'lscamoflash-fullhan-busybox-v1','sha256':hashlib.sha256(self.busybox.read_bytes()).hexdigest(),'cgi_range_header':True}))
        with self.assertRaisesRegex(ValueError, 'ELF'):
            BUILD.build(self.args(), self.root)
        self.assertFalse(self.output.exists())
        self.output = self.root / 'wrong-name'
        with self.assertRaisesRegex(ValueError, 'named LSCamoflash-fullhan'):
            BUILD.build(self.args(), self.root)


if __name__ == '__main__':
    unittest.main()
