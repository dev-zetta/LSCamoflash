"""Credential-free combined artifact controls; all inputs are synthetic public files."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import struct
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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

    def controls_fixture(self):
        root = self.root / 'controls'
        runtime = self.management / 'card' / I.HTTP
        bridge = b'Public fixture controls C source\n'
        cgi = b'Public fixture controls CGI C source\n'
        F.write(self.repo / 'SOURCE/src/contrib/yyos-controls/yyos_controls.c', bridge)
        F.write(self.repo / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c', cgi)
        F.write(self.repo / 'tools/yyos/build-controls.py', b'Public fixture controls recipe\n')
        F.write(self.repo / 'docs/yyos-controls.md', b'Public fixture guarded controls instructions\n')
        files = {'bin/yyos-controls': b'Public fixture static controls executable',
                 'COPYING.Controls': b'Public fixture component notices',
                 'sources/yyos_controls.c': bridge, 'objects/controls.o': b'Public fixture ARM object',
                 'objects/clock.o': b'Public fixture ARM clock object'}
        proof = {'binary_sha256': hashlib.sha256(files['bin/yyos-controls']).hexdigest(),
                 'libc': self.libc, 'fixture_public_proof': True,
                 'objects': [{'object': 'objects/clock.o',
                              'object_sha256': hashlib.sha256(files['objects/clock.o']).hexdigest()}]}
        files['provenance.json'] = json.dumps(proof).encode()
        for name, data in files.items():
            F.write(root / name, data)
        for name, data in {'bin/yyos-controls': files['bin/yyos-controls'],
                           'bin/yyos-controls-cgi': b'Public fixture controls CGI executable',
                           'COPYING.Controls': files['COPYING.Controls'],
                           'controls-provenance.json': files['provenance.json'],
                           'www/cgi-bin/controls.cgi': b'#!/bin/sh\n# public fixture CGI\n'}.items():
            F.write(runtime / name, data)
        manifest = I.read_json(runtime / 'manifest.json')
        manifest['controls_provenance'] = proof
        report = {'static': True, 'sha256': I.sha(runtime / 'bin/yyos-controls-cgi')}
        manifest['helpers'] = {'yyos-controls-cgi': report}
        manifest['controls_cgi'] = {'source_sha256': I.sha(self.repo / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c'),
                                  'binary_sha256': I.sha(runtime / 'bin/yyos-controls-cgi'),
                                  'libc_provenance_sha256': self.libc['provenance_sha256'],
                                  'clock_compat_sha256': P.SSH.CLOCK_SOURCE_SHA, 'elf': report,
                                  'clock_object_sha256': proof['objects'][0]['object_sha256'],
                                  'cflags': ['-static', 'fixture-compile-flags']}
        manifest['files'] = {name: I.sha(runtime / name) for name in I.tree(runtime) - {'manifest.json', 'SHA256SUMS'}}
        F.write(runtime / 'manifest.json', json.dumps(manifest).encode())
        F.sums(runtime, set(manifest['files']) | {'manifest.json'})
        F.sums(self.management / 'card', I.tree(self.management / 'card') - {'SHA256SUMS'})
        F.sums(self.management, I.tree(self.management) - {'SHA256SUMS'})
        F.write(self.repo / 'SOURCE/src/yyos/www/cgi-bin/controls.cgi', (runtime / 'www/cgi-bin/controls.cgi').read_bytes())
        def validate(build_root, runtime=None, expected_proof=None, libc=None):
            if expected_proof != proof or libc != self.libc:
                raise ValueError('Fixture controls proof/libc mismatch')
            mapping = {}
            for name, data in files.items():
                path = I.regular(build_root / name)
                if path.read_bytes() != data:
                    raise ValueError('Fixture retained controls source/object mismatch')
                mapping[name] = path
            if (runtime / 'bin/yyos-controls').read_bytes() != files['bin/yyos-controls']:
                raise ValueError('Fixture controls runtime mismatch')
            return proof, mapping
        validator = SimpleNamespace(validate_controls=Mock(side_effect=validate),
                                    BACKUP=SimpleNamespace(FLAGS=['-static', 'fixture-compile-flags']))
        guard = patch.object(P, 'controls_builder', return_value=validator)
        guard.start(); self.addCleanup(guard.stop)
        self.args.controls_build = root
        return root, validator

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

    def test_optional_controls_retains_validated_mapping_and_revalidates_relocation(self):
        root, validator = self.controls_fixture()
        output = P.build(self.args)
        manifest = I.validate_kit(output, public=True)
        self.assertIn('controls_provenance', manifest)
        self.assertEqual((output / 'sources/controls/objects/controls.o').read_bytes(),
                         (root / 'objects/controls.o').read_bytes())
        self.assertIn('tools/yyos/build-controls.py', manifest['project_sources'])
        self.assertIn('docs/yyos-controls.md', manifest['project_sources'])
        self.assertTrue((output / 'CONTROLS.md').is_file())
        self.assertEqual((output / 'sources/yyos_controls_cgi.c').read_bytes(),
                         (self.repo / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c').read_bytes())
        self.assertIn('SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c', manifest['project_sources'])
        self.assertEqual(validator.validate_controls.call_count, 2)
        self.assertFalse((output / 'card' / I.HTTP / 'native-control.key').exists())

    def test_controls_input_is_required_exactly_when_complete_payload_is_included(self):
        self.args.controls_build = self.root / 'unknown-controls'
        with self.assertRaisesRegex(ValueError, 'matching --controls-build'):
            P.build(self.args)
        self.controls_fixture()
        self.args.controls_build = None
        with self.assertRaisesRegex(ValueError, 'matching --controls-build'):
            P.build(self.args)

    def test_controls_source_object_or_cgi_proof_mismatch_cannot_publish(self):
        root, validator = self.controls_fixture()
        (root / 'objects/controls.o').write_bytes(b'Corrupted retained object')
        with self.assertRaisesRegex(ValueError, 'source/object mismatch'):
            P.build(self.args)
        self.assertFalse(self.args.output.exists())
        runtime = self.management / 'card' / I.HTTP
        manifest = I.read_json(runtime / 'manifest.json')
        original = dict(manifest['controls_cgi'])
        for field, value in (('source_sha256', '0' * 64), ('clock_object_sha256', '0' * 64), ('cflags', [])):
            manifest['controls_cgi'] = {**original, field: value}
            F.write(runtime / 'manifest.json', json.dumps(manifest).encode())
            F.sums(runtime, set(manifest['files']) | {'manifest.json'})
            F.sums(self.management / 'card', I.tree(self.management / 'card') - {'SHA256SUMS'})
            F.sums(self.management, I.tree(self.management) - {'SHA256SUMS'})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Controls CGI differs'):
                P.build(self.args)

    def test_packaged_controls_unknown_file_or_symlink_is_refused(self):
        self.controls_fixture()
        output = P.build(self.args)
        controls = output / 'sources/controls'
        extra = controls / 'unexpected-private-file'
        extra.write_bytes(b'Never distribute this unknown file')
        with self.assertRaisesRegex(ValueError, 'unknown or missing'):
            P.validate_packaged_controls(output / 'sources', output / 'card' / I.HTTP, self.libc)
        extra.unlink()
        link = controls / 'objects/link.o'
        link.symlink_to(controls / 'objects/controls.o')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            P.validate_packaged_controls(output / 'sources', output / 'card' / I.HTTP, self.libc)


if __name__ == '__main__':
    unittest.main()
