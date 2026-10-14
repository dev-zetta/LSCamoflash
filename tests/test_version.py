"""Check release versions with temporary files and harmless updater commands."""
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUMPER = ROOT / 'SOURCE/src/bin/update-version.sh'
UPDATER = ROOT / 'SOURCE/src/sdcard/mmcblk0p2/HACK/sbin/update.sh'
UPDATE = UPDATER.read_text()
FUNCTIONS = UPDATE[UPDATE.index('# Version parsing is shared'):UPDATE.index('\nVERSION=$(cat')]
RUNTIME_SHELL = shlex.split(os.environ.get('CAMOFLASH_RUNTIME_SHELL', '/bin/sh'))
spec = importlib.util.spec_from_file_location('version_build_checker', ROOT / 'SOURCE/src/bin/verify-build.py')
CHECKER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CHECKER)


class VersionBumpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='camoflash-version-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.version = self.root / 'version.txt'

    def bump(self, version, *arguments):
        self.version.write_text(version + '\n')
        return subprocess.run(['bash', str(BUMPER), *arguments], cwd=self.root,
                              capture_output=True, text=True, timeout=5)

    def test_major_bump_resets_lower_fields_and_accepts_later_majors(self):
        for before, after in (('1.03.2413', '2.00.0000'), ('2.09.9999', '3.00.0000'),
                              ('9.99.9999', '10.00.0000'),
                              ('99999999999999999999.01.0002', '100000000000000000000.00.0000')):
            with self.subTest(version=before):
                result = self.bump(before, '--major')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.version.read_text(), after + '\n')

    def test_minor_and_revision_fields_are_decimal(self):
        for before, argument, after in (('2.08.0099', '--minor', '2.09.0000'),
                                        ('2.09.0099', '--revision', '2.09.0100'),
                                        ('2.00.0000', '--revision', '2.00.0001')):
            with self.subTest(version=before, argument=argument):
                result = self.bump(before, argument)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.version.read_text(), after + '\n')

    def test_invalid_input_and_overflow_preserve_file(self):
        for version, argument in (('0.00.0000', '--major'), ('01.00.0000', '--major'),
                                  ('2.0.0000', '--revision'), ('2.00.00000', '--revision'),
                                  ('2.00.0000 extra', '--major'), ('2.00.0000\n3.00.0000', '--major'),
                                  ('2.99.0012', '--minor'), ('2.00.9999', '--revision')):
            with self.subTest(version=version, argument=argument):
                result = self.bump(version, argument)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.version.read_text(), version + '\n')

    def test_invalid_arguments_never_rewrite_or_create_version(self):
        for arguments in ((), ('--unknown',), ('--major', '--minor')):
            result = self.bump('2.00.0000', *arguments)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(self.version.read_text(), '2.00.0000\n')
        self.version.unlink()
        result = subprocess.run(['bash', str(BUMPER), '--revision'], cwd=self.root,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.version.exists())

    def test_make_targets_use_explicit_source_root(self):
        source = self.root / 'source'
        elsewhere = self.root / 'elsewhere'
        source.mkdir(); elsewhere.mkdir()
        (source / 'version.txt').write_text('1.03.2413\n')
        (elsewhere / 'version.txt').write_text('9.99.9999\n')
        command = ['make', '-f', str(ROOT / 'SOURCE/Makefile'), f'ROOT_DIR={source}',
                   f'SRC_DIR={ROOT / "SOURCE/src"}']
        result = subprocess.run([*command, 'update-version-major'], cwd=elsewhere,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([*command, 'version'], cwd=elsewhere,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '2.00.0000')
        self.assertEqual((elsewhere / 'version.txt').read_text(), '9.99.9999\n')


class BuildVersionValidationTests(unittest.TestCase):
    def test_build_checker_accepts_positive_major_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            version = Path(directory) / 'version.txt'
            for value in ('1.03.2413', '2.00.0000', '10.03.2413', '12345678901234567890.00.0000'):
                version.write_text(value + '\n')
                self.assertEqual(CHECKER.read_version(version), value)

    def test_build_checker_rejects_malformed_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            version = Path(directory) / 'version.txt'
            for value in ('0.00.0000', '01.00.0000', '2.0.0000', '2.00.00000',
                          '../2.00.0000', '2.00.0000 extra', '2.00.0000\n3.00.0000'):
                with self.subTest(version=value):
                    version.write_text(value + '\n')
                    with self.assertRaisesRegex(ValueError, 'M.xx.xxxx'):
                        CHECKER.read_version(version)

    def test_matching_invalid_build_version_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            build = Path(directory) / 'build'
            template = source / 'src/sdcard/mmcblk0p2/HACK'
            template.mkdir(parents=True)
            copied = build / 'mmcblk0p2/HACK'
            (copied / 'etc').mkdir(parents=True)
            (template / 'fixture').write_text('same source')
            (copied / 'fixture').write_text('same source')
            (source / 'version.txt').write_text('2.00.0000\n')
            (copied / 'etc/version.txt').write_text('2.00.0000\n')
            self.assertEqual(CHECKER.check_sources(source, build), 1)
            (source / 'version.txt').write_text('2.0.0000\n')
            (copied / 'etc/version.txt').write_text('2.0.0000\n')
            with self.assertRaisesRegex(ValueError, 'M.xx.xxxx'):
                CHECKER.check_sources(source, build)


class RuntimeVersionTests(unittest.TestCase):
    def run_function(self, name, *arguments):
        return subprocess.run([*RUNTIME_SHELL, '-c', FUNCTIONS + '\n' + name + ' "$@"',
                               'sh', *arguments], capture_output=True, text=True, timeout=5)

    def test_runtime_accepts_same_positive_major_contract(self):
        for value in ('1.03.2413', '2.00.0000', '10.03.2413', '12345678901234567890.00.0000'):
            self.assertEqual(self.run_function('update_version_valid', value).returncode, 0)

    def test_runtime_rejects_malformed_versions(self):
        for value in ('0.00.0000', '01.00.0000', '2.0.0000', '2.00.00000',
                      '../2.00.0000', '2.00.0000 extra', '2.00.0000\n3.00.0000', '2.00.0000/extra'):
            with self.subTest(version=value):
                self.assertNotEqual(self.run_function('update_version_valid', value).returncode, 0)

    def test_numeric_order_across_major_minor_and_revision_boundaries(self):
        for newer, older in (('2.00.0000', '1.03.2413'), ('10.00.0000', '2.99.9999'),
                             ('2.09.0000', '2.08.9999'), ('2.00.0100', '2.00.0099'),
                             ('100000000000000000000.00.0000', '99999999999999999999.99.9999')):
            with self.subTest(newer=newer, older=older):
                self.assertEqual(self.run_function('update_version_newer', newer, older).returncode, 0)
                self.assertEqual(self.run_function('update_version_newer', older, newer).returncode, 1)
                self.assertEqual(self.run_function('update_version_newer', newer, newer).returncode, 1)

    def run_updater(self, installed, available):
        temporary = tempfile.TemporaryDirectory(prefix='camoflash-update-version-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        etc = root / 'HACK/etc'; etc.mkdir(parents=True)
        log = root / 'log'; log.mkdir()
        (etc / 'version.txt').write_text(installed + '\n')
        curl = root / 'curl'
        curl.write_text('''#!/bin/sh
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then output=$2; shift; fi
    url=$1; shift
done
case "$url" in
    */version.txt) printf '%s\\n' "$AVAILABLE_VERSION" ;;
    */update-*.tgz) printf '%s\\n' "$url" > "$ARCHIVE_CALL"; printf fixture > "$output" ;;
    *) exit 1 ;;
esac
''')
        no_action = root / 'no-action'
        no_action.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$ACTION_LOG"\n')
        curl.chmod(0o755); no_action.chmod(0o755)
        env = dict(os.environ, hack=str(root / 'HACK'), device_uid='fixture',
                   sd_update=str(root / 'UPDATE'), sd_log=str(log), sd_etc=str(etc),
                   update_url='https://example.invalid/fixture', update_ssl_ignore='0',
                   curl=str(curl), tar=str(no_action), touch=str(no_action),
                   mkdir=shutil.which('mkdir'), rm=shutil.which('rm'), mv=shutil.which('mv'),
                   AVAILABLE_VERSION=available, ARCHIVE_CALL=str(root / 'archive-call'),
                   ACTION_LOG=str(root / 'actions'))
        result = subprocess.run([*RUNTIME_SHELL, str(UPDATER)], env=env,
                                capture_output=True, text=True, timeout=5)
        return result, root

    def test_major_upgrade_selects_archive_and_writes_validated_version(self):
        for installed, available in (('1.03.2413', '2.00.0000'), ('2.99.9999', '10.00.0000')):
            result, root = self.run_updater(installed, available)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'archive-call').read_text().strip(),
                             f'https://example.invalid/fixture/update-{available}.tgz')
            self.assertEqual((root / 'HACK/etc/version.txt').read_text(), available + '\n')
            self.assertIn('/tmp/hostapd.reboot', (root / 'actions').read_text())

    def test_equal_or_older_version_never_downloads(self):
        for installed, available in (('2.00.0000', '2.00.0000'), ('2.00.0000', '1.99.9999'),
                                      ('10.00.0000', '2.99.9999')):
            result, root = self.run_updater(installed, available)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / 'archive-call').exists())
            self.assertFalse((root / 'actions').exists())
            self.assertEqual((root / 'HACK/etc/version.txt').read_text(), installed + '\n')

    def test_malformed_installed_or_remote_version_never_downloads(self):
        for installed, available in (('2.0.0000', '3.00.0000'), ('2.00.0000', '3.00.0000/../../bad'),
                                      ('2.00.0000', '3.00.0000\n4.00.0000'), ('2.00.0000', '0.00.0000')):
            result, root = self.run_updater(installed, available)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'archive-call').exists())
            self.assertFalse((root / 'actions').exists())
            self.assertEqual((root / 'HACK/etc/version.txt').read_text(), installed + '\n')
