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
import struct
import unittest
from unittest.mock import patch

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
        self.setup_yyos()

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

    def setup_yyos(self):
        def module(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            result = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(result)
            return result
        installer = module('yyos_release_fixture_installer', ROOT / 'tools/yyos/install-kit.py')
        ssh = module('yyos_release_fixture_ssh', ROOT / 'tools/yyos/build-ssh-kit.py')
        projects = {'tools/yyos/package-kit.py', 'tools/yyos/install-kit.py', 'tools/yyos/build-kit.py',
                    'tools/yyos/build-ssh-kit.py', 'tools/yyos/build-dropbear.py', 'tools/yyos/build-musl.py',
                    'tools/yyos/dropbear-localoptions.h', 'tools/yyos/boot.sh', 'tools/yyos/yyos-clock-compat.c',
                    'tools/yyos/convert-recording.py', 'tools/yyos/recording-requirements.txt',
                    'docs/yyos-setup.md', 'docs/yyos-recordings.md'}
        for name in projects | {'tools/firmware-backup/build-yyos-kit.py', 'tools/firmware-backup/build-kit.py'}:
            self.write(name, (ROOT / name).read_bytes())
        self.yyos = self.source / 'yyos-release-kit'
        card = self.yyos / 'card'
        for folder, base, fmt, source in ((installer.HTTP, installer.HTTP_BASE, 'lscamoflash-yyos-management-v1', 'yyos'),
                                         (installer.SSH, installer.SSH_BASE, 'lscamoflash-yyos-ssh-kit-v1', 'yyos-ssh')):
            runtime = card / folder
            for name in base:
                path = runtime / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if name == 'LICENSE.MIT':
                    data = (self.root / 'LICENSE').read_bytes()
                elif name == 'COPYING.BusyBox':
                    data = b'BusyBox GPL version 2 fixture\n'
                else:
                    data = ('public YYOS fixture ' + name + '\n').encode()
                path.write_bytes(data)
                if not name.startswith('bin/') and name not in {'LICENSE.MIT', 'COPYING.BusyBox', 'COPYING.Dropbear'}:
                    relative = 'SOURCE/src/' + source + '/' + name
                    self.write(relative, data)
                    projects.add(relative)
            manifest = {'format': fmt, 'stock_sha256': installer.STOCK_SHA, 'credentials_provisioned': False,
                        'arm926_smoke': True, 'files': {name: RELEASE.digest(runtime / name) for name in base}}
            (runtime / 'manifest.json').write_text(json.dumps(manifest))
        for name in installer.ROOT_FILES - {'SHA256SUMS'}:
            path = card / name
            if name == 'yy_telnet_start':
                data = b''
            elif name == 'yyos-http-boot.sh':
                data = (self.root / 'tools/yyos/boot.sh').read_bytes()
            elif name == 'dump.sh':
                data = ssh.boot_wrapper(RELEASE.digest(self.root / 'tools/yyos/boot.sh'))
            else:
                data = ('public YYOS binary ' + name).encode()
            path.write_bytes(data)
        sources = self.yyos / 'sources'
        sources.mkdir()
        original = b'void gettime_wrapper(struct timespec *now) {\n\tstruct timeval tv;\n}\n'
        tar_bytes(sources / 'dropbear-2026.94.tar.bz2', {'dropbear-2026.94/src/dbutil.c': original}, 'w:bz2')
        (sources / 'musl-1.2.6.tar.gz').write_bytes(b'tiny public musl source fixture')
        for name in ('COPYING.musl', 'GCC-COPYING3', 'GCC-COPYING.RUNTIME'):
            (sources / name).write_bytes(('public license fixture ' + name).encode())
        (sources / 'musl-provenance.json').write_text('{"name":"musl","version":"1.2.6"}')
        libc = {'name': 'musl', 'version': '1.2.6', 'source_archive_sha256': RELEASE.digest(sources / 'musl-1.2.6.tar.gz'),
                'license_sha256': RELEASE.digest(sources / 'COPYING.musl'),
                'provenance_sha256': RELEASE.digest(sources / 'musl-provenance.json'),
                'gcc_runtime_notices': {name: RELEASE.digest(sources / name) for name in ('GCC-COPYING3', 'GCC-COPYING.RUNTIME')}}
        for name, value in (('YYOS_DROPBEAR_SHA', RELEASE.digest(sources / 'dropbear-2026.94.tar.bz2')),
                            ('YYOS_MUSL_SHA', RELEASE.digest(sources / 'musl-1.2.6.tar.gz'))):
            guard = patch.object(RELEASE, name, value)
            guard.start(); self.addCleanup(guard.stop)
        clock = self.root / 'clock-source'
        (clock / 'src').mkdir(parents=True)
        (clock / 'src/dbutil.c').write_bytes(original)
        builder = module('yyos_release_fixture_clock', ROOT / 'tools/yyos/build-dropbear.py')
        obj = bytearray(52); obj[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<HHI', obj, 16, 1, 40, 1); struct.pack_into('<I', obj, 36, 0x05000200)
        (sources / 'yyos-clock-compat.o').write_bytes(obj)
        (sources / 'yyos-clock-compat.c').write_bytes((ROOT / 'tools/yyos/yyos-clock-compat.c').read_bytes())
        proof = {'libc': libc, 'binary_sha256': RELEASE.digest(card / installer.SSH / 'bin/dropbear'),
                 'cflags': '-DLSCAMOFLASH_YYOS_CLOCK_COMPAT=1', 'yyos_clock_patch': builder.patch_clock_fallback(clock),
                 'yyos_clock_compat': {'source_sha256': ssh.CLOCK_SOURCE_SHA, 'object_sha256': RELEASE.digest(sources / 'yyos-clock-compat.o'),
                   'kernel_time_abi': 'ARM EABI signed time32 converted to libc time64',
                   'clock_source': 'requested POSIX clock, including monotonic', 'timeouts_disabled': False}}
        (sources / 'dropbear-provenance.json').write_text(json.dumps(proof))
        secure = card / installer.SSH
        (secure / 'COPYING.Dropbear').write_bytes(b'\n'.join((sources / name).read_bytes() for name in
                                                  ('COPYING.musl', 'GCC-COPYING3', 'GCC-COPYING.RUNTIME')))
        for folder in (installer.HTTP, installer.SSH):
            runtime = card / folder
            manifest = json.loads((runtime / 'manifest.json').read_text())
            manifest['files'] = {name: RELEASE.digest(runtime / name) for name in manifest['files']}
            if folder == installer.SSH:
                manifest['dropbear_build'] = proof
            (runtime / 'manifest.json').write_text(json.dumps(manifest))
            sums(runtime, set(manifest['files']) | {'manifest.json'})
        public = {p.relative_to(card).as_posix() for p in card.rglob('*') if p.is_file()}
        sums(card, public)
        (self.yyos / 'install-kit.py').write_bytes((ROOT / 'tools/yyos/install-kit.py').read_bytes())
        (self.yyos / 'SETUP.md').write_bytes((ROOT / 'docs/yyos-setup.md').read_bytes())
        (self.yyos / 'RECORDINGS.md').write_bytes((ROOT / 'docs/yyos-recordings.md').read_bytes())
        (self.yyos / 'tools').mkdir()
        for name in ('convert-recording.py', 'recording-requirements.txt'):
            (self.yyos / 'tools' / name).write_bytes((ROOT / 'tools/yyos' / name).read_bytes())
        (self.yyos / 'README.md').write_bytes(b'Public YYOS package fixture\n')
        for name in ('build-musl.py', 'build-dropbear.py', 'dropbear-localoptions.h'):
            (sources / name).write_bytes((ROOT / 'tools/yyos' / name).read_bytes())
        public = {p.relative_to(self.yyos).as_posix() for p in self.yyos.rglob('*') if p.is_file()}
        binaries = {'telnetd', 'busybox'} | {p.relative_to(card).as_posix() for folder in (installer.HTTP, installer.SSH)
                                           for p in (card / folder / 'bin').iterdir()}
        self.yyos_manifest = {'format': installer.FORMAT, 'stock_sha256': installer.STOCK_SHA, 'credential_free': True,
                              'version': VERSION, 'arm926_smoke': True, 'ssh_optional_default_disabled': True, 'libc': libc,
                              'project_sources': {name: RELEASE.digest(self.root / name) for name in projects},
                              'binaries': {name: {'static': True, 'cpu_arch': 'v5TEJ', 'bytes': (card / name).stat().st_size,
                                                  'sha256': RELEASE.digest(card / name)} for name in binaries},
                              'files': {name: RELEASE.digest(self.yyos / name) for name in public}}
        self.yyos_sums()
        self.git('add', 'tools', 'docs', 'SOURCE/src/yyos', 'SOURCE/src/yyos-ssh')

    def yyos_sums(self):
        (self.yyos / 'manifest.json').write_text(json.dumps(self.yyos_manifest))
        sums(self.yyos, set(self.yyos_manifest['files']) | {'manifest.json'})

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
        self.assertEqual(len(entries), 9)
        self.assertEqual((self.output / 'COPYING.BusyBox').read_bytes(), b'BusyBox GPL version 2 fixture\n')
        self.assertIn('not complete component-source archives', (self.output / 'THIRD_PARTY_NOTICES.md').read_text())

    def test_yyos_archive_is_separate_credential_free_with_optional_ssh_and_sources(self):
        self.stage()
        with tarfile.open(self.output / f'LSCamoflash-{VERSION}-yyos.tar.gz') as archive:
            members = {member.name.removeprefix('LSCamoflash-yyos-kit/'): member for member in archive}
            expected = {path.relative_to(self.yyos).as_posix() for path in self.yyos.rglob('*') if path.is_file()}
            self.assertEqual(set(members), expected)
            self.assertIn('card/LSCamoflash-yyos-ssh/bin/dropbear', members)
            self.assertIn('sources/musl-1.2.6.tar.gz', members)
            self.assertIn('install-kit.py', members)
            for name in members:
                self.assertNotIn('httpd.conf', name)
                self.assertNotIn('ssh.enabled', name)
                self.assertNotIn('host_key', name)
                self.assertNotIn('.local', name)

    def test_yyos_credentials_cannot_be_laundered_into_rehashed_public_inventory(self):
        path = self.yyos / 'card/LSCamoflash-yyos/httpd.conf'
        path.write_bytes(b'private account material\n')
        self.yyos_manifest['files'][path.relative_to(self.yyos).as_posix()] = RELEASE.digest(path)
        self.yyos_sums()
        with self.assertRaises(ValueError):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_yyos_source_mismatch_or_coherently_added_private_host_file_is_rejected(self):
        path = self.yyos / 'private-owner-key'
        path.write_bytes(b'private untracked key fixture')
        self.yyos_manifest['files']['private-owner-key'] = RELEASE.digest(path)
        self.yyos_sums()
        with self.assertRaises(ValueError):
            self.stage()
        path.unlink(); del self.yyos_manifest['files']['private-owner-key']; self.yyos_sums()
        self.write('SOURCE/src/yyos/start.sh', b'new public source\n')
        with self.assertRaises(ValueError):
            self.stage()
        self.assertFalse(self.output.exists())

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
        # Replace only pinned archive identities in this fixture copy so the
        # subprocess can use tiny synthetic archives without a runtime bypass.
        script = SCRIPT.read_bytes().replace(b'e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81', RELEASE.YYOS_DROPBEAR_SHA.encode())
        script = script.replace(b'd585fd3b613c66151fc3249e8ed44f77020cb5e6c1e635a616d3f9f82460512a', RELEASE.YYOS_MUSL_SHA.encode())
        copied = self.write('SOURCE/src/bin/prepare-release.py', script)
        self.git('add', 'SOURCE/src/bin/prepare-release.py')
        result = subprocess.run(['python3', str(copied), '--output', str(self.output)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Prepared public release assets:', result.stdout)
        self.assertEqual(len(list(self.output.iterdir())), 10)


if __name__ == '__main__':
    unittest.main()
