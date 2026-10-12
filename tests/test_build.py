import hashlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_SCRIPT = ROOT / 'SOURCE/src/bin/download-file.sh'


class SourceDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload = self.root / 'payload'
        self.payload.write_bytes(b'archive payload\x00\x01\n')
        self.destination = self.root / 'downloads/archive.tar.gz'
        self.destination.parent.mkdir()
        tools = self.root / 'bin'
        tools.mkdir()
        curl = tools / 'curl'
        curl.write_text('''#!/bin/sh
set -eu
printf 'called\\n' >> "$CURL_CALL_LOG"
while [ "$#" -gt 0 ]; do
    if [ "$1" = --output ]; then
        cp "$DOWNLOAD_PAYLOAD" "$2"
        exit "${CURL_EXIT_CODE:-0}"
    fi
    shift
done
exit 2
''')
        curl.chmod(0o755)
        self.log = self.root / 'curl.log'
        self.env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                        DOWNLOAD_PAYLOAD=str(self.payload), CURL_CALL_LOG=str(self.log))

    def download(self):
        return subprocess.run([str(DOWNLOAD_SCRIPT), 'https://example.invalid/archive.tar.gz',
                               str(self.destination)], env=self.env, capture_output=True, text=True)

    def pointer(self, digest=None):
        digest = digest or hashlib.sha256(self.payload.read_bytes()).hexdigest()
        return f'version https://git-lfs.github.com/spec/v1\noid sha256:{digest}\nsize {self.payload.stat().st_size}\n'

    def test_missing_archive_is_downloaded(self):
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.destination.read_bytes(), self.payload.read_bytes())

    def test_lfs_pointer_is_verified_and_replaced(self):
        self.destination.write_text(self.pointer())
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.destination.read_bytes(), self.payload.read_bytes())

    def test_hash_mismatch_preserves_pointer_and_removes_partial_download(self):
        pointer = self.pointer('0' * 64)
        self.destination.write_text(pointer)
        result = self.download()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.destination.read_text(), pointer)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_network_failure_preserves_pointer(self):
        pointer = self.pointer()
        self.destination.write_text(pointer)
        self.env['CURL_EXIT_CODE'] = '22'
        result = self.download()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.destination.read_text(), pointer)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_hydrated_archive_does_not_download_again(self):
        self.destination.write_bytes(self.payload.read_bytes())
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())

    def test_server_returning_an_lfs_pointer_is_rejected(self):
        self.payload.write_text(self.pointer())
        result = self.download()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_packages_extracts_declared_sources_and_ignores_unrelated_lfs_pointers(self):
        with tarfile.open(self.payload, 'w:gz') as archive:
            content = b'package source\n'
            entry = tarfile.TarInfo('example-1.0/README')
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
        unrelated = self.destination.parent / 'unused.zip'
        unrelated.write_text(self.pointer())
        result = subprocess.run([
            'make', '-f', str(ROOT / 'SOURCE/Makefile'),
            f'ROOT_DIR={self.root}', f'DOWNLOAD_DIR={self.destination.parent}',
            f'SRC_DIR={ROOT / "SOURCE/src"}',
            'URLS=https://example.invalid/archive.tar.gz', 'packages',
        ], cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'packages/example-1.0/README').read_bytes(), content)
        self.assertTrue(unrelated.read_text().startswith('version https://git-lfs'))

    def test_corrupt_archive_does_not_mark_packages_ready(self):
        result = subprocess.run([
            'make', '-f', str(ROOT / 'SOURCE/Makefile'),
            f'ROOT_DIR={self.root}', f'DOWNLOAD_DIR={self.destination.parent}',
            f'SRC_DIR={ROOT / "SOURCE/src"}',
            'URLS=https://example.invalid/archive.tar.gz', 'packages',
        ], cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'packages/cacert.pem').exists())

    def test_empty_response_is_rejected(self):
        self.payload.write_bytes(b'')
        result = self.download()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.destination.exists())


class BuildVersionTests(unittest.TestCase):
    def test_creating_build_directory_does_not_change_source_version(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / 'version.txt').write_text('1.02.0003\n')
            result = subprocess.run(['make', '-f', str(ROOT / 'SOURCE/Makefile'),
                                     str(source / 'build')], cwd=source,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((source / 'build').is_dir())
            self.assertEqual((source / 'version.txt').read_text(), '1.02.0003\n')


if __name__ == '__main__':
    unittest.main()
