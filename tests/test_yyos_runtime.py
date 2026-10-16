"""Isolated YYOS management fixtures; vendor programs and real mounts are unused."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'SOURCE/src/yyos'
FILES = ('common.sh', 'start.sh', 'stop.sh', 'README.md', 'www/index.html',
         'www/dashboard.js', 'www/dashboard.css', 'www/cgi-bin/status.cgi',
         'bin/busybox', 'bin/yyos-recordings', 'www/cgi-bin/recordings.cgi', 'LICENSE.MIT', 'COPYING.BusyBox', 'manifest.json')


def start_time(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]


@unittest.skipUnless(shutil.which('busybox') and shutil.which('openssl'), 'Host BusyBox and OpenSSL required')
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yyos-runtime-')
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Path(self.temporary.name)
        self.card = self.fixture / 'card'
        self.card.mkdir()
        self.kit = self.card / 'LSCamoflash-yyos'
        shutil.copytree(SOURCE, self.kit)
        # This baseline models the optional read-only kit without controls helpers.
        (self.kit / "www/cgi-bin/controls.cgi").unlink(missing_ok=True)
        (self.kit / 'bin').mkdir()
        shutil.copyfile(shutil.which('busybox'), self.kit / 'bin/busybox')
        (self.kit / 'bin/busybox').chmod(0o755)
        # Unused runtime-inventory stand-in; the actual C helper has separate host/ARM fixtures.
        shutil.copyfile(shutil.which('busybox'), self.kit / 'bin/yyos-recordings')
        self.bb = str(self.kit / 'bin/busybox')
        self.state = self.fixture / 'state'
        self.device = self.fixture / 'mmcblk0p1'
        self.device.touch()
        self.stock = self.fixture / 'yy_cam'
        # A host shell blocked in its read builtin models stock, never firmware.
        shutil.copyfile(shutil.which('sh'), self.stock)
        self.stock.chmod(0o755)
        self.cpu = self.fixture / 'cpuinfo'
        self.cpu.write_text('Processor: ARM926EJ-S\nHardware: AK3918AV130\nSerial: PRIVATE-ID\n')
        self.mounts = self.fixture / 'mounts'
        self.mounts.write_text(self.mount_row())
        self.magic = self.fixture / 'magic'; self.magic.write_text('4d44\n')
        self.visible = self.fixture / 'visible'; self.visible.write_text('45825\n')
        self.pair = self.fixture / 'pair'; self.pair.write_text('b3:1\n')
        self.memory = self.fixture / 'meminfo'
        self.memory.write_text('MemTotal: 38112 kB\nMemFree: 4096 kB\nMemAvailable: 25580 kB\nCached: 10000 kB\nPrivatePassword: DO-NOT-LEAK\n')
        self.uptime = self.fixture / 'uptime'; self.uptime.write_text('123.75 99.00\n')
        self.loadavg = self.fixture / 'loadavg'; self.loadavg.write_text('1.25 0.50 0.10 1/10 123\n')
        self.ip = self.fixture / 'ip-addresses'; self.ip.write_text('2: wlan0: <UP>\n    inet 192.0.2.44/24 scope global wlan0\n')
        self.ports = self.fixture / 'ports'; self.ports.write_text('')
        self.disk = self.fixture / 'disk'
        self.disk.write_text(f'Filesystem 1K-blocks Used Available Use% Mounted on\n{self.device} 30000000 100000 29900000 1% {self.card}\n')
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); self.port = sock.getsockname()[1]
            self.network_allowed = True
        except PermissionError:
            self.port = 49151; self.network_allowed = False
        for path in (self.kit / 'start.sh', self.kit / 'stop.sh', self.kit / 'common.sh', self.kit / 'www/cgi-bin/status.cgi', self.kit / 'www/cgi-bin/recordings.cgi'):
            text = path.read_text().replace('/mnt/sdcard', str(self.card))
            if path.name == 'common.sh':
                changes = {
                    'root_user() { [ "$(tool id -u)" = 0 ]; }': 'root_user() { return 0; }',
                    'STATE="/tmp/lscamoflash-yyos"': f'STATE="{self.state}"',
                    'MMC="/dev/mmcblk0p1"': f'MMC="{self.device}"',
                    'for directory in /mnt ': f'for directory in "{self.fixture}" ',
                    'CPUINFO="/proc/cpuinfo"': f'CPUINFO="{self.cpu}"',
                    'MOUNTS="/proc/mounts"': f'MOUNTS="{self.mounts}"',
                    'MEMINFO="/proc/meminfo"': f'MEMINFO="{self.memory}"',
                    'UPTIME="/proc/uptime"': f'UPTIME="{self.uptime}"',
                    'LOADAVG="/proc/loadavg"': f'LOADAVG="{self.loadavg}"',
                    'STOCK="/appfs/bin/yy_cam"': f'STOCK="{self.stock}"',
                    'd76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7': hashlib.sha256(self.stock.read_bytes()).hexdigest(),
                    'PORT="8080"': f'PORT="{self.port}"',
                    'HTTP_BIND="$PORT"': 'HTTP_BIND="127.0.0.1:$PORT"',
                    '$(tool stat -f -c %t "$CARD_MOUNT")': f'$(tool cat "{self.magic}")',
                    '$(tool stat -c %d "$CARD_MOUNT")': f'$(tool cat "{self.visible}")',
                    '[ -b "$device" ]': '[ -f "$device" ]',
                    '$(tool stat -c %t:%T "$device")': f'$(tool cat "{self.pair}")',
                    'tool ip -4 addr show 2>/dev/null': f'tool cat "{self.ip}"',
                    'tool netstat -tln 2>/dev/null': f'{{ tool netstat -tln 2>/dev/null; tool cat "{self.ports}"; }}',
                }
                for old, new in changes.items():
                    self.assertIn(old, text); text = text.replace(old, new)
            elif path.name == 'status.cgi':
                text = text.replace('tool df -k "$CARD_MOUNT" 2>/dev/null', f'tool cat "{self.disk}"')
            path.write_text(text)
        hashed = subprocess.run(['openssl', 'passwd', '-1', '-stdin'], input=b'fixture-password\n', capture_output=True, check=True).stdout.decode().strip()
        self.auth = self.kit / 'httpd.conf'; self.auth.write_text('I:index.html\n/:admin:' + hashed + '\n')
        (self.kit / 'LICENSE.MIT').write_text('MIT fixture\n')
        (self.kit / 'COPYING.BusyBox').write_text('GPLv2 fixture\n')
        (self.kit / 'manifest.json').write_text('{"format":"fixture"}\n')
        self.checksums()
        self.addCleanup(self.cleanup_server)

    def mount_row(self, options='rw', source=None, kind='vfat'):
        return f'{source or self.device} {self.card} {kind} {options},relatime 0 0\n'

    def checksums(self):
        (self.kit / 'SHA256SUMS').write_text(''.join(hashlib.sha256((self.kit / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in FILES))

    def run_script(self, name):
        return subprocess.run([self.bb, 'sh', str(self.kit / name)], capture_output=True, text=True, timeout=15)

    def cleanup_server(self):
        if (self.state / 'pid').is_file():
            self.run_script('stop.sh')

    def cgi(self, host='camera.local:8080', method='GET'):
        return subprocess.run([self.bb, 'sh', str(self.kit / 'www/cgi-bin/status.cgi')],
                              env=dict(os.environ, HTTP_HOST=host, REQUEST_METHOD=method, QUERY_STRING='cmd=DO-NOT-EXECUTE', PRIVATE_ENV='DO-NOT-LEAK'),
                              capture_output=True, text=True, timeout=8)

    def body(self, response):
        return json.loads(response.stdout.split('\n\n', 1)[1])

    def test_identity_root_and_auth_refuse_before_state(self):
        self.cpu.write_text('Hardware: FH8626V100\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.cpu.write_text('Hardware: AK3918AV130\n')
        original = self.stock.read_bytes(); self.stock.write_bytes(original + b'wrong identity')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0); self.stock.write_bytes(original)
        common = self.kit / 'common.sh'; saved = common.read_text()
        common.write_text(saved.replace('root_user() { return 0; }', 'root_user() { return 1; }'))
        self.assertNotEqual(self.run_script('start.sh').returncode, 0); common.write_text(saved)
        for content in ('', 'I:index.html\n/:admin:plaintext\n', self.auth.read_text() + '*.cgi:/bin/sh\n'):
            self.auth.write_text(content)
            self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertFalse(self.state.exists()); self.assertFalse((self.kit / 'startup.log').exists())

    def test_visible_mount_wrong_identity_readonly_and_duplicates_refuse(self):
        for mounts, magic, visible in ((self.mount_row('ro'), '4d44', 45825), (self.mount_row()*2, '4d44', 45825),
                (self.mount_row()+self.mount_row('ro'), '4d44', 45825), (self.mount_row(kind='ext4'), 'ef53', 45825),
                (self.mount_row(source='/dev/unrelated'), '4d44', 45825), (self.mount_row(), '4d44', 45826)):
            with self.subTest(mounts=mounts):
                self.mounts.write_text(mounts); self.magic.write_text(magic); self.visible.write_text(str(visible))
                self.assertNotEqual(self.run_script('start.sh').returncode, 0)
                self.assertFalse(self.state.exists())
        self.mounts.write_text(f'tmpfs {self.card} tmpfs rw 0 0\n' + self.mount_row())
        self.magic.write_text('4d44'); self.visible.write_text('45825')
        result = subprocess.run([self.bb, 'sh', '-c', '. "$1"; trusted_mount', 'fixture', str(self.kit / 'common.sh')], capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_exact_payload_missing_checksums_unknown_files_and_tamper_refuse(self):
        index = self.kit / 'www/index.html'; original = index.read_bytes()
        index.write_bytes(original + b'changed')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0); index.write_bytes(original)
        saved = (self.kit / 'SHA256SUMS').read_text()
        (self.kit / 'SHA256SUMS').write_text('\n'.join(saved.splitlines()[1:])+'\n')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        (self.kit / 'SHA256SUMS').write_text(saved)
        (self.kit / 'www/private.db').write_bytes(b'PRIVATE')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertFalse(self.state.exists())

    def test_symlink_log_credentials_and_existing_state_are_preserved(self):
        target = self.fixture / 'preserve'; target.write_bytes(b'KEEP')
        log = self.kit / 'startup.log'; log.symlink_to(target)
        self.assertNotEqual(self.run_script('start.sh').returncode, 0); log.unlink()
        self.auth.unlink(); self.auth.symlink_to(target)
        self.assertNotEqual(self.run_script('start.sh').returncode, 0); self.auth.unlink()
        self.state.mkdir(); (self.state / 'sentinel').write_bytes(b'KEEP')
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertEqual(target.read_bytes(), b'KEEP'); self.assertEqual((self.state / 'sentinel').read_bytes(), b'KEEP')

    def test_occupied_port_refuses_before_creating_state(self):
        self.ports.write_text(f'tcp 0 0 0.0.0.0:{self.port} 0.0.0.0:* LISTEN\n')
        result = self.run_script('start.sh')
        self.assertNotEqual(result.returncode, 0); self.assertIn('occupied', result.stderr)
        self.assertFalse(self.state.exists())

    def test_failed_daemon_bind_leaves_no_success_or_stale_state(self):
        common = self.kit / 'common.sh'
        common.write_text(common.read_text().replace('HTTP_BIND="127.0.0.1:$PORT"', 'HTTP_BIND="192.0.2.254:$PORT"'))
        self.checksums()
        self.assertNotEqual(self.run_script('start.sh').returncode, 0)
        self.assertFalse(self.state.exists()); self.assertFalse((self.kit / 'startup.log').exists())

    def test_cgi_sanitized_counters_and_native_candidates_are_unverified(self):
        self.ports.write_text('tcp 0 0 0.0.0.0:8554 0.0.0.0:* LISTEN\ntcp 0 0 0.0.0.0:5000 0.0.0.0:* LISTEN\n')
        response = self.cgi(); self.assertEqual(response.returncode, 0, response.stderr)
        data = self.body(response)
        self.assertEqual(data['memory']['available_kB'], 25580)
        self.assertEqual(data['memory']['used_kB'], 12532)
        self.assertEqual(data['storage']['total_kB'], 30000000)
        self.assertTrue(data['services']['native_rtsp_listening']); self.assertTrue(data['services']['native_onvif_listening'])
        self.assertFalse(data['streams']['verified']); self.assertFalse(data['onvif']['verified'])
        self.assertEqual(data['streams']['main_candidate'], 'rtsp://192.0.2.44:8554/stream0')
        self.assertEqual(data['onvif']['candidate_url'], 'http://192.0.2.44:5000/onvif/device_service')
        for flag in ('stock_app_managed', 'settings_write', 'network_write', 'ptz', 'reboot', 'firmware_update'):
            self.assertFalse(data[flag])
        self.assertEqual(data['recordings'], {'read_only': True, 'format': 'yyos-v5-media', 'playback': False})
        for private in ('PRIVATE', 'DO-NOT-LEAK', 'DO-NOT-EXECUTE', 'fixture-password'):
            self.assertNotIn(private, response.stdout)

    def test_cgi_invalid_host_ip_method_and_head(self):
        for host in ('camera.local/evil', 'x\r\nInjected: yes', '999.1.1.1', 'camera.local:99999'):
            self.assertIn('400', self.cgi(host=host).stdout)
        self.assertIn('405', self.cgi(method='POST').stdout)
        self.assertEqual(self.cgi(method='HEAD').stdout.split('\n\n', 1)[1], '')
        self.ip.write_text('inet 192.0.2.44/24\ninet 192.0.2.45/24\n')
        self.assertIn('503', self.cgi().stdout)

    def test_invalid_memory_and_cpu_values_cannot_inject_json(self):
        self.memory.write_text('MemTotal: 10000 kB\nMemFree: 1000 kB\nMemAvailable: BAD kB\nCached: 3000 kB\nShmem: 500 kB\nPrivate: <script>\n')
        self.loadavg.write_text('evil 999999999999999999999999999 0.25\n')
        data = self.body(self.cgi())
        self.assertFalse(data['memory']['available_reported']); self.assertEqual(data['memory']['available_kB'], 3500)
        self.assertEqual(data['cpu'], {'load_1m': 0, 'load_5m': 0, 'load_15m': 0.25})

    def test_unrelated_or_zero_pid_is_never_signalled(self):
        other = subprocess.Popen([self.bb, 'sleep', '30'])
        try:
            self.state.mkdir()
            for line in (f'{other.pid} {start_time(other.pid)}\n', '0 1\n', '1 1\n', f'{other.pid} 0\n'):
                (self.state / 'pid').write_text(line)
                self.assertNotEqual(self.run_script('stop.sh').returncode, 0)
                self.assertIsNone(other.poll())
            (self.state / 'pid').unlink(); self.state.rmdir()
        finally:
            other.terminate(); other.wait(timeout=3)

    def test_authenticated_http_owned_lifecycle_preserves_stock_process(self):
        if not self.network_allowed:
            self.skipTest('Loopback sockets unavailable in this sandbox')
        stock = subprocess.Popen([self.stock, '-c', 'read fixture'], stdin=subprocess.PIPE)
        stamp = start_time(stock.pid)
        try:
            self.assertEqual(self.run_script('start.sh').returncode, 0)
            saved = (self.state / 'pid').read_text()
            self.assertNotEqual(self.run_script('start.sh').returncode, 0)
            self.assertEqual((self.state / 'pid').read_text(), saved)
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/', timeout=3)
            self.assertEqual(denied.exception.code, 401); denied.exception.close()
            def request(path):
                value = urllib.request.Request(f'http://127.0.0.1:{self.port}/{path}')
                value.add_header('Authorization', 'Basic '+base64.b64encode(b'admin:fixture-password').decode())
                return urllib.request.urlopen(value, timeout=3)
            with request('cgi-bin/status.cgi') as response:
                data = json.load(response)
            self.assertTrue(data['services']['stock_app']); self.assertTrue(data['services']['management'])
            with self.assertRaises(urllib.error.HTTPError) as excluded:
                request('httpd.conf')
            exclusion_status = excluded.exception.code; excluded.exception.close()
            self.assertIn(exclusion_status, (403, 404))
            pid, timestamp = saved.split()
            (self.state / 'pid').write_text(f'{pid} {int(timestamp)+1}\n')
            self.assertNotEqual(self.run_script('stop.sh').returncode, 0)
            (self.state / 'pid').write_text(saved)
            self.assertEqual(self.run_script('stop.sh').returncode, 0)
            self.assertFalse(self.state.exists()); self.assertIsNone(stock.poll()); self.assertEqual(start_time(stock.pid), stamp)
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex(('127.0.0.1', self.port)), 0)
            self.assertEqual(self.run_script('start.sh').returncode, 0)
            self.assertEqual(self.run_script('stop.sh').returncode, 0)
        finally:
            stock.terminate(); stock.wait(timeout=3); stock.stdin.close()

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for browser URL validation fixture')
    def test_browser_only_accepts_profile_specific_same_camera_candidates(self):
        program = r'''
const assert=require('assert');const ui=require(process.argv[1]);const ip='192.0.2.44';
assert(ui.streamURL('rtsp://192.0.2.44:8554/stream0',ip,'stream0'));
for(const url of ['rtsp://other.local:8554/stream0','rtsp://u:p@192.0.2.44:8554/stream0','rtsp://192.0.2.44:8554/main','rtsp://192.0.2.44:8554/stream0?key=private'])assert.equal(ui.streamURL(url,ip,'stream0'),null);
assert(ui.serviceURL('http://192.0.2.44:5000/onvif/device_service',ip));
for(const url of ['http://other.local:5000/onvif/device_service','http://192.0.2.44:5000/','javascript:alert(1)','http://192.0.2.44:5000/onvif/device_service#x'])assert.equal(ui.serviceURL(url,ip),null);
assert.deepEqual(ui.memoryValues({total_kB:100,available_kB:200}),{total:100,available:100,used:0,percent:0});
assert.equal(ui.memoryValues({total_kB:100,available_kB:NaN}),null);
'''
        result = subprocess.run(['node', '-e', program, str(self.kit / 'www/dashboard.js')], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
