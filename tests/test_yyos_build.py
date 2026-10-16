"""Isolated YYOS boot-kit assembly; no card, camera, firmware or network access."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('yyos_management_builder', REPO / 'tools/yyos/build-kit.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
RUN = subprocess.run


class YYOSBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yyos-management-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        for name in BUILD.FILES:
            destination = self.source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text('# synthetic payload; never execute\n')
        self.bb = self.root / 'busybox'
        self.bb.write_bytes(b'SYNTHETIC-ARM-BUSYBOX\0')
        self.bb.chmod(0o755)
        self.cc = self.root / 'fixture-gcc'
        self.cc.write_text('#!/bin/sh\nexit 99\n')
        self.cc.chmod(0o755)
        self.reader = self.root / 'fixture-readelf'
        self.reader.write_text('#!/bin/sh\nexit 99\n')
        self.reader.chmod(0o755)
        self.output = self.root / 'kit'
        self.args = SimpleNamespace(output=self.output, busybox=self.bb, cc=str(self.cc),
                                    readelf=str(self.reader), qemu=None, password_file=None, username='admin')

    def command(self, command, **kwargs):
        if command[0] != str(self.cc):
            return RUN(command, **kwargs)
        self.assertIn('-static', command)
        self.assertIn('-march=armv5te', command)
        Path(command[-1]).write_bytes(b'SYNTHETIC-NATIVE-ENTRY\0')
        return SimpleNamespace(returncode=0)

    def elf(self, path, reader):
        return {'static': True, 'cpu_arch': 'v5TEJ', 'sha256': BUILD.NOR.digest(path), 'bytes': path.stat().st_size}

    def build(self, command=None):
        with patch.object(BUILD, 'SOURCE', self.source), \
                patch.object(BUILD.NOR, 'validate_arm_elf', side_effect=self.elf), \
                patch.object(BUILD.BACKUP, 'busybox_sources', return_value=(b'GPLv2 fixture\n', {'fixture': True})), \
                patch.object(BUILD.subprocess, 'run', side_effect=command or self.command):
            return BUILD.build(self.args)

    def check_sums(self, path):
        names = set()
        for line in (path / 'SHA256SUMS').read_text().splitlines():
            checksum, name = line.split('  ', 1)
            self.assertNotIn(name, names)
            names.add(name)
            self.assertEqual(hashlib.sha256((path / name).read_bytes()).hexdigest(), checksum)
        return names

    def test_credential_free_inventory_and_checksums(self):
        self.build()
        card = self.output / 'card'
        runtime = card / 'LSCamoflash-yyos'
        self.assertEqual({p.name for p in card.iterdir()}, BUILD.ROOT_FILES | {'LSCamoflash-yyos'})
        self.assertEqual((card / 'yy_telnet_start').read_bytes(), b'')
        self.assertEqual((card / 'dump.sh').read_bytes(), (BUILD.HERE / 'boot.sh').read_bytes())
        self.assertFalse((runtime / 'httpd.conf').exists())
        manifest = json.loads((runtime / 'manifest.json').read_text())
        self.assertFalse(manifest['credentials_provisioned'])
        self.assertFalse(manifest['native_media_verified'])
        self.assertFalse(manifest['settings_write'])
        for directory in (self.output, card, runtime):
            self.check_sums(directory)
        names = {str(p.relative_to(card)) for p in card.rglob('*')}
        self.assertFalse(any('onvif_srvd' in p or 'hostapd' in p for p in names))
        self.assertIn('LSCamoflash-yyos/www/cgi-bin/recordings.cgi', names)
        self.assertIn('LSCamoflash-yyos/bin/yyos-recordings', names)
        for name in ('_ht_ap_mode.conf', '_ht_get_log.conf', 'yy_debug.ini', 'hack.sh'):
            self.assertNotIn(name, names)

    @unittest.skipUnless(shutil.which('openssl'), 'Host OpenSSL required')
    def test_site_auth_is_hashed_outside_www_and_public_checksums(self):
        password = self.root / 'private-password'
        password.write_text('SYNTHETIC-private-password-42\n')
        self.args.password_file = password
        self.build()
        runtime = self.output / 'card/LSCamoflash-yyos'
        config = (runtime / 'httpd.conf').read_text()
        self.assertRegex(config, r'^I:index.html\n/:admin:\$1\$')
        self.assertNotIn('SYNTHETIC-private-password-42', config)
        for path in self.output.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'SYNTHETIC-private-password-42', path.read_bytes())
        self.assertTrue(json.loads((runtime / 'manifest.json').read_text())['credentials_provisioned'])
        for directory in (self.output, runtime.parent, runtime):
            self.assertFalse(any('httpd.conf' in name for name in self.check_sums(directory)))

    def test_existing_files_refused_before_compiler_and_preserved(self):
        self.output.mkdir()
        (self.output / 'keep').write_bytes(b'KEEP')
        with patch.object(BUILD.NOR, 'executable') as compiler:
            with self.assertRaisesRegex(ValueError, 'empty'):
                BUILD.build(self.args)
            compiler.assert_not_called()
        self.assertEqual((self.output / 'keep').read_bytes(), b'KEEP')

    def test_output_symlink_mountpoint_and_file_refused(self):
        self.output.symlink_to(self.source, target_is_directory=True)
        for output in (self.output, self.output / 'nested', Path('/')):
            with self.subTest(output=output), self.assertRaises(ValueError):
                BUILD.output_guard(output)
        self.output.unlink()
        self.output.write_bytes(b'KEEP')
        with self.assertRaises(ValueError):
            BUILD.output_guard(self.output)
        self.assertEqual(self.output.read_bytes(), b'KEEP')

    def test_concurrent_addition_preserved(self):
        def command(argv, **kwargs):
            result = self.command(argv, **kwargs)
            self.output.mkdir(exist_ok=True)
            (self.output / 'keep').write_bytes(b'CONCURRENT')
            return result
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.build(command)
        self.assertEqual((self.output / 'keep').read_bytes(), b'CONCURRENT')

    def test_output_argument_required(self):
        result = RUN([os.sys.executable, str(BUILD.HERE / 'build-kit.py')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--output', result.stderr)

    def test_real_arm926_build(self):
        cc, bb, qemu = (os.environ.get(name) for name in ('BACKUP_ARM_CC', 'BACKUP_ARM_BUSYBOX', 'BACKUP_QEMU'))
        if not all((cc, bb, qemu)):
            self.skipTest('Set BACKUP_ARM_CC/BACKUP_ARM_BUSYBOX/BACKUP_QEMU for real ARM926 build')
        self.args.cc, self.args.busybox, self.args.qemu, self.args.readelf = cc, Path(bb), qemu, None
        BUILD.build(self.args)
        for directory in (self.output, self.output / 'card', self.output / 'card/LSCamoflash-yyos'):
            self.check_sums(directory)
        manifest = json.loads((self.output / 'card/LSCamoflash-yyos/manifest.json').read_text())
        self.assertTrue(manifest['arm926_smoke'])
        self.assertTrue(manifest['busybox']['static'])
        self.assertFalse(manifest['credentials_provisioned'])


@unittest.skipUnless(shutil.which('busybox'), 'Host BusyBox required')
class YYOSBootTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yyos-boot-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.card = self.root / 'card'
        self.runtime = self.card / 'LSCamoflash-yyos'
        (self.runtime / 'bin').mkdir(parents=True)
        self.bb = self.card / 'busybox'
        shutil.copyfile(shutil.which('busybox'), self.bb)
        self.bb.chmod(0o755)
        shutil.copyfile(self.bb, self.runtime / 'bin/busybox')
        self.marker = self.root / 'started'
        self.start = self.runtime / 'start.sh'
        self.start.write_text('#!/bin/sh\nprintf started > "' + str(self.marker) + '"\n')
        source = (BUILD.HERE / 'boot.sh').read_text()
        # Fixture-only paths and shorter timeout; production script is immutable.
        source = source.replace('/mnt/sdcard', str(self.card)).replace('in /mnt ', 'in ' + str(self.root) + ' ')
        source = source.replace('timeout -k 2 20', 'timeout -k 1 1')
        self.boot = self.root / 'boot.sh'
        self.boot.write_text(source)
        self.sums()

    def sums(self):
        (self.runtime / 'SHA256SUMS').write_text(''.join(
            BUILD.NOR.digest(self.runtime / name) + '  ' + name + '\n'
            for name in ('start.sh', 'bin/busybox')))

    def run_boot(self, root=None):
        return RUN([str(self.bb), 'sh', str(self.boot), str(self.card) if root is None else root],
                   capture_output=True, timeout=6)

    def test_wrong_sd_root_refused_before_start(self):
        self.assertEqual(self.run_boot('/').returncode, 2)
        self.assertFalse(self.marker.exists())

    def test_checksum_failure_refuses_start(self):
        self.start.write_text(self.start.read_text() + '# corrupted\n')
        self.assertNotEqual(self.run_boot().returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_start_is_bounded_and_valid_start_can_finish(self):
        self.assertEqual(self.run_boot().returncode, 0)
        self.assertEqual(self.marker.read_text(), 'started')
        self.start.write_text('#!/bin/sh\nexec "' + str(self.bb) + '" sleep 120\n')
        self.sums()
        started = time.monotonic()
        self.assertNotEqual(self.run_boot().returncode, 0)
        self.assertLess(time.monotonic() - started, 5)


if __name__ == '__main__':
    unittest.main()
