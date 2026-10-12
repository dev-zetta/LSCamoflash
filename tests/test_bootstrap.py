"""Native SD entry and mount regressions; no real mounts or camera programs."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'SOURCE/src/contrib/bootstrap/hostapd.c'
STAGE = (ROOT / 'SOURCE/src/sdcard/mmcblk0p1/bootstrap.sh').read_text()


@unittest.skipUnless(shutil.which('cc') and shutil.which('busybox'), 'host C compiler and BusyBox required')
class NativeBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='camoflash-bootstrap-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.card = self.root / 'card'
        self.card.mkdir()
        self.device = self.root / 'mmcblk0'
        self.device.touch()
        self.mounts = self.root / 'mounts'
        self.mounts.write_text(self.mount_row())
        shutil.copyfile(shutil.which('busybox'), self.card / 'busybox')
        (self.card / 'busybox').chmod(0o755)
        (self.card / 'bootstrap.sh').write_text('''#!/bin/sh
printf 'root=%s arg1=%s arg2=%s\\n' "$1" "$2" "$3"
cat /proc/$$/comm
exit 17
''')
        self.program = self.root / 'hostapd'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                        f'-DBOOTSTRAP_FIXTURE_ROOT="{self.root}"', str(SOURCE), '-o', str(self.program)], check=True)

    def mount_row(self, mode='rw'):
        return f'{self.device} {self.card} vfat {mode},relatime 0 0\n'

    def run_entry(self):
        return subprocess.run([str(self.program), '/etc/config/hostapd.conf', '-B'],
                              capture_output=True, text=True, timeout=3)

    def test_exec_forwards_stock_arguments_and_replaces_hostapd_process(self):
        result = self.run_entry()
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertIn(f'root={self.card} arg1=/etc/config/hostapd.conf arg2=-B', result.stdout)
        self.assertNotEqual(result.stdout.splitlines()[-1], 'hostapd')

    def test_covered_tmpfs_row_does_not_hide_fat_card(self):
        self.mounts.write_text(f'tmpfs {self.card} tmpfs rw 0 0\n' + self.mount_row())
        self.assertEqual(self.run_entry().returncode, 17)

    def test_missing_readonly_ambiguous_and_unrelated_mounts_are_rejected(self):
        for content in ('', self.mount_row('ro'), self.mount_row() * 2,
                        f'/dev/notmmc {self.card} vfat rw 0 0\n',
                        f'{self.device} {self.card} ext4 rw 0 0\n',
                        self.mount_row() + self.mount_row('ro')):
            with self.subTest(content=content):
                self.mounts.write_text(content)
                result = self.run_entry()
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(result.stdout, '')

    def test_symlink_card_is_rejected(self):
        moved = self.root / 'real-card'
        self.card.rename(moved)
        self.card.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.run_entry().returncode, 2)

    def test_symlink_or_empty_payloads_are_rejected_without_execution(self):
        for name in ('busybox', 'bootstrap.sh'):
            path = self.card / name
            saved = self.root / name
            path.rename(saved)
            path.symlink_to(saved)
            with self.subTest(name=name, kind='symlink'):
                self.assertEqual(self.run_entry().returncode, 3)
            path.unlink()
            path.touch()
            with self.subTest(name=name, kind='empty'):
                self.assertEqual(self.run_entry().returncode, 3)
            path.unlink()
            saved.rename(path)


class StageMountTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='camoflash-stage-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.boot = self.root / 'boot'
        self.sd = self.root / 'sd'
        self.tools = self.root / 'tools'
        self.tools.mkdir()
        self.boot.mkdir()
        self.mounts = self.root / 'mounts'
        self.mounts.touch()
        self.log = self.root / 'mount.log'
        mount = self.tools / 'mount'
        mount.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$MOUNT_LOG"\nexit "${MOUNT_RESULT:-0}"\n')
        mount.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.tools) + ':' + os.environ['PATH'],
                        boot_root=str(self.boot), sd_path=str(self.sd),
                        sd_dev=str(self.root / 'mmcblk0p2'), hack_conf=str(self.boot / 'HACK/etc/hack.conf'),
                        init=str(self.boot / 'HACK/sbin/init.sh'), MOUNT_LOG=str(self.log))
        start = STAGE.index('\tmkdir -p "$sd_path"')
        end = STAGE.index('\n\t# Persist boot diagnostics', start)
        self.block = STAGE[start:end].replace('/proc/mounts', str(self.mounts))
        # A fixture file replaces the block-device predicate only in this test.
        self.block = self.block.replace('[ -b "$sd_dev" ]', '[ -f "$sd_dev" ]')

    def runtime(self):
        config = self.boot / 'HACK/etc/hack.conf'
        config.parent.mkdir(parents=True)
        config.touch()
        init = self.boot / 'HACK/sbin/init.sh'
        init.parent.mkdir()
        init.write_text('#!/bin/sh\nexit 0\n')
        init.chmod(0o755)

    def run_block(self):
        return subprocess.run(['/bin/sh', '-c', self.block], env=self.env,
                              capture_output=True, text=True, timeout=3)

    def test_single_fat_runtime_uses_bind_mount(self):
        self.runtime()
        result = self.run_block()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().strip(), f'--bind {self.boot} {self.sd}')

    def test_partition_two_is_preferred(self):
        self.runtime()
        Path(self.env['sd_dev']).touch()
        self.assertEqual(self.run_block().returncode, 0)
        self.assertEqual(self.log.read_text().strip(), f'-t vfat -o rw {self.env["sd_dev"]} {self.sd}')

    def test_mount_failure_and_missing_runtime_stop_setup(self):
        self.assertNotEqual(self.run_block().returncode, 0)
        self.assertFalse(self.log.exists())
        self.runtime()
        self.env['MOUNT_RESULT'] = '1'
        self.assertNotEqual(self.run_block().returncode, 0)

    def test_existing_non_card_or_readonly_mount_is_rejected(self):
        self.runtime()
        for row in (f'tmpfs {self.sd} tmpfs rw 0 0\n',
                    f'/dev/mmcblk0 {self.sd} vfat ro 0 0\n'):
            self.mounts.write_text(row)
            self.assertNotEqual(self.run_block().returncode, 0)
            self.assertFalse(self.log.exists())

    def test_existing_fat_mount_and_covered_tmpfs_are_accepted(self):
        self.runtime()
        self.mounts.write_text(f'tmpfs {self.sd} tmpfs rw 0 0\n/dev/mmcblk0p2 {self.sd} vfat rw 0 0\n')
        self.assertEqual(self.run_block().returncode, 0)
        self.assertFalse(self.log.exists())

    def test_station_reload_is_limited_to_exact_firmware(self):
        driver = self.tools / 'driver'
        driver.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$MOUNT_LOG"\n')
        driver.chmod(0o755)
        start = STAGE.index('\tcase "$anyka_md5"')
        end = STAGE.index('\n\tesac', start) + len('\n\tesac')
        block = STAGE[start:end].replace('/usr/sbin/wifi_driver_atbm6132c.sh', str(driver))
        for checksum in ('7c2a124cdd607ebef63fb66d063b6a87', 'f' * 32):
            self.env['anyka_md5'] = checksum
            result = subprocess.run(['/bin/sh', '-c', block], env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if checksum.startswith('7c2'):
                self.assertEqual(self.log.read_text(), 'sta\n')
                self.log.unlink()
            else:
                self.assertFalse(self.log.exists())


@unittest.skipUnless(shutil.which('busybox'), 'host BusyBox required')
class PersistentBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='camoflash-boot-logs-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.hack = self.root / 'HACK'
        self.logs = self.hack / 'var/log'
        self.logs.mkdir(parents=True)
        (self.hack / 'bin').mkdir()
        self.lock = self.root / 'setup.lock'
        self.wrapper = self.root / 'wrapper'
        self.application = self.root / 'application'
        self.mounts = self.root / 'mounts'
        self.mounts.touch()
        self.calls = self.root / 'calls'
        self.init = self.root / 'init'
        self.init.write_text('#!/missing-shell\necho initialized\necho diagnostic >&2\nexit 0\n')
        self.init.chmod(0o755)
        # Only unmount is intercepted. All shell, timeout, log and file operations
        # use the real selected BusyBox; no fixture touches a host mount or /tmp lock.
        runtime = shlex.split(os.environ.get('CAMOFLASH_RUNTIME_SHELL', 'busybox ash'))[:-1]
        program = self.hack / 'bin/busybox'
        program.write_text('#!/bin/sh\nif [ "$1" = umount ]; then\n'
                           ' printf "%s\\n" "$*" >> "$CALLS"; exit 0\nfi\nexec ' +
                           shlex.join(runtime) + ' "$@"\n')
        program.chmod(0o755)
        start = STAGE.index('bootstrap_prepare_logs() {')
        end = STAGE.index('\n# Hostapd and config', start)
        self.functions = STAGE[start:end].replace('/tmp/setup.lock', str(self.lock))
        self.functions = self.functions.replace('/tmp/anyka_ipc_wrapper.sh', str(self.wrapper))
        self.functions = self.functions.replace('/usr/bin/anyka_ipc', str(self.application))
        self.functions = self.functions.replace('/proc/mounts', str(self.mounts))
        self.env = dict(os.environ, sd_path=str(self.root), hack=str(self.hack), boot_root=str(self.root),
                        init=str(self.init), CALLS=str(self.calls))

    def run_boot(self, run_init=True, short_deadline=False):
        functions = self.functions
        if short_deadline:
            functions = functions.replace('timeout -k 5 600', 'timeout -k 1 1')
        command = functions + '\nbootstrap_prepare_logs || exit 23\n'
        if run_init:
            command += 'bootstrap_run_init\n'
        shell = shlex.split(os.environ.get('CAMOFLASH_RUNTIME_SHELL', 'busybox ash'))
        return subprocess.run(shell + ['-c', command], env=self.env, capture_output=True, text=True, timeout=8)

    def test_logs_persist_and_rotate_one_previous_boot(self):
        for name in ('boot.log', 'init.log', 'init.err'):
            (self.logs / name).write_text('old ' + name)
        result = self.run_boot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('init finished with status 0', (self.logs / 'boot.log').read_text())
        self.assertEqual((self.logs / 'init.log').read_text(), 'initialized\n')
        self.assertEqual((self.logs / 'init.err').read_text(), 'diagnostic\n')
        self.assertEqual((self.logs / 'init.previous.log').read_text(), 'old init.log')
        self.assertEqual((self.logs / 'init.previous.err').read_text(), 'old init.err')
        self.assertEqual((self.logs / 'boot.previous.log').read_text(), 'old boot.log')
        # Invalid shebang above proves the explicit BusyBox shell executes init.
        self.assertEqual(result.stdout, '')

    def test_symlink_or_directory_log_is_rejected_before_truncation(self):
        outside = self.root / 'outside'
        outside.write_text('preserve')
        log = self.logs / 'init.log'
        log.symlink_to(outside)
        self.assertEqual(self.run_boot().returncode, 23)
        self.assertEqual(outside.read_text(), 'preserve')
        log.unlink()
        log.mkdir()
        self.assertEqual(self.run_boot().returncode, 23)

    def test_failed_init_releases_only_matching_bind_and_owned_lock(self):
        self.init.write_text(f'echo lock > {shlex.quote(str(self.lock))}\nexit 19\n')
        self.wrapper.write_text('our wrapper')
        self.application.write_text('our wrapper')
        self.mounts.write_text(f'/dev/fixture {self.application} vfat rw 0 0\n')
        result = self.run_boot()
        self.assertEqual(result.returncode, 19)
        self.assertFalse(self.lock.exists())
        self.assertEqual(self.calls.read_text(), f'umount {self.application}\n')
        self.calls.unlink()
        self.lock.write_text('existing')
        self.application.write_text('different')
        self.assertEqual(self.run_boot().returncode, 19)
        self.assertEqual(self.lock.read_text(), 'lock\n')
        self.assertFalse(self.calls.exists())

    def test_hung_init_times_out_and_persists_status(self):
        self.init.write_text('while :; do sleep 1; done\n')
        result = self.run_boot(short_deadline=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'init finished with status {result.returncode}', (self.logs / 'boot.log').read_text())

    def test_preexisting_dangling_setup_lock_is_not_owned(self):
        self.lock.symlink_to(self.root / 'absent')
        self.init.write_text('exit 19\n')
        self.assertEqual(self.run_boot().returncode, 19)
        self.assertTrue(self.lock.is_symlink())

    def test_handoff_sampler_is_opt_in_and_only_follows_success(self):
        helper = self.hack / 'sbin/boot_diagnostics.sh'
        helper.parent.mkdir()
        helper.write_text('printf ready > "$1/sampled"\n')
        sampled = self.hack / 'sampled'
        self.assertEqual(self.run_boot().returncode, 0)
        self.assertFalse(sampled.exists())
        (self.root / '_ht_get_log.conf').touch()
        self.assertEqual(self.run_boot().returncode, 0)
        deadline = time.monotonic() + 3
        while not sampled.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(sampled.read_text(), 'ready')
        sampled.unlink()
        self.init.write_text('exit 19\n')
        self.assertEqual(self.run_boot().returncode, 19)
        self.assertFalse(sampled.exists())
