"""Credential-free combined artifact controls; all inputs are synthetic public files."""
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import struct
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


P = load('yyos_package_tests', REPO / 'tools/yyos/package-kit.py')
F = load('yyos_package_test_files', REPO / 'tests/test_yyos_install.py')
I = P.INSTALL


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yyos-package-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.base = self.root / 'base'
        F.fixture_kit(self.base)
        self.management = self.root / 'management'
        self.ssh = self.root / 'ssh'
        self.musl = self.root / 'musl'
        self.dropbear = self.root / 'dropbear'
        self.musl.mkdir(); self.dropbear.mkdir()
        for name in ('musl-1.2.6.tar.gz', 'COPYING.musl', 'GCC-COPYING3', 'GCC-COPYING.RUNTIME', 'provenance.json'):
            F.write(self.musl / name, ('Fixture public musl ' + name).encode())
        self.libc = {'name': 'musl', 'version': '1.2.6',
                     'source_archive_sha256': I.sha(self.musl / 'musl-1.2.6.tar.gz'),
                     'license_sha256': I.sha(self.musl / 'COPYING.musl'),
                     'provenance_sha256': I.sha(self.musl / 'provenance.json'),
                     'gcc_runtime_notices': {name: I.sha(self.musl / name) for name in ('GCC-COPYING3', 'GCC-COPYING.RUNTIME')}}
        original = b'void gettime_wrapper(struct timespec *now) {\n\tstruct timeval tv;\n}\n'
        with tarfile.open(self.dropbear / 'dropbear-2026.94.tar.bz2', 'w:bz2') as archive:
            entry = tarfile.TarInfo('dropbear-2026.94/src/dbutil.c'); entry.size = len(original)
            archive.addfile(entry, io.BytesIO(original))
        obj = bytearray(52); obj[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<HHI', obj, 16, 1, 40, 1); struct.pack_into('<I', obj, 36, 0x05000200)
        F.write(self.dropbear / 'yyos-clock-compat.o', obj)
        clock_tree = self.root / 'clock-source'
        F.write(clock_tree / 'src/dbutil.c', original)
        builder = load('yyos_package_clock_fixture', REPO / 'tools/yyos/build-dropbear.py')
        self.proof = {'libc': self.libc, 'cflags': '-DLSCAMOFLASH_YYOS_CLOCK_COMPAT=1',
                      'yyos_clock_patch': builder.patch_clock_fallback(clock_tree),
                      'yyos_clock_compat': {'source_sha256': P.SSH.CLOCK_SOURCE_SHA,
                        'object_sha256': I.sha(self.dropbear / 'yyos-clock-compat.o'),
                        'kernel_time_abi': 'ARM EABI signed time32 converted to libc time64',
                        'clock_source': 'requested POSIX clock, including monotonic', 'timeouts_disabled': False}}
        F.write(self.dropbear / 'provenance.json', json.dumps(self.proof).encode())
        (self.management / 'card').mkdir(parents=True)
        for name in I.ROOT_FILES - {'SHA256SUMS', 'yyos-http-boot.sh'}:
            shutil.copyfile(self.base / 'card' / name, self.management / 'card' / name)
        shutil.copytree(self.base / 'card' / I.HTTP, self.management / 'card' / I.HTTP)
        shutil.copytree(self.base / 'card' / I.SSH, self.ssh / 'card' / I.SSH)
        for root, folder in ((self.management, I.HTTP), (self.ssh, I.SSH)):
            runtime = root / 'card' / folder
            (runtime / 'bin/busybox').write_bytes(b'Fixture identical static BusyBox')
            if folder == I.SSH:
                with (runtime / 'COPYING.Dropbear').open('ab') as stream:
                    for name in ('COPYING.musl', 'GCC-COPYING3', 'GCC-COPYING.RUNTIME'):
                        stream.write((self.musl / name).read_bytes())
            manifest = I.read_json(runtime / 'manifest.json')
            manifest.update(arm926_smoke=True, credentials_provisioned=False)
            if folder == I.SSH:
                manifest['dropbear_build'] = self.proof
            manifest['files'] = {name: I.sha(runtime / name) for name in manifest['files']}
            F.write(runtime / 'manifest.json', json.dumps(manifest).encode())
            F.sums(runtime, set(manifest['files']) | {'manifest.json'})
            source = self.repo / 'SOURCE/src' / ('yyos-ssh' if folder == I.SSH else 'yyos')
            shutil.copytree(runtime, source)
        (self.management / 'card/busybox').write_bytes(b'Fixture identical static BusyBox')
        boot = b'#!/bin/sh\nexit 0\n'
        F.write(self.repo / 'tools/yyos/boot.sh', boot)
        (self.management / 'card/dump.sh').write_bytes(boot)
        F.sums(self.management / 'card', I.tree(self.management / 'card') - {'SHA256SUMS'})
        F.write(self.ssh / 'boot/normal-http-boot.sh', boot)
        F.write(self.ssh / 'boot/boot.sh', P.SSH.boot_wrapper(I.sha(self.management / 'card/dump.sh')))
        F.write(self.ssh / 'manifest.json', b'{"private_output":false}')
        F.sums(self.ssh, I.tree(self.ssh) - {'SHA256SUMS'})
        F.write(self.management / 'manifest.json', b'{}')
        F.sums(self.management, I.tree(self.management) - {'SHA256SUMS'})
        for name in ('package-kit.py', 'install-kit.py', 'build-kit.py', 'build-ssh-kit.py',
                     'build-dropbear.py', 'build-musl.py', 'dropbear-localoptions.h', 'convert-recording.py',
                     'recording-requirements.txt'):
            F.write(self.repo / 'tools/yyos' / name, b'Fixture public source\n')
        F.write(self.repo / 'tools/yyos/build-dropbear.py', (REPO / 'tools/yyos/build-dropbear.py').read_bytes())
        F.write(self.repo / 'tools/yyos/yyos-clock-compat.c', (REPO / 'tools/yyos/yyos-clock-compat.c').read_bytes())
        F.write(self.repo / 'docs/yyos-setup.md', b'Fixture setup instructions\n')
        F.write(self.repo / 'docs/yyos-recordings.md', b'Fixture converter instructions\n')
        F.write(self.repo / 'SOURCE/version.txt', b'2.00.0000\n')
        self.proof['build_script_sha256'] = I.sha(self.repo / 'tools/yyos/build-dropbear.py')
        F.write(self.musl / 'provenance.json', json.dumps({'name': 'musl', 'version': '1.2.6',
                'build_script_sha256': I.sha(self.repo / 'tools/yyos/build-musl.py')}).encode())
        self.libc['provenance_sha256'] = I.sha(self.musl / 'provenance.json')
        F.write(self.dropbear / 'provenance.json', json.dumps(self.proof).encode())
        runtime = self.ssh / 'card' / I.SSH
        manifest = I.read_json(runtime / 'manifest.json')
        manifest['dropbear_build'] = self.proof
        F.write(runtime / 'manifest.json', json.dumps(manifest).encode())
        F.sums(runtime, set(manifest['files']) | {'manifest.json'})
        F.sums(self.ssh, I.tree(self.ssh) - {'SHA256SUMS'})
        self.args = SimpleNamespace(management_kit=self.management, ssh_kit=self.ssh, musl_build=self.musl,
                                    dropbear_build=self.dropbear, output=self.root / 'out', readelf='/bin/true')
        for guard in (patch.object(P, 'REPO', self.repo),
                      patch.object(P.SSH, 'SOURCE_SHA', I.sha(self.dropbear / 'dropbear-2026.94.tar.bz2')),
                      patch.object(P.SSH, 'provenance', return_value=self.proof),
                      patch.object(P.SSH.NOR, 'validate_arm_elf', side_effect=lambda path, reader: {'static': True, 'cpu_arch': 'v5TEJ', 'sha256': I.sha(path), 'bytes': path.stat().st_size})):
            guard.start(); self.addCleanup(guard.stop)

    def test_combined_inventory_disabled_ssh_sources_and_checksums(self):
        output = P.build(self.args)
        manifest = I.validate_kit(output, public=True)
        self.assertTrue(manifest['credential_free'])
        self.assertEqual({p.name for p in (output / 'card').iterdir()}, I.ROOT_FILES | {I.HTTP, I.SSH})
        self.assertTrue((output / 'sources/musl-1.2.6.tar.gz').is_file())
        self.assertTrue((output / 'sources/GCC-COPYING.RUNTIME').is_file())
        for name in I.SITE:
            self.assertFalse((output / 'card' / name).exists())
        self.assertEqual((output / 'card/yyos-http-boot.sh').read_bytes(), (self.management / 'card/dump.sh').read_bytes())

    def test_private_ssh_or_web_inputs_are_rejected(self):
        path = self.ssh / 'card' / I.SSH / 'ssh.enabled'
        path.write_bytes(b'enabled\n')
        with self.assertRaises(ValueError):
            P.build(self.args)
        path.unlink()
        F.write(self.management / 'card' / I.HTTP / 'httpd.conf', F.AUTH)
        with self.assertRaises(ValueError):
            P.build(self.args)

    def test_missing_or_changed_runtime_notice_is_rejected(self):
        (self.musl / 'GCC-COPYING.RUNTIME').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            P.build(self.args)

    def test_missing_clock_policy_or_corrupted_clock_object_is_rejected(self):
        patch = self.proof.pop('yyos_clock_patch')
        with self.assertRaises(ValueError):
            P.build(self.args)
        self.proof['yyos_clock_patch'] = patch
        (self.dropbear / 'yyos-clock-compat.o').write_bytes(b'wrong object')
        with self.assertRaises(ValueError):
            P.build(self.args)

    def test_stale_dropbear_or_coherently_rehashed_musl_recipe_is_rejected(self):
        original = self.proof['build_script_sha256']
        self.proof['build_script_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Dropbear.*build recipe'):
            P.build(self.args)
        self.proof['build_script_sha256'] = original
        proof = I.read_json(self.musl / 'provenance.json')
        proof['build_script_sha256'] = '0' * 64
        F.write(self.musl / 'provenance.json', json.dumps(proof).encode())
        self.libc['provenance_sha256'] = I.sha(self.musl / 'provenance.json')
        with self.assertRaisesRegex(ValueError, 'Musl.*build recipe'):
            P.build(self.args)

    def test_wrong_libc_source_change_and_nonempty_output_refused(self):
        self.libc['name'] = 'uclibc'
        with self.assertRaises(ValueError):
            P.build(self.args)
        self.libc['name'] = 'musl'
        path = self.repo / 'SOURCE/src/yyos/start.sh'
        original = path.read_bytes(); path.write_bytes(b'new source')
        with self.assertRaises(ValueError):
            P.build(self.args)
        path.write_bytes(original)
        self.args.output.mkdir()
        F.write(self.args.output / 'keep', b'preserve')
        with self.assertRaises(ValueError):
            P.build(self.args)
        self.assertEqual((self.args.output / 'keep').read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
