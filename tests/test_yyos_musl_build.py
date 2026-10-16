"""Bounds and corruption controls for the redistributable static libc builder."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'tools/yyos/build-musl.py'
spec = importlib.util.spec_from_file_location('yyos_musl_build', SCRIPT)
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


class MuslBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def archive(self, names):
        archive = self.root / 'source.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for name, link in names:
                item = tarfile.TarInfo(name)
                if link:
                    item.type, item.linkname = tarfile.SYMTYPE, '/etc/passwd'
                    tar.addfile(item)
                else:
                    item.size = 4
                    tar.addfile(item, io.BytesIO(b'test'))
        return archive

    def test_unsafe_archive_rejected_before_any_write(self):
        for name, link in [('musl-1.2.6/../../escape', False), ('/escape', False),
                           ('musl-1.2.6/link', True), ('other/file', False)]:
            with self.subTest(name=name):
                destination = self.root / 'unpack'
                destination.mkdir(exist_ok=True)
                with self.assertRaises(ValueError):
                    BUILD.unpack(self.archive([(name, link)]), destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_duplicate_source_member_rejected(self):
        name = 'musl-1.2.6/file'
        with self.assertRaises(ValueError):
            BUILD.unpack(self.archive([(name, False), (name, False)]), self.root / 'out')
        self.assertFalse((self.root / 'out').exists())

    def test_static_inventory_rejects_missing_libc_and_symlink(self):
        install = self.root / 'install'
        install.mkdir()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            BUILD.inventory(install)
        (install / 'escape').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            BUILD.inventory(install)

    def test_corrupt_source_retains_failure_without_build(self):
        archive = self.root / 'bad.tar.gz'
        archive.write_bytes(b'bad')
        output = self.root / 'failed'
        run = subprocess.run([sys.executable, str(SCRIPT), '--source', str(archive), '--output', str(output)],
                             capture_output=True, timeout=5)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(sorted(x.name for x in output.iterdir()), ['result.json'])

    def test_existing_output_preserved(self):
        output = self.root / 'existing'
        output.mkdir()
        (output / 'keep').write_bytes(b'original')
        run = subprocess.run([sys.executable, str(SCRIPT), '--source', '/missing', '--output', str(output)],
                             capture_output=True, timeout=5)
        self.assertEqual(run.returncode, 2)
        self.assertEqual((output / 'keep').read_bytes(), b'original')

    def test_unproven_musl_compiler_override_rejected(self):
        musl = self.root / 'musl'
        musl.mkdir()
        (musl / 'provenance.json').write_text('{"name":"musl","version":"1.2.6"}')
        with self.assertRaisesRegex(ValueError, 'tested musl'):
            BUILD.COMMON.validate_musl(musl)


if __name__ == '__main__':
    unittest.main()
