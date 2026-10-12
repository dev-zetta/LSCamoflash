"""Exercise staged update copies using fixture mounts and temporary files only."""
import os
from pathlib import Path
import subprocess
import shutil
import shlex
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATE = (ROOT / 'SOURCE/src/sdcard/mmcblk0p2/HACK/sbin/update.sh').read_text()
BOOTSTRAP = (ROOT / 'SOURCE/src/sdcard/mmcblk0p1/bootstrap.sh').read_text()
RUNTIME_SHELL = shlex.split(os.environ.get('CAMOFLASH_RUNTIME_SHELL', '/bin/sh'))


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='camoflash-update-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sd = self.root / 'sd'
        self.boot = self.root / 'boot'
        self.staged = self.sd / 'UPDATE'
        self.log = self.sd / 'HACK/var/log'
        self.overlay = self.sd / 'OVERLAY'
        for path in (self.boot, self.staged / 'mmcblk0p1', self.staged / 'mmcblk0p2/HACK/sbin', self.log, self.overlay):
            path.mkdir(parents=True, exist_ok=True)
        (self.staged / 'mmcblk0p1/hostapd').write_text('new boot hook')
        (self.staged / 'mmcblk0p2/HACK/sbin/init.sh').write_text('new init')
        (self.overlay / 'retain-on-error').touch()
        self.mounts = self.root / 'mounts'
        self.mounts.touch()
        self.tools = self.root / 'tools'
        self.tools.mkdir()
        self.calls = self.root / 'calls'
        self.executable(self.tools / 'mount', '#!/bin/sh\necho mount >> "$CALL_LOG"\nexit "${MOUNT_STATUS:-0}"\n')
        self.executable(self.tools / 'umount', '#!/bin/sh\necho umount >> "$CALL_LOG"\nexit 0\n')
        self.executable(self.tools / 'cp', '#!/bin/sh\necho copy >> "$CALL_LOG"\nif [ "${COPY_PARTIAL:-0}" = 1 ]; then for target in "$@"; do :; done; echo partial > "$target"; exit 1; fi\n[ "${COPY_STATUS:-0}" = 0 ] || exit "$COPY_STATUS"\nexec /bin/cp "$@"\n')
        self.env = dict(os.environ, PATH=str(self.tools) + ':' + os.environ['PATH'], VERSION='1.03.2412',
                        sys_mnt=str(self.boot), sd_path=str(self.sd), sd_update=str(self.staged),
                        sd_log=str(self.log), sd_overlay=str(self.overlay), cp=str(self.tools / 'cp'), rm='rm', mv='mv', mkdir='mkdir', sync='true',
                        UPDATE_MOUNT=str(self.tools / 'mount'), UPDATE_UMOUNT=str(self.tools / 'umount'),
                        CALL_LOG=str(self.calls))
        start = UPDATE.index('# Copy update files through')
        self.block = UPDATE[start:UPDATE.index('\nagent=', start)].replace('/proc/mounts', str(self.mounts))
        self.block = self.block.replace('&& mount -t', '&& "$UPDATE_MOUNT" -t').replace('umount "$sys_mnt"', '"$UPDATE_UMOUNT" "$sys_mnt"')
        self.device = self.root / 'mmcblk0p1'
        self.block = self.block.replace('/dev/mmcblk0p1\n', str(self.device) + '\n')
        self.block = self.block.replace('[ -b "$update_boot_device" ]', '[ -f "$update_boot_device" ]')

    @staticmethod
    def executable(path, text):
        path.write_text(text)
        path.chmod(0o755)

    def run_update(self):
        return subprocess.run([*RUNTIME_SHELL, '-c', self.block], env=self.env,
                              capture_output=True, text=True, timeout=4)

    def assert_retained(self):
        self.assertTrue(self.staged.is_dir())
        self.assertTrue((self.overlay / 'retain-on-error').exists())
        self.assertNotIn('Update installed:', (self.log / 'update.log').read_text())

    def test_whole_card_bind_receives_boot_and_runtime_files(self):
        self.mounts.write_text(f'tmpfs {self.boot} tmpfs rw 0 0\n/dev/mmcblk0 {self.sd} vfat rw 0 0\n')
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.sd / 'hostapd').read_text(), 'new boot hook')
        self.assertEqual((self.sd / 'HACK/sbin/init.sh').read_text(), 'new init')
        self.assertFalse((self.boot / 'hostapd').exists())
        self.assertFalse(self.staged.exists())
        self.assertFalse(self.overlay.exists())
        self.assertEqual(self.calls.read_text().splitlines(), ['copy', 'copy'])

    def test_two_partition_update_uses_mounted_first_partition(self):
        self.mounts.write_text(f'/dev/mmcblk0p1 {self.boot} vfat rw 0 0\n/dev/mmcblk0p2 {self.sd} vfat rw 0 0\n')
        self.assertEqual(self.run_update().returncode, 0)
        self.assertEqual((self.boot / 'hostapd').read_text(), 'new boot hook')
        self.assertEqual((self.sd / 'HACK/sbin/init.sh').read_text(), 'new init')

    def test_failed_mount_never_copies_into_tmpfs_or_discards_update(self):
        self.env['MOUNT_STATUS'] = '1'
        self.device.touch()
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assert_retained()
        self.assertFalse((self.boot / 'hostapd').exists())
        self.assertEqual(self.calls.read_text(), 'mount\n')

    def test_failed_copy_or_sync_retains_staged_update_and_overlay(self):
        self.mounts.write_text(f'/dev/mmcblk0p1 {self.boot} vfat rw 0 0\n')
        self.env['COPY_STATUS'] = '1'
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assert_retained()
        self.env['COPY_STATUS'] = '0'
        self.env['sync'] = 'false'
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assert_retained()

    def test_failed_pre_hook_stops_copy_and_retains_update(self):
        self.mounts.write_text(f'/dev/mmcblk0p1 {self.boot} vfat rw 0 0\n')
        self.executable(self.staged / 'update-pre.sh', '#!/bin/sh\nexit 1\n')
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assert_retained()
        self.assertFalse(self.calls.exists())

    @unittest.skipUnless(shutil.which('busybox'), 'host BusyBox required')
    def test_atomic_update_replaces_executing_boot_and_runtime_busybox(self):
        self.mounts.write_text(f'/dev/mmcblk0 {self.sd} vfat rw 0 0\n')
        installed = [self.sd / 'busybox', self.sd / 'HACK/bin/busybox']
        processes = []
        try:
            for number, path in enumerate(installed):
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(shutil.which('busybox'), path)
                staged = self.staged / ('mmcblk0p1/busybox' if number == 0 else 'mmcblk0p2/HACK/bin/busybox')
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(path.read_bytes() + b'updated executable fixture')
                staged.chmod(0o755)
                ready = self.root / f'ready{number}'
                process = subprocess.Popen([str(path), 'sh', '-c', 'echo ready > "$1"; exec "$2" sleep 30', 'sh', str(ready), str(path)])
                processes.append(process)
                for _ in range(100):
                    if ready.exists():
                        break
                    import time
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
            result = self.run_update()
            self.assertEqual(result.returncode, 0, result.stderr)
            for path, process in zip(installed, processes):
                self.assertTrue(path.read_bytes().endswith(b'updated executable fixture'))
                self.assertIsNone(process.poll())
                self.assertEqual(subprocess.run([str(path), 'true']).returncode, 0)
            self.assertFalse(self.staged.exists())
        finally:
            for process in processes:
                process.terminate()
                process.wait(timeout=3)

    def test_partial_copy_is_cleaned_and_can_retry_in_same_process(self):
        helper = self.block[:self.block.index('if [ -d "$sd_update" ]; then')]
        script = helper + r'''
COPY_PARTIAL=1
export COPY_PARTIAL
update_copy_tree "$sd_update/mmcblk0p1" "$sys_mnt" && exit 90
COPY_PARTIAL=0
export COPY_PARTIAL
update_copy_tree "$sd_update/mmcblk0p1" "$sys_mnt"
'''
        result = subprocess.run([*RUNTIME_SHELL, '-c', script], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.boot / 'hostapd').read_text(), 'new boot hook')
        self.assertEqual([path.name for path in self.boot.iterdir()], ['hostapd'])
        self.assertTrue((self.staged / 'mmcblk0p1/hostapd').exists())

    def run_cold_boot_update(self, custom=''):
        """Run bootstrap's real configuration boundary and the whole updater.

        Only physical mount input and command implementations are substituted.
        No inherited runtime configuration or command variables are supplied.
        """
        hack = self.sd / 'HACK'
        etc = hack / 'etc'
        etc.mkdir(parents=True, exist_ok=True)
        (etc / 'version.txt').write_text('1.03.2412\n')
        settings = {
            'sd_path': str(self.sd), 'sd_update': str(self.staged),
            'sd_log': str(self.log), 'sd_overlay': str(self.overlay),
            'sd_bin': str(hack / 'bin'), 'sys_bin': str(self.root / 'stock/bin'),
            'sys_mnt': str(self.boot), 'update_url': '',
        }
        conf = etc / 'hack.conf'
        conf.write_text(''.join(f'export {key}={shlex.quote(value)}\n'
                               for key, value in settings.items()))
        custom_conf = etc / 'hack_custom.conf'
        custom_conf.write_text(custom)
        commands = etc / 'commands.conf'
        commands.write_text(
            f'[ "$busybox_hack" = {shlex.quote(str(hack / "bin/busybox"))} ] || exit 97\n'
            f'[ "$busybox_firmware" = {shlex.quote(str(self.root / "stock/bin/busybox"))} ] || exit 98\n'
            f'export cp={shlex.quote(str(self.tools / "cp"))}\n'
            'export mkdir=mkdir mv=mv rm=rm sync=true\n')
        body = self.root / 'updater-body.sh'
        body.write_text(UPDATE.replace('/proc/mounts', str(self.mounts)))
        updater = hack / 'sbin/update.sh'
        updater.parent.mkdir(parents=True, exist_ok=True)
        # Run the full updater under the selected shell, including optional ARM
        # BusyBox/QEMU, instead of accidentally using the host shebang in tests.
        self.executable(updater, '#!/bin/sh\nexec ' + shlex.join(RUNTIME_SHELL) +
                        ' ' + shlex.quote(str(body)) + ' "$@"\n')
        start = BOOTSTRAP.index('\t# Apply staged updates before')
        end = BOOTSTRAP.index('\n\t# Execute pre_init_async.sh', start)
        block = BOOTSTRAP[start:end]
        block += '\nprintf "custom-hook\\ninit\\n" > "$BOOT_CONTINUED"\n'
        block += '[ -z "${sd_update+x}" ] && [ -z "${cp+x}" ] && [ -z "${update_url+x}" ]\n'
        env = {
            'PATH': str(self.tools) + ':/usr/bin:/bin',
            'CALL_LOG': str(self.calls), 'BOOT_CONTINUED': str(self.root / 'continued'),
            'hack': str(hack), 'hack_conf': str(conf),
            'hack_custom_conf': str(custom_conf), 'commands_conf': str(commands),
            'update': str(updater), 'device_uid': 'fixture-device',
        }
        # The log directory does not exist until bootstrap creates it.
        shutil.rmtree(self.log)
        return subprocess.run([*RUNTIME_SHELL, '-c', block], env=env,
                              capture_output=True, text=True, timeout=5)

    def test_cold_boot_applies_whole_updater_without_inherited_settings_or_url(self):
        self.mounts.write_text(f'/dev/mmcblk0 {self.sd} vfat rw 0 0\n')
        result = self.run_cold_boot_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.sd / 'hostapd').read_text(), 'new boot hook')
        self.assertEqual((self.sd / 'HACK/sbin/init.sh').read_text(), 'new init')
        self.assertFalse(self.staged.exists())
        self.assertIn('Update installed:', (self.log / 'update-last.log').read_text())
        self.assertEqual((self.root / 'continued').read_text(), 'custom-hook\ninit\n')

    def test_cold_boot_stops_before_hooks_and_init_after_partial_install_failure(self):
        self.mounts.write_text(f'/dev/mmcblk0p1 {self.boot} vfat rw 0 0\n')
        (self.sd / 'HACK/sbin').mkdir()
        (self.sd / 'HACK/sbin/init.sh').write_text('old init')
        self.executable(self.tools / 'cp', '''#!/bin/sh
echo copy >> "$CALL_LOG"
[ "$(grep -c '^copy$' "$CALL_LOG")" -ne 2 ] || exit 1
exec /bin/cp "$@"
''')
        result = self.run_cold_boot_update()
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.boot / 'hostapd').read_text(), 'new boot hook')
        self.assertEqual((self.sd / 'HACK/sbin/init.sh').read_text(), 'old init')
        self.assert_retained()
        self.assertFalse((self.root / 'continued').exists())
        self.assertIn('staged update failed', result.stderr)
        self.assertIn(str(self.log / 'update.log'), result.stderr)

    def test_cold_boot_without_stage_does_not_contact_unavailable_update_url(self):
        shutil.rmtree(self.staged)
        network_called = self.root / 'network-called'
        self.executable(self.tools / 'curl',
                        '#!/bin/sh\necho unexpected > ' + shlex.quote(str(network_called)) + '\nexit 1\n')
        result = self.run_cold_boot_update('export update_url="https://127.0.0.1/unavailable"\nexport curl=curl\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(network_called.exists())
        self.assertFalse(self.calls.exists())
        self.assertTrue((self.root / 'continued').exists())

    def test_cold_boot_honors_trusted_custom_update_and_log_paths(self):
        self.mounts.write_text(f'/dev/mmcblk0 {self.sd} vfat rw 0 0\n')
        custom_stage = self.sd / 'CUSTOM_UPDATE'
        custom_log = self.sd / 'HACK/var/custom-log'
        self.staged.rename(custom_stage)
        custom = (f'export sd_update={shlex.quote(str(custom_stage))}\n'
                  f'export sd_log={shlex.quote(str(custom_log))}\n')
        result = self.run_cold_boot_update(custom)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(custom_stage.exists())
        self.assertIn('Update installed:', (custom_log / 'update-last.log').read_text())
        self.assertTrue((self.root / 'continued').exists())
