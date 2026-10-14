"""Public release staging with tiny archives and an isolated Git index."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'SOURCE/src/bin/prepare-release.py'
SPEC = importlib.util.spec_from_file_location('prepare_release', SCRIPT)
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)
VERSION = '2.00.0000'
VERSION_FILE = 'mmcblk0p2/HACK/etc/version.txt'


def tar_bytes(path, entries, mode='w:gz'):
    with tarfile.open(path, mode) as archive:
        for name, data in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def sums(directory, names):
    (directory / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  {name}\n'
        for name in sorted(names)))


class ReleaseVersionTests(unittest.TestCase):
    def test_positive_major_and_fixed_minor_build_widths(self):
        for version in ('1.03.2413', '2.00.0000', '10.03.2413'):
            self.assertEqual(RELEASE.version_text((version + '\r\n').encode()), version)
        for version in ('0.00.0000', '01.00.0000', '-2.00.0000', '2.0.0000', '2.00.000', '2.00.0000 extra'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                RELEASE.version_text(version.encode())


@unittest.skipUnless(shutil.which('git'), 'Git required for tracked-source boundary')
class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='camoflash-release-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'repo'
        self.root.mkdir()
        self.output = Path(self.temporary.name) / 'release'
        self.source = self.root / 'SOURCE'
        self.source.mkdir()
        self.download = self.source / 'download'
        self.download.mkdir()
        self.write('LICENSE', b'MIT project license\n')
        self.write('SOURCE/LICENSE.MIT', b'MIT project license\n')
        self.write('SOURCE/3RD_PARTY_LICENSES.md', b'# Third-party licenses\nBusyBox GPLv2; FFmpeg GPLv3+.\n')
        self.write('SOURCE/version.txt', (VERSION + '\n').encode())
        self.write('SOURCE/Makefile', b'''DOWNLOAD_URL := https://example.invalid/source
REV := 1.0
BUSYBOX := busybox-$(REV)
TOOLCHAIN := tiny-toolchain
URLS := \\
 $(DOWNLOAD_URL)/$(BUSYBOX).tar.bz2?download=\\#/$(BUSYBOX).tar.bz2 \\
 $(DOWNLOAD_URL)/$(TOOLCHAIN).tar.bz2?download=\\#/$(TOOLCHAIN).tar.bz2
''')
        self.write('SOURCE/src/config/busybox.config', b'CONFIG_STATIC=y\n')
        self.write('SOURCE/src/patches/ffmpeg/configure', b'public build patch\n')
        for name in RELEASE.FULLHAN_SOURCE_FILES:
            self.write('SOURCE/src/fullhan/' + name, ('public Fullhan ' + name + '\n').encode())
        self.write('SOURCE/src/fullhan/busybox-http-range.patch', b'public CGI Range patch\n')
        self.write('SOURCE/src/fullhan/onvif-readonly.patch', b'public ONVIF authentication patch\n')
        self.write('SOURCE/src/patches/busybox-1.0/uclibc-config', b'CONFIG_STATIC=y\n')
        self.write('public.txt', b'public source\n')
        self.write('.local/secret.txt', b'private research must never ship\n')
        self.write('SOURCE/download/undeclared.tar.gz', b'private undeclared download\n')
        (self.root / 'public-link').symlink_to('public.txt')
        # A tracked symlink is preserved without opening its private target.
        self.external = Path(self.temporary.name) / 'outside-secret'
        self.external.write_bytes(b'outside private data\n')
        (self.root / 'external-link').symlink_to(self.external)
        tar_bytes(self.download / 'busybox-1.0.tar.bz2', {'busybox-1.0/LICENSE': b'BusyBox GPL version 2 fixture\n'}, 'w:bz2')
        tar_bytes(self.download / 'tiny-toolchain.tar.bz2', {'tiny-toolchain/README.txt': b'prebuilt toolchain license/source links\n'}, 'w:bz2')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.git('add', '.')
        # Generated inputs and an untracked extraction are deliberately added
        # only after git add. Neither may leak into the source file list.
        self.write('untracked-extraction/private.txt', b'private extracted file\n')
        self.write('SOURCE/build/' + VERSION_FILE, (VERSION + '\n').encode())
        self.full = self.source / f'LSCamoflash-{VERSION}-uclibc.tar.gz'
        self.update = self.source / f'update-{VERSION}-uclibc.tgz'
        self.full_entries = {VERSION_FILE: (VERSION + '\n').encode(),
                             'mmcblk0p1/bootstrap.sh': b'boot\n',
                             'mmcblk0p2/HACK/sbin/init.sh': b'runtime\n'}
        self.update_entries = {name: data for name, data in self.full_entries.items() if name != VERSION_FILE}
        tar_bytes(self.full, self.full_entries)
        tar_bytes(self.update, self.update_entries)
        self.kit = self.source / 'backup-kit'
        (self.kit / 'card').mkdir(parents=True)
        for name in RELEASE.KIT_FILES - {'SHA256SUMS', 'card/SHA256SUMS'}:
            value = b'' if name.endswith('.conf') else (name + '\n').encode()
            (self.kit / name).write_bytes(value)
        (self.kit / 'manifest.json').write_text(json.dumps({'format': 'lscamoflash-nor-backup-kit-v1'}))
        sums(self.kit / 'card', {Path(name).name for name in RELEASE.KIT_FILES if name.startswith('card/')} - {'SHA256SUMS'})
        sums(self.kit, RELEASE.KIT_FILES - {'SHA256SUMS'})
        self.fullhan = self.source / 'fullhan-kit/LSCamoflash-fullhan'
        self.fullhan.mkdir(parents=True)
        for name in RELEASE.FULLHAN_PAYLOAD_FILES:
            path = self.fullhan / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name in RELEASE.FULLHAN_SOURCE_FILES:
                path.write_bytes((self.source / 'src/fullhan' / name).read_bytes())
            else:
                path.write_bytes(('synthetic Fullhan ' + name + '\n').encode())
        (self.fullhan / 'LICENSE.MIT').write_bytes((self.root / 'LICENSE').read_bytes())
        (self.fullhan / 'COPYING.BusyBox').write_bytes(b'BusyBox GPL version 2 fixture\n')
        def report(name):
            path = self.fullhan / 'bin' / name
            return {'bytes': path.stat().st_size, 'sha256': RELEASE.digest(path), 'static': True, 'cpu_arch': 'v5TEJ'}
        busybox = {'format': 'lscamoflash-fullhan-busybox-v1', 'sha256': report('busybox')['sha256'],
                   'cgi_range_header': True, 'arm1176_smoke': True, 'elf': report('busybox'),
                   'source_archive': {'name': 'busybox-1.0.tar.bz2', 'sha256': RELEASE.digest(self.download / 'busybox-1.0.tar.bz2')},
                   'patch_sha256': RELEASE.digest(self.source / 'src/fullhan/busybox-http-range.patch'),
                   'base_config_sha256': RELEASE.digest(self.source / 'src/patches/busybox-1.0/uclibc-config')}
        onvif = {'format': 'lscamoflash-fullhan-onvif-v1', 'sha256': report('onvif_srvd')['sha256'],
                 'arm1176_smoke': True, 'elf': report('onvif_srvd'),
                 'authentication': ['WSSE UsernameToken', 'HTTP Digest'], 'pre_auth_operations': ['GetSystemDateAndTime'],
                 'patch_sha256': RELEASE.digest(self.source / 'src/fullhan/onvif-readonly.patch'),
                 'source_archives': {'tiny-toolchain.tar.bz2': RELEASE.digest(self.download / 'tiny-toolchain.tar.bz2')}}
        self.write('SOURCE/fullhan-busybox/manifest.json', json.dumps(busybox).encode())
        self.write('SOURCE/fullhan-onvif/manifest.json', json.dumps(onvif).encode())
        self.write('SOURCE/fullhan-onvif/COPYING.ONVIF', (self.fullhan / 'COPYING.ONVIF').read_bytes())
        self.fullhan_manifest = {'format': 'lscamoflash-fullhan-management-v2', 'stock_sha256': RELEASE.FULLHAN_STOCK_SHA,
                                 'credentials_provisioned': False, 'onvif_credentials_provisioned': False,
                                 'onvif_included': True, 'arm1176_smoke': True, 'busybox': report('busybox'),
                                 'busybox_provenance': busybox, 'onvif_provenance': onvif,
                                 'helpers': {name: report(name) for name in ('fullhan-recordings', 'fullhan-discovery')},
                                 'files': {name: RELEASE.digest(self.fullhan / name) for name in RELEASE.FULLHAN_PAYLOAD_FILES}}
        self.fullhan_sums()

    def git(self, *arguments):
        return subprocess.run(['git', '-C', str(self.root), *arguments], check=True,
                              capture_output=True, text=True)

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def stage(self):
        return RELEASE.prepare(self.root, self.output)

    def fullhan_sums(self):
        (self.fullhan / 'manifest.json').write_text(json.dumps(self.fullhan_manifest))
        sums(self.fullhan, RELEASE.FULLHAN_FILES - {'SHA256SUMS'})

    def test_assets_are_byte_exact_and_every_asset_checksum_is_correct(self):
        self.output.mkdir()  # A dedicated empty directory is accepted.
        self.stage()
        self.assertEqual((self.output / self.full.name).read_bytes(), self.full.read_bytes())
        self.assertEqual((self.output / self.update.name).read_bytes(), self.update.read_bytes())
        entries = {}
        for line in (self.output / 'SHA256SUMS').read_text().splitlines():
            checksum, name = line.split('  ')
            entries[name] = checksum
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), checksum)
        self.assertEqual(set(entries), {p.name for p in self.output.iterdir()} - {'SHA256SUMS'})
        self.assertEqual(len(entries), 8)
        self.assertEqual((self.output / 'COPYING.BusyBox').read_bytes(), b'BusyBox GPL version 2 fixture\n')
        self.assertIn('not complete component-source archives', (self.output / 'THIRD_PARTY_NOTICES.md').read_text())

    def test_source_bundle_contains_tracked_public_files_and_only_declared_hydrated_downloads(self):
        self.stage()
        prefix = f'LSCamoflash-{VERSION}-source/'
        with tarfile.open(self.output / f'LSCamoflash-{VERSION}-source.tar.gz') as archive:
            members = {m.name.removeprefix(prefix): m for m in archive}
            for name in ('public.txt', 'SOURCE/src/config/busybox.config', 'SOURCE/src/patches/ffmpeg/configure',
                         'LICENSE', 'SOURCE/LICENSE.MIT', 'SOURCE/Makefile',
                         'SOURCE/download/busybox-1.0.tar.bz2', 'SOURCE/download/tiny-toolchain.tar.bz2'):
                self.assertIn(name, members)
                self.assertEqual(archive.extractfile(members[name]).read(), (self.root / name).read_bytes())
            self.assertTrue(members['public-link'].issym())
            self.assertEqual(members['public-link'].linkname, 'public.txt')
            self.assertTrue(members['external-link'].issym())
            self.assertEqual(members['external-link'].linkname, str(self.external))
            for name in members:
                self.assertNotIn('.local', name)
                self.assertNotIn('untracked-extraction', name)
                self.assertNotIn('undeclared.tar.gz', name)
                self.assertNotIn('SOURCE/build', name)
                self.assertNotIn('SOURCE/backup-kit', name)
                self.assertNotIn('SOURCE/fullhan-kit', name)

    def test_backup_archive_is_separate_and_includes_project_and_busybox_licenses(self):
        self.stage()
        prefix = f'LSCamoflash-{VERSION}-backup-kit/'
        with tarfile.open(self.output / f'LSCamoflash-{VERSION}-backup-kit.tar.gz') as archive:
            names = {member.name.removeprefix(prefix) for member in archive}
            self.assertEqual(names, RELEASE.KIT_FILES | {'LICENSE.MIT', 'COPYING.BusyBox', 'THIRD_PARTY_NOTICES.md'})
            self.assertEqual(archive.extractfile(prefix + 'COPYING.BusyBox').read(), b'BusyBox GPL version 2 fixture\n')
            self.assertNotIn('mmcblk0p1', names)

    def test_invalid_or_mismatched_versions_fail_before_output(self):
        for version in ('1.2.0001', '1.02.001', '0.02.0001', '01.02.0001', '2.00.0000 extra', '../2.00.0000'):
            with self.subTest(version=version):
                self.write('SOURCE/version.txt', (version + '\n').encode())
                with self.assertRaises(ValueError):
                    self.stage()
                self.assertFalse(self.output.exists())
        self.write('SOURCE/version.txt', (VERSION + '\n').encode())
        self.write('SOURCE/build/' + VERSION_FILE, b'1.02.0002\n')
        with self.assertRaisesRegex(ValueError, 'Built runtime version'):
            self.stage()
        self.write('SOURCE/build/' + VERSION_FILE, (VERSION + '\n').encode())
        tar_bytes(self.full, dict(self.full_entries, **{VERSION_FILE: b'1.02.0002\n'}))
        with self.assertRaisesRegex(ValueError, 'Full archive version'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_mixed_same_version_update_is_rejected(self):
        tar_bytes(self.update, {'mmcblk0p2/HACK/sbin/init.sh': b'stale runtime\n'})
        with self.assertRaisesRegex(ValueError, 'Update archive differs'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_hardlinked_runtime_members_are_compared_by_payload(self):
        for archive_path, entries in ((self.full, self.full_entries), (self.update, self.update_entries)):
            tar_bytes(archive_path, entries, 'w:')
            with tarfile.open(archive_path, 'a:') as archive:
                link = tarfile.TarInfo('mmcblk0p2/HACK/sbin/init-link.sh')
                link.type = tarfile.LNKTYPE
                link.linkname = 'mmcblk0p2/HACK/sbin/init.sh'
                archive.addfile(link)
            # Use real gzip compression around the small tar with a hardlink.
            import gzip
            archive_path.write_bytes(gzip.compress(archive_path.read_bytes()))
        self.stage()
        self.assertEqual((self.output / self.full.name).read_bytes(), self.full.read_bytes())
        self.assertEqual((self.output / self.update.name).read_bytes(), self.update.read_bytes())

    def test_missing_declared_input_is_rejected_without_output(self):
        (self.download / 'tiny-toolchain.tar.bz2').unlink()
        with self.assertRaises(FileNotFoundError):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_lfs_pointer_is_rejected_instead_of_shipping_pointer_text(self):
        self.write('SOURCE/download/tiny-toolchain.tar.bz2', RELEASE.LFS_HEADER + b'oid sha256:' + b'0' * 64 + b'\nsize 99\n')
        with self.assertRaisesRegex(ValueError, 'Unhydrated Git LFS pointer'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_hydrated_input_must_match_tracked_lfs_hash_and_size(self):
        path = self.download / 'tiny-toolchain.tar.bz2'
        payload = path.read_bytes()
        pointer = RELEASE.LFS_HEADER + b'oid sha256:' + hashlib.sha256(payload).hexdigest().encode() + f'\nsize {len(payload)}\n'.encode()
        path.write_bytes(pointer)
        self.git('add', 'SOURCE/download/tiny-toolchain.tar.bz2')
        path.write_bytes(payload)
        self.stage()
        shutil.rmtree(self.output)
        path.write_bytes(payload + b'changed')
        with self.assertRaisesRegex(ValueError, 'differs from tracked object'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_unknown_backup_files_and_modified_checked_payload_fail(self):
        private = self.kit / 'card/private-backup.bin'
        private.write_bytes(b'private camera readback\n')
        with self.assertRaisesRegex(ValueError, 'unexpected files'):
            self.stage()
        private.unlink()
        (self.kit / 'card/dump.sh').write_bytes(b'changed after kit build\n')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / 'keep.txt'
        sentinel.write_bytes(b'preserve existing files\n')
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
            self.stage()
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'preserve existing files\n')

    def test_fullhan_archive_has_fixed_install_root_exact_public_inventory_and_licenses(self):
        self.stage()
        with tarfile.open(self.output / f'LSCamoflash-{VERSION}-fullhan.tar.gz') as archive:
            members = {member.name: member for member in archive}
            self.assertEqual(set(members), {'LSCamoflash-fullhan/' + name for name in RELEASE.FULLHAN_FILES})
            for name in RELEASE.FULLHAN_FILES:
                self.assertEqual(archive.extractfile(members['LSCamoflash-fullhan/' + name]).read(), (self.fullhan / name).read_bytes())
            for private in ('httpd.conf', 'onvif.auth', 'onvif.uuid', 'startup.log'):
                self.assertNotIn('LSCamoflash-fullhan/' + private, members)

    def test_fullhan_missing_kit_credentials_or_unknown_files_are_rejected_before_output(self):
        for name in ('httpd.conf', 'onvif.auth', 'onvif.uuid', 'startup.log', 'private-firmware.bin'):
            path = self.fullhan / name
            path.write_bytes(b'private site data must never ship\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Fullhan kit contains missing or unexpected'):
                self.stage()
            path.unlink()
            self.assertFalse(self.output.exists())
        shutil.rmtree(self.fullhan)
        with self.assertRaisesRegex(ValueError, 'Fullhan kit contains missing or unexpected'):
            self.stage()

    def test_fullhan_coherently_rehashed_credential_flags_and_manifest_inventory_are_rejected(self):
        for field in ('credentials_provisioned', 'onvif_credentials_provisioned'):
            self.fullhan_manifest[field] = True
            self.fullhan_sums()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'credential-free'):
                self.stage()
            self.fullhan_manifest[field] = False
        del self.fullhan_manifest['files']['bin/onvif_srvd']
        self.fullhan_sums()
        with self.assertRaisesRegex(ValueError, 'manifest inventory'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_fullhan_payload_and_source_provenance_must_match_current_inputs(self):
        binary = self.fullhan / 'bin/onvif_srvd'
        original = binary.read_bytes()
        binary.write_bytes(original + b'corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.stage()
        binary.write_bytes(original)
        # Rehashed manifest/checksum text cannot approve a mismatched binary
        # build record or an old public source patch.
        self.fullhan_manifest['onvif_provenance']['sha256'] = '0' * 64
        self.fullhan_sums()
        with self.assertRaisesRegex(ValueError, 'ONVIF provenance'):
            self.stage()
        self.fullhan_manifest['onvif_provenance']['sha256'] = RELEASE.digest(binary)
        self.fullhan_sums()
        self.write('SOURCE/src/fullhan/onvif-readonly.patch', b'new public authentication patch\n')
        with self.assertRaisesRegex(ValueError, 'ONVIF provenance'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_fullhan_symlink_and_rehashed_license_mismatch_are_rejected(self):
        path = self.fullhan / 'COPYING.ONVIF'
        original = path.read_bytes()
        path.unlink()
        path.symlink_to(self.external)
        with self.assertRaisesRegex(ValueError, 'must not contain symlinks'):
            self.stage()
        path.unlink()
        path.write_bytes(b'changed license\n')
        self.fullhan_manifest['files']['COPYING.ONVIF'] = RELEASE.digest(path)
        self.fullhan_sums()
        with self.assertRaisesRegex(ValueError, 'ONVIF license'):
            self.stage()
        self.assertNotEqual(original, path.read_bytes())
        self.assertFalse(self.output.exists())

    def test_symlink_download_and_tracked_parent_redirect_are_rejected(self):
        path = self.download / 'tiny-toolchain.tar.bz2'
        path.unlink()
        path.symlink_to(self.external)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.stage()
        path.unlink()
        tar_bytes(path, {'tiny-toolchain/README.txt': b'toolchain\n'}, 'w:bz2')
        tracked = self.write('public-dir/data.txt', b'public\n')
        self.git('add', 'public-dir/data.txt')
        tracked.unlink()
        tracked.parent.rmdir()
        tracked.parent.symlink_to(self.external.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink ancestor'):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_cli_resolves_repo_from_script_and_only_stages_fixture(self):
        copied = self.write('SOURCE/src/bin/prepare-release.py', SCRIPT.read_bytes())
        self.git('add', 'SOURCE/src/bin/prepare-release.py')
        result = subprocess.run(['python3', str(copied), '--output', str(self.output)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Prepared public release assets:', result.stdout)
        self.assertEqual(len(list(self.output.iterdir())), 9)


if __name__ == '__main__':
    unittest.main()
