"""Isolated ONVIF fixtures. Stock programs, flash and physical cards are unused."""
import base64
import datetime
import hashlib
import os
import signal
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'SOURCE/src/fullhan'


class SHA256DigestAuthHandler(urllib.request.HTTPDigestAuthHandler):
    """Keep the SOAP fixture compatible with Python 3.11/3.12 urllib."""
    def get_algorithm_impls(self, algorithm):
        if algorithm == 'SHA-256':
            def digest(value):
                return hashlib.sha256(value.encode('ascii')).hexdigest()
            return digest, lambda secret, data: digest(secret + ':' + data)
        return super().get_algorithm_impls(algorithm)


class DigestHandlerTests(unittest.TestCase):
    def test_sha256_rfc7616_vector_when_stdlib_lacks_algorithm_support(self):
        # RFC 7616 section 3.9.1: independently specified challenge/response.
        # https://www.rfc-editor.org/rfc/rfc7616.html#section-3.9.1
        url = 'http://www.example.org/dir/index.html'
        passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password('http-auth@example.org', url, 'Mufasa', 'Circle of Life')
        challenge = {'realm': 'http-auth@example.org', 'qop': 'auth, auth-int', 'algorithm': 'SHA-256',
                     'nonce': '7ypf/xlj9XXwfDPEoM4URrv/xwf94BcCAzFZH4GiTo0v',
                     'opaque': 'FQhe/qaU925kfnzjCev0ciny7QMkPqMAFRtzCUYo5tdS'}
        handler = SHA256DigestAuthHandler(passwords)
        with mock.patch.object(urllib.request.AbstractDigestAuthHandler, 'get_algorithm_impls',
                               side_effect=ValueError('Unsupported digest authentication algorithm')) as legacy:
            with self.assertRaises(ValueError):
                urllib.request.HTTPDigestAuthHandler(passwords).get_authorization(urllib.request.Request(url), challenge)
            with mock.patch.object(handler, 'get_cnonce', return_value='f2/wE4q74E6zIJEtWaHKaf5wv/H5QzzpXusqGemxURZJ'):
                authorization = handler.get_authorization(urllib.request.Request(url), challenge)
            # Only the legacy baseline touched the deliberately unsupported
            # stdlib implementation; the SHA-256 fixture handles it itself.
            legacy.assert_called_once_with('SHA-256')
        fields = urllib.request.parse_keqv_list(urllib.request.parse_http_list(authorization))
        self.assertEqual(fields['response'], '753927fa0e85d155564e2e272a28d1802ca10daf4496794697cf8db5856cb6c1')
        self.assertEqual((fields['algorithm'], fields['qop'], fields['nc']), ('SHA-256', 'auth', '00000001'))


@unittest.skipUnless(shutil.which('busybox'), 'Host BusyBox required')
class OnvifGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fullhan-onvif-guards-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        (self.root / 'bin').mkdir()
        self.bb = shutil.which('busybox')
        common = (SOURCE / 'common.sh').read_text().replace('ROOT="/mnt/LSCamoflash-fullhan"', f'ROOT="{self.root}"')
        common = common.replace('PROC="/proc"', f'PROC="{self.proc}"').replace('MEMINFO="/proc/meminfo"', f'MEMINFO="{self.root}/meminfo"')
        common = common.replace('BB="$ROOT/bin/busybox"', f'BB="{self.bb}"')
        (self.root / 'common.sh').write_text(common)
        shutil.copyfile(SOURCE / 'onvif-common.sh', self.root / 'onvif-common.sh')
        self.auth = self.root / 'onvif.auth'
        self.auth.write_text('admin\nsynthetic-fixture-password\n')
        (self.root / 'onvif.uuid').write_text('6eeb1499-e62c-4e94-943b-43c4d8dbb698\n')
        (self.root / 'meminfo').write_text('MemAvailable: 13416 kB\n')

    def shell(self, command):
        return subprocess.run([self.bb, 'sh', '-c', f'. "{self.root}/common.sh"; . "{self.root}/onvif-common.sh"; ' + command],
                              capture_output=True, text=True, timeout=4)

    def test_auth_requires_exact_two_printable_lines_and_private_regular_file(self):
        self.assertEqual(self.shell('onvif_credentials').returncode, 0)
        for data in ('admin\n', 'admin\n\n', 'bad:name\nsecret\n', 'admin\nsecret\nextra\n', 'admin\nsec\tret\n', 'admin\n' + 'x'*129 + '\n'):
            self.auth.write_text(data)
            result = self.shell('onvif_credentials')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('secret', result.stderr)
        self.auth.unlink()
        self.auth.symlink_to(self.root / 'missing')
        self.assertNotEqual(self.shell('onvif_credentials').returncode, 0)

    def test_memory_threshold_units_missing_and_duplicate_fail_closed(self):
        for data, expected in (('MemAvailable: 8192 kB\n', 0), ('MemAvailable: 8191 kB\n', 1),
                               ('MemAvailable: 9000 MB\n', 1), ('MemFree: 20000 kB\n', 1),
                               ('MemAvailable: 10000 kB\nMemAvailable: 10000 kB\n', 1)):
            (self.root / 'meminfo').write_text(data)
            self.assertEqual(bool(self.shell('onvif_memory').returncode), bool(expected))

    def test_start_failure_before_state_or_child_for_missing_auth_and_low_memory(self):
        # Replace only physical identity/mount functions in this fixture copy.
        # Their production behavior is covered by test_fullhan.py.
        common = (self.root / 'common.sh').read_text()
        common += '\nroot_user() { return 0; }\nidentity() { return 0; }\ntrusted_mount() { return 0; }\nverify_payload() { return 0; }\n'
        (self.root / 'common.sh').write_text(common)
        text = (SOURCE / 'onvif-common.sh').read_text().replace('ONVIF_STATE="/tmp/lscamoflash-fullhan-onvif"', f'ONVIF_STATE="{self.root}/state"')
        (self.root / 'onvif-common.sh').write_text(text)
        for name in ('onvif_srvd', 'fullhan-discovery'):
            executable = self.root / 'bin' / name
            executable.write_text('#!/bin/sh\nprintf called > "' + str(self.root / 'executed') + '"\n')
            executable.chmod(0o755)
        script = self.root / 'onvif-start.sh'
        script.write_text((SOURCE / 'onvif-start.sh').read_text().replace('/mnt/LSCamoflash-fullhan', str(self.root)))
        self.auth.unlink()
        result = subprocess.run([self.bb, 'sh', str(script)], capture_output=True, text=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.auth.write_text('admin\nsynthetic-fixture-password\n')
        (self.root / 'meminfo').write_text('MemAvailable: 8191 kB\n')
        result = subprocess.run([self.bb, 'sh', str(script)], capture_output=True, text=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'state').exists())
        self.assertFalse((self.root / 'executed').exists())

    def process(self, kind):
        folder = self.proc / '321'
        folder.mkdir(exist_ok=True)
        # start_time reads field22 after safely removing the comm field.
        (folder / 'stat').write_text('321 (synthetic fixture) ' + ' '.join(['S'] + ['0']*18 + ['456']) + '\n')
        target = self.root / ('bin/onvif_srvd' if kind == 'server' else 'bin/fullhan-discovery')
        target.touch()
        (folder / 'exe').symlink_to(target)
        prefix = 'onvif_address=192.0.2.44; onvif_uuid=6eeb1499-e62c-4e94-943b-43c4d8dbb698; '
        if kind == 'server':
            result = self.shell(prefix + 'onvif_action=inspect; onvif_arguments')
            args = result.stdout.splitlines()
        else:
            args = [str(target), '--interface', 'wlan0', '--xaddr', 'http://192.0.2.44:5000/', '--uuid', '6eeb1499-e62c-4e94-943b-43c4d8dbb698']
        (folder / 'cmdline').write_bytes(b'\0'.join(arg.encode() for arg in args) + b'\0')
        return folder, prefix + ('onvif_owned' if kind == 'server' else 'onvif_discovery_owned') + ' 321 456'

    def test_server_owned_stop_checks_full_argv_executable_and_start_time(self):
        folder, command = self.process('server')
        self.assertEqual(self.shell(command).returncode, 0)
        original = (folder / 'cmdline').read_bytes()
        (folder / 'cmdline').write_bytes(original.replace(b'8554/main', b'8554/other'))
        self.assertNotEqual(self.shell(command).returncode, 0)
        (folder / 'cmdline').write_bytes(original)
        self.assertNotEqual(self.shell(command.replace('321 456', '321 457')).returncode, 0)
        (folder / 'exe').unlink()
        (folder / 'exe').symlink_to('/unrelated/daemon')
        self.assertNotEqual(self.shell(command).returncode, 0)

    def test_discovery_owned_stop_rejects_unrelated_interface_and_extra_options(self):
        folder, command = self.process('discovery')
        self.assertEqual(self.shell(command).returncode, 0)
        original = (folder / 'cmdline').read_bytes()
        for data in (original.replace(b'wlan0', b'eth0'), original + b'--port\0' + b'1234\0'):
            (folder / 'cmdline').write_bytes(data)
            self.assertNotEqual(self.shell(command).returncode, 0)

    def test_direct_mode_state_has_no_discovery_owner_and_rejects_partial_zero_fields(self):
        folder, command = self.process('server')
        state = self.root / 'state'
        state.mkdir()
        text = (self.root / 'onvif-common.sh').read_text().replace('ONVIF_STATE="/tmp/lscamoflash-fullhan-onvif"', f'ONVIF_STATE="{state}"')
        (self.root / 'onvif-common.sh').write_text(text)
        # Match the RAM pid-file argument after the fixture state relocation.
        (folder / 'cmdline').write_bytes((folder / 'cmdline').read_bytes().replace(b'/tmp/lscamoflash-fullhan-onvif', str(state).encode()))
        suffix = '192.0.2.44 6eeb1499-e62c-4e94-943b-43c4d8dbb698\n'
        (state / 'owned').write_text('321 456 0 0 ' + suffix)
        self.assertEqual(self.shell('onvif_running').returncode, 0)
        self.assertNotEqual(self.shell('onvif_discovery_running').returncode, 0)
        for values in ('0 456', '321 0'):
            (state / 'owned').write_text('321 456 ' + values + ' ' + suffix)
            self.assertNotEqual(self.shell('onvif_read_state').returncode, 0)

    @unittest.skipUnless(shutil.which('cc'), 'Host C compiler required for owned synthetic lifecycle')
    def test_busy_stock_discovery_refuses_default_but_direct_mode_starts_and_stops_only_own_server(self):
        common = (self.root / 'common.sh').read_text().replace(f'PROC="{self.proc}"', 'PROC="/proc"')
        common += '\nroot_user() { return 0; }\nidentity() { return 0; }\ntrusted_mount() { return 0; }\nverify_payload() { return 0; }\nread_ipv4() { printf "192.0.2.44\\n"; }\n'
        (self.root / 'common.sh').write_text(common)
        state = self.root / 'state'
        text = (self.root / 'onvif-common.sh').read_text().replace('ONVIF_STATE="/tmp/lscamoflash-fullhan-onvif"', f'ONVIF_STATE="{state}"')
        (self.root / 'onvif-common.sh').write_text(text)
        network = self.root / 'netstat'
        network.write_text('udp 0 0 0.0.0.0:3702 0.0.0.0:*\n')
        for name in ('onvif-start.sh', 'onvif-stop.sh'):
            text = (SOURCE / name).read_text().replace('/mnt/LSCamoflash-fullhan', str(self.root))
            text = text.replace('"$BB" netstat -tlnu 2>/dev/null', f'cat "{network}"')
            (self.root / name).write_text(text)
        source = self.root / 'synthetic-server.c'
        source.write_text('''#include <stdio.h>
#include <signal.h>
#include <string.h>
#include <unistd.h>
static volatile sig_atomic_t done;
static void stop(int number) { (void)number; done=1; }
int main(int argc,char **argv) {
  const char *pidfile=0; int i; FILE *fp;
  for(i=1;i+1<argc;i++) if(!strcmp(argv[i],"--pid_file"))pidfile=argv[i+1];
  if(!pidfile)return 2;
  signal(SIGTERM,stop);
  fp=fopen(pidfile,"w");if(!fp)return 1;
  fprintf(fp,"%ld\\n",(long)getpid());fclose(fp);
  while(!done)usleep(10000);
  unlink(pidfile);return 0;
}
''')
        binary = self.root / 'bin/onvif_srvd'
        subprocess.run(['cc', '-O2', str(source), '-o', str(binary)], check=True, capture_output=True, timeout=15)
        # A discovery executable is deliberately absent: direct mode must not
        # require or launch one, while the default mode must refuse startup.
        def run(name, *arguments):
            return subprocess.run([self.bb, 'sh', str(self.root / name), *arguments], capture_output=True, text=True, timeout=8)
        self.addCleanup(lambda: run('onvif-stop.sh') if (state / 'owned').exists() else None)
        result = run('onvif-start.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(state.exists())
        # With a packaged discovery binary, the default refusal specifically
        # comes from the occupied stock port before any state/process creation.
        shutil.copyfile(binary, self.root / 'bin/fullhan-discovery')
        (self.root / 'bin/fullhan-discovery').chmod(0o755)
        result = run('onvif-start.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('port is already in use', result.stderr)
        self.assertFalse(state.exists())
        network.write_text('tcp 0 0 0.0.0.0:5000 0.0.0.0:* LISTEN\n')
        result = run('onvif-start.sh', '--no-discovery')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(state.exists())
        network.write_text('udp 0 0 0.0.0.0:3702 0.0.0.0:*\n')
        (self.root / 'bin/fullhan-discovery').unlink()
        result = run('onvif-start.sh', '--no-discovery')
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = (state / 'owned').read_text().split()
        self.assertEqual(fields[2:4], ['0', '0'])
        self.assertEqual(self.shell('onvif_running').returncode, 0)
        self.assertNotEqual(self.shell('onvif_discovery_running').returncode, 0)
        result = run('onvif-stop.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(state.exists())
        self.assertEqual(network.read_text(), 'udp 0 0 0.0.0.0:3702 0.0.0.0:*\n')

    def lifecycle_fixture(self):
        """Actual owned synthetic processes; no sockets or stock commands."""
        common = (self.root / 'common.sh').read_text().replace(f'PROC="{self.proc}"', 'PROC="/proc"')
        common += '\nroot_user() { return 0; }\nidentity() { return 0; }\ntrusted_mount() { return 0; }\nverify_payload() { return 0; }\nread_ipv4() { printf "192.0.2.44\\n"; }\n'
        (self.root / 'common.sh').write_text(common)
        state = self.root / 'state'
        text = (SOURCE / 'onvif-common.sh').read_text().replace('ONVIF_STATE="/tmp/lscamoflash-fullhan-onvif"', f'ONVIF_STATE="{state}"')
        (self.root / 'onvif-common.sh').write_text(text)
        for name in ('onvif-start.sh', 'onvif-stop.sh'):
            text = (SOURCE / name).read_text().replace('/mnt/LSCamoflash-fullhan', str(self.root))
            text = text.replace('"$BB" netstat -tlnu 2>/dev/null', 'true')
            (self.root / name).write_text(text)
        source = self.root / 'lifecycle.c'
        source.write_text('''#include <stdio.h>
#include <signal.h>
#include <string.h>
#include <unistd.h>
static volatile sig_atomic_t done;
static void stop(int n) {(void)n;done=1;}
int main(int argc,char **argv) {
 const char *pidfile=0;int i;FILE *fp;
 signal(SIGTERM,stop);
 fp=fopen("''' + str(self.root / 'created-pids') + '''","a");
 if(!fp)return 2;fprintf(fp,"%ld\\n",(long)getpid());fclose(fp);
 if(strstr(argv[0],"fullhan-discovery") && access("''' + str(self.root / 'fail-discovery') + '''",F_OK)==0)return 1;
 for(i=1;i+1<argc;i++)if(!strcmp(argv[i],"--pid_file"))pidfile=argv[i+1];
 if(pidfile){fp=fopen(pidfile,"w");if(!fp)return 1;fprintf(fp,"%ld\\n",(long)getpid());fclose(fp);}
 while(!done)usleep(10000);
 if(pidfile){usleep(1200000);unlink(pidfile);}return 0;
}
''')
        binary = self.root / 'bin/onvif_srvd'
        subprocess.run(['cc', '-O2', str(source), '-o', str(binary)], check=True, capture_output=True, timeout=15)
        shutil.copyfile(binary, self.root / 'bin/fullhan-discovery')
        (self.root / 'bin/fullhan-discovery').chmod(0o755)

        def cleanup():
            if (self.root / 'created-pids').exists():
                for value in (self.root / 'created-pids').read_text().split():
                    try:
                        path = Path(f'/proc/{value}/exe').readlink()
                        if path in (binary, self.root / 'bin/fullhan-discovery'):
                            os.kill(int(value), signal.SIGKILL)
                    except (FileNotFoundError, ProcessLookupError):
                        pass
        self.addCleanup(cleanup)

        def run(name, *args):
            return subprocess.run([self.bb, 'sh', str(self.root / name), *args], capture_output=True,
                                  text=True, timeout=12)
        return state, run

    def wait_dead(self, pid):
        for _ in range(100):
            try:
                stat = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
                if stat[0] in ('Z', 'X'):
                    return
            except FileNotFoundError:
                return
            time.sleep(.02)
        self.fail('Synthetic process did not exit')

    @unittest.skipUnless(shutil.which('cc'), 'Host C compiler required')
    def test_stop_surviving_server_after_discovery_exits(self):
        state, run = self.lifecycle_fixture()
        result = run('onvif-start.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = (state / 'owned').read_text().split()
        os.kill(int(fields[2]), signal.SIGTERM)
        self.wait_dead(fields[2])
        result = run('onvif-stop.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.wait_dead(fields[0])
        self.assertFalse(state.exists())

    @unittest.skipUnless(shutil.which('cc'), 'Host C compiler required')
    def test_stop_surviving_discovery_after_server_crash_removes_exact_stale_pidfile(self):
        state, run = self.lifecycle_fixture()
        result = run('onvif-start.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = (state / 'owned').read_text().split()
        os.kill(int(fields[0]), signal.SIGKILL)
        self.wait_dead(fields[0])
        self.assertTrue((state / 'server.pid').exists())
        result = run('onvif-stop.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.wait_dead(fields[2])
        self.assertFalse(state.exists())

    @unittest.skipUnless(shutil.which('cc'), 'Host C compiler required')
    def test_mismatched_live_peer_or_zero_owner_never_signals_surviving_service(self):
        state, run = self.lifecycle_fixture()
        result = run('onvif-start.sh', '--no-discovery')
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (state / 'owned').read_text()
        fields = original.split()
        other = subprocess.Popen([self.bb, 'sleep', '30'])
        try:
            other_time = Path(f'/proc/{other.pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]
            changed = fields.copy(); changed[2:4] = [str(other.pid), other_time]
            (state / 'owned').write_text(' '.join(changed)+'\n')
            self.assertNotEqual(run('onvif-stop.sh').returncode, 0)
            self.assertIsNone(other.poll())
            self.assertEqual(self.shell('onvif_address=192.0.2.44; onvif_uuid='+fields[5]+'; onvif_owned '+fields[0]+' '+fields[1]).returncode, 0)
            changed = fields.copy(); changed[0] = '0'
            (state / 'owned').write_text(' '.join(changed)+'\n')
            self.assertNotEqual(run('onvif-stop.sh').returncode, 0)
            self.assertIsNone(other.poll())
            (state / 'owned').write_text(original)
            self.assertEqual(run('onvif-stop.sh').returncode, 0)
        finally:
            other.terminate(); other.wait(timeout=3)

    @unittest.skipUnless(shutil.which('cc'), 'Host C compiler required')
    def test_start_failure_waits_for_delayed_pidfile_cleanup_and_retry_succeeds(self):
        state, run = self.lifecycle_fixture()
        failure = self.root / 'fail-discovery'
        failure.touch()
        result = run('onvif-start.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(state.exists(), result.stderr)
        failure.unlink()
        result = run('onvif-start.sh', '--no-discovery')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(run('onvif-stop.sh').returncode, 0)
        self.assertFalse(state.exists())


@unittest.skipUnless(os.environ.get('FULLHAN_ONVIF_BIN'), 'Set FULLHAN_ONVIF_BIN to isolated built candidate for real SOAP fixtures')
class OnvifSoapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fullhan-soap-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.auth = self.root / 'onvif.auth'
        self.auth.write_text('fixture\nfixture-password\n')
        self.auth.chmod(0o600)
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
        except PermissionError:
            self.skipTest('Loopback sockets unavailable in sandbox')
        self.url = f'http://127.0.0.1:{port}/onvif/device_service'
        command = [os.environ['FULLHAN_ONVIF_BIN']]
        if os.environ.get('FULLHAN_ONVIF_QEMU'):
            command = [os.environ['FULLHAN_ONVIF_QEMU'], '-cpu', 'arm1176'] + command
        command += ['--no_fork', '--no_close', '--pid_file', str(self.root / 'server.pid'),
                    '--auth_file', str(self.auth), '--ifs', 'lo', '--port', str(port), '--scope', 'onvif://www.onvif.org/name/fixture',
                    '--name', 'main', '--width', '1920', '--height', '1080', '--url', 'rtsp://192.0.2.44:8554/main', '--type', 'H264',
                    '--name', 'sub', '--width', '640', '--height', '360', '--url', 'rtsp://192.0.2.44:8554/sub', '--type', 'H264']
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        import time
        for _ in range(50):
            if (self.root / 'server.pid').exists():
                time.sleep(.1)
                return
            if self.process.poll() is not None:
                self.fail('Isolated ONVIF candidate exited before readiness')
            time.sleep(.05)
        self.fail('Isolated ONVIF candidate did not become ready')

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

    def request(self, operation, namespace, content='', password='fixture-password', digest=False, username='fixture', created_at=None, nonce=None):
        header = ''
        if password is not None and not digest:
            nonce = os.urandom(16) if nonce is None else nonce
            created = (created_at or datetime.datetime.now(datetime.timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')
            value = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
            header = '<s:Header><wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"><wsse:UsernameToken><wsse:Username>' + username + '</wsse:Username><wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">' + value + '</wsse:Password><wsse:Nonce>' + base64.b64encode(nonce).decode() + '</wsse:Nonce><wsu:Created xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">' + created + '</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header>'
        data = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">' + header + '<s:Body><m:' + operation + ' xmlns:m="' + namespace + '">' + content + '</m:' + operation + '></s:Body></s:Envelope>').encode()
        request = urllib.request.Request(self.url, data, {'Content-Type': 'application/soap+xml; charset=utf-8'})
        opener = urllib.request.build_opener()
        if digest:
            passwords = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            passwords.add_password(None, self.url, username, password)
            opener = urllib.request.build_opener(SHA256DigestAuthHandler(passwords))
        try:
            with opener.open(request, timeout=4) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            try:
                return error.code, error.read()
            finally:
                error.close()

    def test_real_soap_requires_auth_and_returns_only_native_h264_profiles(self):
        device = 'http://www.onvif.org/ver10/device/wsdl'
        media = 'http://www.onvif.org/ver10/media/wsdl'
        for password in (None, 'wrong-password'):
            status, body = self.request('GetProfiles', media, password=password)
            self.assertNotEqual(status, 200)
            self.assertNotIn(b'rtsp://', body)
        status, body = self.request('GetProfiles', media, username='wrong-user')
        self.assertNotEqual(status, 200)
        self.assertNotIn(b'rtsp://', body)
        status, body = self.request('GetCapabilities', device)
        self.assertEqual(status, 200)
        self.assertNotIn(b'<tt:PTZ', body)
        self.assertNotIn(b'<tt:Events', body)
        status, body = self.request('GetProfiles', media)
        self.assertEqual(status, 200)
        document = ET.fromstring(body)
        profiles = document.findall('.//{http://www.onvif.org/ver10/media/wsdl}Profiles')
        self.assertEqual({p.attrib['token'] for p in profiles}, {'main', 'sub'})
        self.assertEqual(body.count(b'>H264<'), 2)
        self.assertNotIn(b'AudioEncoderConfiguration', body)
        for profile in ('main', 'sub'):
            status, body = self.request('GetStreamUri', media, '<m:StreamSetup><tt:Stream xmlns:tt="http://www.onvif.org/ver10/schema">RTP-Unicast</tt:Stream><tt:Transport xmlns:tt="http://www.onvif.org/ver10/schema"><tt:Protocol>RTSP</tt:Protocol></tt:Transport></m:StreamSetup><m:ProfileToken>' + profile + '</m:ProfileToken>')
            self.assertEqual(status, 200)
            self.assertIn(('rtsp://192.0.2.44:8554/' + profile).encode(), body)

    def test_http_digest_and_unsupported_writes_fail_without_side_effects(self):
        device = 'http://www.onvif.org/ver10/device/wsdl'
        # Force the Python 3.11/3.12 compatibility path even on a newer host.
        # A server downgrade to another algorithm also fails this control.
        with mock.patch.object(urllib.request.AbstractDigestAuthHandler, 'get_algorithm_impls',
                               side_effect=ValueError('Simulated legacy urllib algorithm support')):
            status, body = self.request('GetCapabilities', device, digest=True)
        self.assertEqual(status, 200)
        for action, namespace in (('SystemReboot', device), ('SetHostname', device),
                                  ('ContinuousMove', 'http://www.onvif.org/ver20/ptz/wsdl'),
                                  ('GetSnapshotUri', 'http://www.onvif.org/ver10/media/wsdl')):
            status, body = self.request(action, namespace)
            self.assertNotEqual(status, 200)
        self.assertEqual(self.auth.read_text(), 'fixture\nfixture-password\n')
        self.assertIsNone(self.process.poll())

    def test_anonymous_clock_bootstrap_corrects_wsse_offset_without_relaxing_freshness_or_replay(self):
        device = 'http://www.onvif.org/ver10/device/wsdl'
        media = 'http://www.onvif.org/ver10/media/wsdl'
        # A client two hours behind represents the observed camera-ahead skew
        # without changing any host, camera or vendor clock/configuration.
        client_now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        status, body = self.request('GetProfiles', media, created_at=client_now)
        self.assertNotEqual(status, 200)
        self.assertNotIn(b'rtsp://', body)
        status, body = self.request('GetSystemDateAndTime', device, password=None)
        self.assertEqual(status, 200)
        document = ET.fromstring(body)
        schema = '{http://www.onvif.org/ver10/schema}'
        utc = document.find('.//' + schema + 'UTCDateTime')
        self.assertIsNotNone(utc)
        def value(section, field):
            return int(utc.find(schema + section + '/' + schema + field).text)
        reported = datetime.datetime(value('Date', 'Year'), value('Date', 'Month'), value('Date', 'Day'),
                                     value('Time', 'Hour'), value('Time', 'Minute'), value('Time', 'Second'),
                                     tzinfo=datetime.timezone.utc)
        offset = reported - client_now
        self.assertTrue(7190 < offset.total_seconds() < 7210)
        corrected = client_now + offset
        nonce = os.urandom(16)
        status, body = self.request('GetProfiles', media, created_at=corrected, nonce=nonce)
        self.assertEqual(status, 200)
        self.assertIn(b'>H264<', body)
        status, body = self.request('GetProfiles', media, created_at=corrected, nonce=nonce)
        self.assertNotEqual(status, 200)
        self.assertNotIn(b'rtsp://', body)
        # Time is the sole pre-auth exception; capabilities and media remain
        # protected even after an anonymous clock query.
        for action, namespace in (('GetCapabilities', device), ('GetProfiles', media), ('GetStreamUri', media)):
            status, body = self.request(action, namespace, password=None)
            self.assertNotEqual(status, 200)
            self.assertNotIn(b'rtsp://', body)


if __name__ == '__main__':
    unittest.main()
