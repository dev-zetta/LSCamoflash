"""Offline safety checks for the pinned SSH toolchain builder."""
from pathlib import Path
import importlib.util
import io
import json
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'tools/yyos/build-dropbear.py'
spec = importlib.util.spec_from_file_location('yyos_dropbear_build', SCRIPT)
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


class DropbearBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def archive(self, members):
        archive = self.root / 'source.tar.bz2'
        with tarfile.open(archive, 'w:bz2') as tar:
            for name, kind in members:
                info = tarfile.TarInfo(name)
                if kind == 'file':
                    info.size = 4
                    tar.addfile(info, io.BytesIO(b'test'))
                else:
                    info.type = tarfile.SYMTYPE
                    info.linkname = '/etc/passwd'
                    tar.addfile(info)
        return archive

    def elf(self, flags=0x05000200, machine=40, program_type=1):
        raw = bytearray(84)
        raw[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<HH', raw, 16, 2, machine)
        struct.pack_into('<I', raw, 28, 52)
        struct.pack_into('<I', raw, 36, flags)
        struct.pack_into('<HH', raw, 42, 32, 1)
        struct.pack_into('<I', raw, 52, program_type)
        path = self.root / 'binary'
        path.write_bytes(raw)
        return path

    def test_corrupt_or_unpinned_source_refused(self):
        path = self.root / 'source'
        path.write_bytes(b'not official Dropbear')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            BUILD.verify_source(path)

    def test_symlink_source_refused(self):
        target = self.root / 'source'
        target.write_bytes(b'data')
        link = self.root / 'link'
        link.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            BUILD.verify_source(link)

    def test_oversize_source_refused_before_hashing(self):
        path = self.root / 'source'
        path.write_bytes(b'12345')
        with mock.patch.object(BUILD, 'SOURCE_LIMIT', 4):
            with self.assertRaisesRegex(ValueError, 'size limit'):
                BUILD.verify_source(path)

    def test_safe_archive_regular_file_extracted(self):
        archive = self.archive([(f'dropbear-{BUILD.VERSION}/file', 'file')])
        destination = self.root / 'unpack'
        destination.mkdir()
        out = BUILD.unpack_source(archive, destination)
        self.assertEqual((out / 'file').read_bytes(), b'test')

    def test_unsafe_archive_members_never_extracted(self):
        for name, kind in [('/etc/passwd', 'file'),
                           (f'dropbear-{BUILD.VERSION}/../../escape', 'file'),
                           ('other-release/file', 'file'),
                           (f'dropbear-{BUILD.VERSION}/link', 'link')]:
            with self.subTest(name=name):
                archive = self.archive([(name, kind)])
                destination = self.root / 'unpack'
                destination.mkdir(exist_ok=True)
                with self.assertRaisesRegex(ValueError, 'archive member'):
                    BUILD.unpack_source(archive, destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_duplicate_archive_member_refused_before_writing(self):
        name = f'dropbear-{BUILD.VERSION}/file'
        archive = self.archive([(name, 'file'), (name, 'file')])
        destination = self.root / 'unpack'
        destination.mkdir()
        with self.assertRaisesRegex(ValueError, 'archive member'):
            BUILD.unpack_source(archive, destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_arm_static_soft_float_elf_accepted(self):
        self.assertTrue(BUILD.check_elf(self.elf())['static'])

    def test_dynamic_loader_or_dynamic_section_refused(self):
        for program_type in (2, 3):
            with self.subTest(program_type=program_type):
                with self.assertRaisesRegex(ValueError, 'static output'):
                    BUILD.check_elf(self.elf(program_type=program_type))

    def test_hard_float_or_other_architecture_refused(self):
        for kwargs in ({'flags': 0x05000400}, {'machine': 62}, {'flags': 0x04000200}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    BUILD.check_elf(self.elf(**kwargs))

    def test_companion_config_matches_audited_hash(self):
        self.assertEqual(BUILD.digest(SCRIPT.with_name(BUILD.CONFIG_NAME)), BUILD.CONFIG_SHA256)

    def test_nonzero_build_step_preserves_log(self):
        log = self.root / 'failure.log'
        with self.assertRaisesRegex(RuntimeError, 'exit code 7'):
            BUILD.run_logged([sys.executable, '-c', "print('failure evidence');raise SystemExit(7)"],
                             self.root, log, 3)
        self.assertIn(b'failure evidence', log.read_bytes())

    def test_existing_output_never_modified(self):
        output = self.root / 'existing'
        output.mkdir()
        (output / 'keep').write_bytes(b'original')
        result = subprocess.run([sys.executable, str(SCRIPT), '--source', '/missing',
                                 '--output', str(output)], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual((output / 'keep').read_bytes(), b'original')
        self.assertEqual(len(list(output.iterdir())), 1)

    def test_failed_input_retains_result_without_execution(self):
        source = self.root / 'corrupt'
        source.write_bytes(b'corrupt')
        output = self.root / 'failed'
        result = subprocess.run([sys.executable, str(SCRIPT), '--source', str(source),
                                 '--output', str(output)], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        evidence = json.loads((output / 'result.json').read_text())
        self.assertFalse(evidence['ok'])
        self.assertEqual(evidence['stage'], 'inputs')
        self.assertEqual(len(list(output.iterdir())), 1)

    def test_later_crypto_license_notices_preserved(self):
        source = self.root / 'source'
        for relative in ('LICENSE', 'libtomcrypt/LICENSE', 'libtommath/LICENSE'):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('upstream license\n')
        for relative in ('src/mlkem768.c', 'src/libcrux_mlkem768_sha3.h', 'src/sntrup761.c',
                         'src/ed25519.c', 'src/sshpty.c', 'src/atomicio.c'):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('/* OpenBSD marker */\n/* MIT License; Copyright holder */\n'
                            '#define CODE 1\n/* SPDX-License-Identifier: MIT */\n')
        out = self.root / 'licenses'
        BUILD.license_bundle(source, out)
        self.assertIn('MIT License; Copyright holder', out.read_text())
        self.assertIn('SPDX-License-Identifier: MIT', out.read_text())


if __name__ == '__main__':
    unittest.main()
