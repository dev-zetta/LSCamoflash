"""Controls kit proof and private inventory checks; no camera/card actions."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

BUILD = load('yyos_controls_management_builder_tests', REPO / 'tools/yyos/build-kit.py')
RUNTIME = load('yyos_controls_management_runtime_tests', REPO / 'tests/test_yyos_runtime.py')


class ControlsProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get('YYOS_CONTROLS_BUILD')
        if not root:
            raise unittest.SkipTest('Set YYOS_CONTROLS_BUILD to a public production build')
        cls.original = Path(root).absolute()
        cls.proof, cls.mapping = BUILD.validate_controls(cls.original)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yyos-controls-kit-proof-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'controls'
        for name, source in self.mapping.items():
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        self.proof_copy = copy.deepcopy(self.proof)

    def save_proof(self):
        (self.root / 'provenance.json').write_text(json.dumps(self.proof_copy) + '\n')

    def test_minimal_source_mapping_reconstructs_validated_production_build(self):
        proof, mapping = BUILD.validate_controls(self.root, expected_proof=self.proof)
        self.assertEqual(proof, self.proof)
        self.assertEqual(set(mapping), set(self.mapping))
        self.assertEqual(len(mapping), 68)
        self.assertFalse(any('native-control.key' in name or 'fixture' in name for name in mapping))

    def test_boolean_integer_substitutes_are_refused(self):
        for path in (('qemu', 'passed'), ('elf', 'static')):
            with self.subTest(path=path):
                self.proof_copy = copy.deepcopy(self.proof)
                self.proof_copy[path[0]][path[1]] = 1
                self.save_proof()
                with self.assertRaises(ValueError):
                    BUILD.validate_controls(self.root)

    def test_changed_core_object_or_license_is_refused(self):
        for name in ('sources/yyos_controls.c', 'objects/crypto-00.o', 'COPYING.Controls'):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.assertRaises(ValueError):
                    BUILD.validate_controls(self.root)
                path.write_bytes(original)

    def test_nonreproducible_crypto_patch_is_refused(self):
        self.proof_copy['crypto_patches'][0]['patched_sha256'] = '0' * 64
        self.save_proof()
        with self.assertRaisesRegex(ValueError, 'patches'):
            BUILD.validate_controls(self.root)

    def test_missing_object_unexpected_binary_and_runtime_proof_refused(self):
        extra = self.root / 'bin/test-fixture'
        extra.write_bytes(b'not shipped')
        with self.assertRaisesRegex(ValueError, 'unexpected binary'):
            BUILD.validate_controls(self.root)
        extra.unlink()
        self.proof_copy['objects'].pop()
        self.save_proof()
        with self.assertRaisesRegex(ValueError, '28 source/object'):
            BUILD.validate_controls(self.root)

    def test_runtime_copy_must_match_exact_build_proof(self):
        runtime = self.root.parent / 'runtime'
        (runtime / 'bin').mkdir(parents=True)
        shutil.copyfile(self.root / 'bin/yyos-controls', runtime / 'bin/yyos-controls')
        shutil.copyfile(self.root / 'COPYING.Controls', runtime / 'COPYING.Controls')
        shutil.copyfile(self.root / 'provenance.json', runtime / 'controls-provenance.json')
        BUILD.validate_controls(self.root, runtime, self.proof)
        (runtime / 'controls-provenance.json').write_text('{}\n')
        with self.assertRaisesRegex(ValueError, 'Runtime controls proof'):
            BUILD.validate_controls(self.root, runtime, self.proof)


class ControlsCGIProvenanceTests(unittest.TestCase):
    def test_actual_kit_binds_compile_flags_and_validated_clock_object(self):
        location = os.environ.get('YYOS_CONTROLS_KIT')
        if not location:
            self.skipTest('Set YYOS_CONTROLS_KIT to an actual controls-enabled management kit')
        runtime = Path(location) / 'card/LSCamoflash-yyos'
        manifest = json.loads((runtime / 'manifest.json').read_text())
        cgi = manifest['controls_cgi']
        self.assertEqual(cgi['cflags'], BUILD.BACKUP.FLAGS)
        self.assertIn('-static', cgi['cflags'])
        clock = [item for item in manifest['controls_provenance']['objects']
                 if item['object'] == 'objects/clock.o']
        self.assertEqual(len(clock), 1)
        self.assertEqual(cgi['clock_object_sha256'], clock[0]['object_sha256'])
        self.assertEqual(cgi['clock_compat_sha256'], clock[0]['source_sha256'])
        self.assertEqual(cgi['binary_sha256'], BUILD.NOR.digest(runtime / 'bin/yyos-controls-cgi'))
        self.assertEqual(cgi['source_sha256'], BUILD.NOR.digest(
            REPO / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c'))
        self.assertEqual(cgi['libc_provenance_sha256'],
                         manifest['controls_provenance']['libc']['provenance_sha256'])


@unittest.skipUnless(shutil.which('busybox') and shutil.which('openssl'), 'Host BusyBox/OpenSSL required')
class ControlsInventoryTests(unittest.TestCase):
    setUp = RUNTIME.RuntimeTests.setUp
    mount_row = RUNTIME.RuntimeTests.mount_row
    checksums = RUNTIME.RuntimeTests.checksums
    cleanup_server = RUNTIME.RuntimeTests.cleanup_server
    run_script = RUNTIME.RuntimeTests.run_script
    cgi = RUNTIME.RuntimeTests.cgi
    body = RUNTIME.RuntimeTests.body

    def verify(self):
        return subprocess.run([self.bb, 'sh', '-c', '. "$1"; verify_payload',
                               'fixture', str(self.kit / 'common.sh')],
                              capture_output=True, timeout=10)

    def add_controls(self):
        for name in BUILD.CONTROL_FILES:
            destination = self.kit / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b'synthetic public inventory; not executed\n')
        self.checksums()
        with (self.kit / 'SHA256SUMS').open('a') as stream:
            for name in BUILD.CONTROL_FILES:
                stream.write(hashlib.sha256((self.kit / name).read_bytes()).hexdigest() + '  ' + name + '\n')

    def test_complete_controls_group_and_readonly_baseline_are_accepted(self):
        self.assertEqual(self.verify().returncode, 0)
        self.add_controls()
        self.assertEqual(self.verify().returncode, 0)

    def test_status_capability_requires_complete_payload_and_private_key(self):
        def status():
            response = self.cgi()
            self.assertEqual(response.returncode, 0, response.stderr)
            self.assertNotIn('0123456789abcdef', response.stdout)
            return self.body(response)
        baseline = status()
        self.assertFalse(baseline['settings_write'])
        self.assertFalse(baseline['ptz'])
        self.assertEqual(baseline['controls'],
                         {'included': False, 'configured': False, 'jog_ms': None})
        key = self.kit / 'native-control.key'
        key.write_bytes(b'0123456789abcdef')
        self.assertFalse(status()['settings_write'])
        self.assertFalse(status()['ptz'])
        key.unlink()
        self.add_controls()
        absent = status()
        self.assertFalse(absent['settings_write'])
        self.assertFalse(absent['ptz'])
        self.assertEqual(absent['controls'],
                         {'included': True, 'configured': False, 'jog_ms': 200})
        key = self.kit / 'native-control.key'
        key.write_bytes(b'0123456789abcdef\n')
        configured = status()
        self.assertTrue(configured['settings_write'])
        self.assertTrue(configured['ptz'])
        self.assertEqual(configured['controls'],
                         {'included': True, 'configured': True, 'jog_ms': 200})
        key.write_bytes(b'invalid')
        self.assertFalse(status()['settings_write'])
        key.write_bytes(b'0123456789abcdef')
        (self.kit / 'bin/yyos-controls').write_bytes(b'tampered')
        tampered = status()
        self.assertFalse(tampered['settings_write'])
        self.assertFalse(tampered['ptz'])

    def test_partial_controls_group_is_refused(self):
        (self.kit / 'bin/yyos-controls').write_bytes(b'partial')
        self.assertNotEqual(self.verify().returncode, 0)

    def test_private_key_accepts_sixteen_ascii_bytes_with_optional_lf_only(self):
        key = self.kit / 'native-control.key'
        for value in (b'0123456789abcdef', b'0123456789abcdef\n'):
            with self.subTest(value_length=len(value)):
                key.write_bytes(value)
                result = self.verify()
                self.assertEqual(result.returncode, 0)
                self.assertEqual((result.stdout, result.stderr), (b'', b''))
                self.assertNotIn('native-control.key', (self.kit / 'SHA256SUMS').read_text())
        for value in (b'x' * 15, b'x' * 17, b'x' * 16 + b'\r\n', b'x' * 8 + b'\n' + b'x' * 7,
                      b'x' * 15 + b'\0', b'x' * 15 + b' ', b'x' * 15 + b'\x7f', b'x' * 16 + b'\n\n'):
            with self.subTest(invalid_length=len(value)):
                key.write_bytes(value)
                result = self.verify()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((result.stdout, result.stderr), (b'', b''))

    def test_key_symlink_hardlink_and_public_checksum_entry_refused(self):
        outside = self.fixture / 'outside-key'
        outside.write_bytes(b'0123456789abcdef')
        key = self.kit / 'native-control.key'
        key.symlink_to(outside)
        self.assertNotEqual(self.verify().returncode, 0)
        key.unlink()
        os.link(outside, key)
        self.assertNotEqual(self.verify().returncode, 0)
        key.unlink()
        key.write_bytes(outside.read_bytes())
        with (self.kit / 'SHA256SUMS').open('a') as stream:
            stream.write(hashlib.sha256(key.read_bytes()).hexdigest() + '  native-control.key\n')
        self.assertNotEqual(self.verify().returncode, 0)
        self.assertEqual(outside.read_bytes(), b'0123456789abcdef')


if __name__ == '__main__':
    unittest.main()
