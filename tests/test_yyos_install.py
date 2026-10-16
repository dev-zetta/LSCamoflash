"""Host-only installation/provisioning controls on regular temporary files."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('yyos_installer_tests', REPO / 'tools/yyos/install-kit.py')
I = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(I)
AUTH = b'I:index.html\n/:admin:$1$fixture$abcdefghijklmnopqrstuv\n'
CLIENT = b'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(range(1, 33))) + b'\n'
HOST = b'\0\0\0\x0bssh-ed25519\0\0\0\x40' + bytes(range(1, 65))
CONTROL_KEY = b'SyntheticKey1234'


def native_document():
    return {'format': 'lscamoflash-yyos-native-credentials-v1', 'profile': 'lsc-3225722-yyos-14.1.5',
            'firmware_version': '14.1.5', 'app_sha256': I.STOCK_SHA, 'protocol_version': 3.5,
            'device_id': 'FakeCameraDevice000001', 'local_key': CONTROL_KEY.decode()}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def sums(root, names):
    write(root / 'SHA256SUMS', ''.join(I.sha(root / name) + '  ' + name + '\n' for name in sorted(names)).encode())


def fixture_kit(kit):
    card = kit / 'card'
    for folder, base, fmt in ((I.HTTP, I.HTTP_BASE, 'lscamoflash-yyos-management-v1'),
                              (I.SSH, I.SSH_BASE, 'lscamoflash-yyos-ssh-kit-v1')):
        root = card / folder
        for name in base:
            write(root / name, ('synthetic public ' + folder + '/' + name + '\n').encode())
        manifest = {'format': fmt, 'stock_sha256': I.STOCK_SHA, 'credentials_provisioned': False,
                    'files': {name: I.sha(root / name) for name in base}}
        write(root / 'manifest.json', json.dumps(manifest).encode())
        sums(root, set(base) | {'manifest.json'})
    for name in I.ROOT_FILES - {'SHA256SUMS'}:
        write(card / name, b'' if name == 'yy_telnet_start' else ('synthetic root ' + name).encode())
    sums(card, I.tree(card))
    write(kit / 'README.md', b'synthetic package\n')
    public = I.tree(kit)
    write(kit / 'manifest.json', json.dumps({'format': I.FORMAT, 'stock_sha256': I.STOCK_SHA,
          'credential_free': True, 'files': {name: I.sha(kit / name) for name in public}}).encode())
    sums(kit, public | {'manifest.json'})


def reseal_kit(kit):
    """Recompute all manifests/checksums after a deliberate structural mutation."""
    for folder in (I.HTTP, I.SSH):
        root = kit / 'card' / folder
        manifest = I.read_json(root / 'manifest.json')
        manifest['files'] = {name: I.sha(root / name) for name in manifest['files']}
        write(root / 'manifest.json', json.dumps(manifest).encode())
        sums(root, set(manifest['files']) | {'manifest.json'})
    sums(kit / 'card', I.tree(kit / 'card') - {'SHA256SUMS'} - I.SITE)
    manifest = I.read_json(kit / 'manifest.json')
    public = I.tree(kit) - {'manifest.json', 'SHA256SUMS'} - {'card/' + name for name in I.SITE}
    manifest['files'] = {name: I.sha(kit / name) for name in public}
    write(kit / 'manifest.json', json.dumps(manifest).encode())
    sums(kit, public | {'manifest.json'})


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yyos-install-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.kit = self.root / 'public'
        fixture_kit(self.kit)
        self.mount = self.root / 'card'
        self.mount.mkdir()
        write(self.mount / 'DCIM/keep.media', b'private recording preserved')
        self.identity = {'device': '/dev/synthetic1', 'uuid': 'ABCD-1234', 'st_dev': self.mount.stat().st_dev,
                         'mount': str(self.mount)}
        self.args = SimpleNamespace(kit=self.kit, mount=self.mount, device=None, uuid=None, replace_web_auth=False)

    def private(self, ssh=False):
        write(self.kit / 'card' / I.HTTP / 'httpd.conf', AUTH)
        if ssh:
            for name, data in (('authorized_keys', CLIENT), ('dropbear_ed25519_host_key', HOST), ('ssh.enabled', b'enabled\n')):
                write(self.kit / 'card' / I.SSH / name, data)

    def controls_payload(self):
        runtime = self.kit / 'card' / I.HTTP
        manifest = I.read_json(runtime / 'manifest.json')
        proof = {'synthetic_public_controls_proof': True, 'app_sha256': I.STOCK_SHA}
        for name in I.HTTP_CONTROLS:
            write(runtime / name, b'Synthetic public controls payload')
            if name == 'controls-provenance.json':
                write(runtime / name, json.dumps(proof).encode())
            manifest['files'][name] = I.sha(runtime / name)
        manifest['controls_provenance'] = proof
        write(runtime / 'manifest.json', json.dumps(manifest).encode())
        sums(runtime, set(manifest['files']) | {'manifest.json'})
        sums(self.kit / 'card', I.tree(self.kit / 'card') - {'SHA256SUMS'})
        public = I.tree(self.kit) - {'manifest.json', 'SHA256SUMS'}
        manifest = I.read_json(self.kit / 'manifest.json')
        manifest['controls_provenance'] = proof
        manifest['files'] = {name: I.sha(self.kit / name) for name in public}
        write(self.kit / 'manifest.json', json.dumps(manifest).encode())
        sums(self.kit, public | {'manifest.json'})

    def execute(self, perform=True):
        with patch.object(I, 'mounted_card', return_value=self.identity):
            return I.install(self.args, perform=perform)

    def snapshot(self):
        return {p.relative_to(self.mount).as_posix(): I.sha(p) for p in self.mount.rglob('*') if p.is_file()}

    def test_credential_free_first_install_refuses_without_mutation(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Provision'):
            self.execute()
        self.assertEqual(self.snapshot(), before)

    def test_plan_does_not_write_and_reports_auth_modes_only(self):
        self.private(ssh=True)
        before = self.snapshot()
        result = self.execute(False)
        self.assertTrue(result['plan_only'])
        self.assertTrue(result['ssh_enabled'])
        self.assertNotIn('$1$', json.dumps(result))
        self.assertEqual(self.snapshot(), before)

    def test_first_install_verified_marker_last_preserves_recording(self):
        self.private(ssh=True)
        events = []
        original = Path.rename
        def rename(path, target):
            events.append(Path(target).name)
            return original(path, target)
        with patch.object(Path, 'rename', rename):
            result = self.execute()
        self.assertTrue(result['installed'])
        self.assertEqual(events[-1], 'yy_telnet_start')
        self.assertEqual((self.mount / 'DCIM/keep.media').read_bytes(), b'private recording preserved')
        self.assertEqual((self.mount / I.HTTP / 'httpd.conf').read_bytes(), AUTH)
        self.assertEqual((self.mount / I.SSH / 'authorized_keys').read_bytes(), CLIENT)
        I.sums(self.mount, self.mount / 'SHA256SUMS')

    def test_combined_upgrade_preserves_auth_keys_logs_and_archives_old(self):
        self.private(ssh=True)
        first = self.execute()
        write(self.mount / I.HTTP / 'startup.log', b'private old HTTP log\n')
        write(self.mount / I.SSH / 'startup.log', b'private old SSH log\n')
        old = self.snapshot()
        write(self.kit / 'card' / I.HTTP / 'httpd.conf', AUTH.replace(b'admin', b'newuser'))
        (self.kit / 'card' / I.SSH / 'ssh.enabled').unlink()
        second = self.execute()
        archive = self.mount / second['archive']
        self.assertEqual((self.mount / I.HTTP / 'httpd.conf').read_bytes(), AUTH)
        self.assertEqual((self.mount / I.SSH / 'ssh.enabled').read_bytes(), b'enabled\n')
        self.assertEqual((self.mount / I.SSH / 'startup.log').read_bytes(), b'private old SSH log\n')
        for name, value in old.items():
            if name.split('/')[0] in I.ROOT_FILES | {I.HTTP, I.SSH}:
                self.assertEqual(I.sha(archive / name), value)
        self.assertTrue((self.mount / first['archive']).is_dir())

    def test_existing_disabled_ssh_stays_disabled(self):
        self.private(ssh=True)
        self.execute()
        (self.mount / I.SSH / 'ssh.enabled').unlink()
        self.execute()
        self.assertFalse((self.mount / I.SSH / 'ssh.enabled').exists())

    def test_new_keys_can_enable_previously_unprovisioned_ssh(self):
        self.private()
        self.execute()
        self.private(ssh=True)
        result = self.execute()
        self.assertTrue(result['ssh_enabled'])
        self.assertEqual((self.mount / I.SSH / 'ssh.enabled').read_bytes(), b'enabled\n')

    def test_unknown_debug_boot_input_refused_before_mutation(self):
        self.private()
        write(self.mount / 'yy_debug.ini', b'fixture debug marker')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            self.execute()
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_public_payload_and_symlink_refused(self):
        self.private()
        path = self.kit / 'card' / I.HTTP / 'start.sh'
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.execute()
        fixture_kit(self.kit)
        path.unlink()
        path.symlink_to(self.root / 'unrelated')
        with self.assertRaises(ValueError):
            self.execute()

    def test_failed_stage_disarms_marker_preserves_original_payload(self):
        self.private()
        self.execute()
        old = self.snapshot()
        original = I.write_new
        def fail(path, data, executable=False):
            if path.name == 'busybox':
                raise OSError('synthetic disk failure')
            return original(path, data, executable)
        with patch.object(I, 'write_new', side_effect=fail), self.assertRaises(OSError):
            self.execute()
        self.assertFalse((self.mount / 'yy_telnet_start').exists())
        self.assertEqual(I.sha(self.mount / I.HTTP / 'start.sh'), old[I.HTTP + '/start.sh'])
        self.assertEqual((self.mount / 'DCIM/keep.media').read_bytes(), b'private recording preserved')
        self.assertTrue(any(p.name == 'yy_telnet_start' for p in (self.mount / 'diagnostic-archive').rglob('*')))

    def test_final_fsync_failure_removes_new_marker(self):
        self.private()
        original = I.sync
        def fail(path):
            if path == self.mount and (self.mount / 'yy_telnet_start').exists():
                raise OSError('synthetic final flush failure')
            original(path)
        with patch.object(I, 'sync', side_effect=fail), self.assertRaises(OSError):
            self.execute()
        self.assertFalse((self.mount / 'yy_telnet_start').exists())

    def test_web_auth_must_be_protected_hash_not_plaintext(self):
        for data in (b'/:admin:plaintext\n', AUTH + AUTH, b'I:index.html\n', AUTH + b'P:other\n'):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                I.auth_config(data)

    def test_provision_hashes_password_outside_public_inventory(self):
        password = self.root / 'web-password'
        password.write_bytes(b'fixture-private-password\n')
        password.chmod(0o600)
        args = SimpleNamespace(kit=self.kit, output=self.root / 'private', username='admin', password_file=password,
                               client_public_key=None, host_key=None, generate_ssh_keys=False)
        before = {p.relative_to(self.kit).as_posix(): I.sha(p) for p in self.kit.rglob('*') if p.is_file()}
        result = I.provision(args)
        self.assertTrue(result['web_provisioned'])
        self.assertFalse(result['ssh_provisioned'])
        I.validate_kit(args.output)
        config = (args.output / 'card' / I.HTTP / 'httpd.conf').read_bytes()
        I.auth_config(config)
        self.assertNotIn(b'fixture-private-password', config)
        self.assertEqual(before, {p.relative_to(self.kit).as_posix(): I.sha(p) for p in self.kit.rglob('*') if p.is_file()})
        for path in args.output.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'fixture-private-password', path.read_bytes())

    def test_generated_owner_private_key_stays_outside_card_and_host_seed_matches(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        password = self.root / 'web-password'
        password.write_bytes(b'fixture-private-password\n')
        password.chmod(0o600)
        args = SimpleNamespace(kit=self.kit, output=self.root / 'private', username='admin', password_file=password,
                               client_public_key=None, host_key=None, generate_ssh_keys=True)
        result = I.provision(args)
        self.assertTrue(result['ssh_provisioned'])
        owner_path = args.output / 'owner_ssh_ed25519'
        self.assertEqual(owner_path.stat().st_mode & 0o777, 0o600)
        owner = serialization.load_ssh_private_key(owner_path.read_bytes(), password=None)
        self.assertEqual(owner.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH) + b'\n',
                         (args.output / 'card' / I.SSH / 'authorized_keys').read_bytes())
        host = (args.output / 'card' / I.SSH / 'dropbear_ed25519_host_key').read_bytes()
        self.assertEqual(Ed25519PrivateKey.from_private_bytes(host[19:51]).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw), host[51:])
        for path in (args.output / 'card').rglob('*'):
            if path.is_file():
                self.assertNotIn(b'OPENSSH PRIVATE KEY', path.read_bytes())

    def test_optional_native_key_provisions_only_raw_key_outside_public_inventory(self):
        self.controls_payload()
        source = self.root / 'native-credentials'
        source.write_text(json.dumps(native_document())); source.chmod(0o600)
        password = self.root / 'web-password'
        password.write_bytes(b'fixture-private-password\n'); password.chmod(0o600)
        args = SimpleNamespace(kit=self.kit, output=self.root / 'private', username='admin', password_file=password,
                               client_public_key=None, host_key=None, generate_ssh_keys=False, native_credentials=source)
        result = I.provision(args)
        target = args.output / 'card' / I.HTTP / 'native-control.key'
        self.assertTrue(result['native_controls_provisioned'])
        self.assertEqual(target.read_bytes(), CONTROL_KEY)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        I.validate_kit(args.output)
        for path in args.output.rglob('*'):
            if path.is_file() and path != target:
                self.assertNotIn(CONTROL_KEY, path.read_bytes())
                self.assertNotIn(b'FakeCameraDevice000001', path.read_bytes())
        with self.assertRaises(ValueError):
            I.validate_kit(args.output, public=True)
        self.assertNotIn(I.HTTP + '/native-control.key', I.sums(args.output / 'card', args.output / 'card/SHA256SUMS'))

    def test_native_credentials_schema_key_ascii_duplicates_and_permissions_refuse(self):
        source = self.root / 'credentials'
        for changed in ({'profile': 'other'}, {'app_sha256': '0' * 64}, {'local_key': 'x' * 15},
                        {'local_key': 'é' * 16}, {'local_key': 'x' * 15 + '\n'}, {'protocol_version': True}):
            value = native_document(); value.update(changed)
            source.write_text(json.dumps(value)); source.chmod(0o600)
            with self.subTest(fields=list(changed)), self.assertRaises(ValueError) as caught:
                I.native_credentials(source)
            self.assertNotIn(CONTROL_KEY.decode(), str(caught.exception))
        source.write_text(json.dumps(native_document())[:-1] + ',"local_key":"different"}')
        with self.assertRaises(ValueError):
            I.native_credentials(source)
        source.write_text(json.dumps(native_document())); source.chmod(0o644)
        with self.assertRaises(ValueError):
            I.native_credentials(source)

    def test_controls_credentials_refuse_missing_optional_payload_before_output(self):
        source = self.root / 'credentials'
        source.write_text(json.dumps(native_document())); source.chmod(0o600)
        password = self.root / 'password'; password.write_bytes(b'fixture-password\n'); password.chmod(0o600)
        args = SimpleNamespace(kit=self.kit, output=self.root / 'private', username='admin', password_file=password,
                               client_public_key=None, host_key=None, generate_ssh_keys=False, native_credentials=source)
        with self.assertRaisesRegex(ValueError, 'optional controls payload'):
            I.provision(args)
        self.assertFalse(args.output.exists())

    def test_existing_controls_key_is_preserved_on_upgrade_and_never_hashed_publicly(self):
        self.controls_payload(); self.private()
        write(self.kit / 'card' / I.HTTP / 'native-control.key', CONTROL_KEY)
        self.execute()
        write(self.kit / 'card' / I.HTTP / 'native-control.key', b'DifferentKey1234')
        result = self.execute()
        self.assertEqual(result['native_controls_key'], 'existing-preserved')
        self.assertEqual((self.mount / I.HTTP / 'native-control.key').read_bytes(), CONTROL_KEY)
        self.assertEqual((self.mount / result['archive'] / I.HTTP / 'native-control.key').read_bytes(), CONTROL_KEY)
        self.assertNotIn(I.HTTP + '/native-control.key', I.sums(self.mount, self.mount / 'SHA256SUMS'))

    def test_coherently_hashed_native_key_is_still_refused_as_public_payload(self):
        name = 'card/' + I.HTTP + '/native-control.key'
        write(self.kit / name, CONTROL_KEY)
        manifest = I.read_json(self.kit / 'manifest.json')
        manifest['files'][name] = I.sha(self.kit / name)
        write(self.kit / 'manifest.json', json.dumps(manifest).encode())
        sums(self.kit, set(manifest['files']) | {'manifest.json'})
        with self.assertRaisesRegex(ValueError, 'Site provisioning files'):
            I.validate_kit(self.kit, public=True)

    def test_declared_and_checksummed_unknown_runtime_files_are_refused(self):
        for index, (folder, name) in enumerate(((I.HTTP, 'foo'), (I.HTTP, 'owner-private.txt'),
                                                (I.SSH, 'foo'), (I.SSH, 'www/cgi-bin/recordings.cgi'))):
            kit = self.root / ('unknown-' + str(index)); fixture_kit(kit)
            root = kit / 'card' / folder
            write(root / name, b'Unknown declared file must never be published')
            manifest = I.read_json(root / 'manifest.json')
            manifest['files'][name] = I.sha(root / name)
            write(root / 'manifest.json', json.dumps(manifest).encode()); reseal_kit(kit)
            with self.subTest(folder=folder, name=name), self.assertRaisesRegex(ValueError, 'Unknown declared runtime file'):
                I.validate_kit(kit, public=True)

    def test_optional_recordings_group_is_complete_or_absent(self):
        runtime = self.kit / 'card' / I.HTTP
        manifest = I.read_json(runtime / 'manifest.json')
        for name in I.HTTP_RECORDINGS:
            write(runtime / name, b'Synthetic public recording payload')
            manifest['files'][name] = I.sha(runtime / name)
        write(runtime / 'manifest.json', json.dumps(manifest).encode()); reseal_kit(self.kit)
        I.validate_kit(self.kit, public=True)
        name = 'bin/yyos-recordings'
        (runtime / name).unlink(); manifest['files'].pop(name)
        write(runtime / 'manifest.json', json.dumps(manifest).encode()); reseal_kit(self.kit)
        with self.assertRaisesRegex(ValueError, 'Incomplete optional runtime group'):
            I.validate_kit(self.kit, public=True)

    def test_partial_controls_group_is_refused_even_with_matching_proof(self):
        self.controls_payload()
        runtime = self.kit / 'card' / I.HTTP
        manifest = I.read_json(runtime / 'manifest.json')
        name = 'bin/yyos-controls-cgi'
        (runtime / name).unlink(); manifest['files'].pop(name)
        write(runtime / 'manifest.json', json.dumps(manifest).encode()); reseal_kit(self.kit)
        with self.assertRaisesRegex(ValueError, 'Incomplete optional runtime group'):
            I.validate_kit(self.kit, public=True)

    def test_controls_proof_must_match_runtime_file_and_package(self):
        for field in ('runtime-missing', 'file-mismatch', 'package-missing', 'package-mismatch', 'empty-proof'):
            self.kit = self.root / field; fixture_kit(self.kit); self.controls_payload()
            runtime = self.kit / 'card' / I.HTTP
            manifest = I.read_json(runtime / 'manifest.json')
            package = I.read_json(self.kit / 'manifest.json')
            if field == 'runtime-missing':
                manifest.pop('controls_provenance')
            elif field == 'file-mismatch':
                write(runtime / 'controls-provenance.json', b'{"different":true}')
            elif field == 'package-missing':
                package.pop('controls_provenance')
            elif field == 'package-mismatch':
                package['controls_provenance'] = {'different': True}
            else:
                manifest['controls_provenance'] = package['controls_provenance'] = {}
                write(runtime / 'controls-provenance.json', b'{}')
            write(runtime / 'manifest.json', json.dumps(manifest).encode())
            write(self.kit / 'manifest.json', json.dumps(package).encode()); reseal_kit(self.kit)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '[Cc]ontrols.*provenance'):
                I.validate_kit(self.kit, public=True)

    def test_controls_proof_without_controls_group_is_refused(self):
        for level in ('runtime', 'package'):
            kit = self.root / ('unexpected-proof-' + level); fixture_kit(kit)
            path = kit / ('card/' + I.HTTP if level == 'runtime' else '') / 'manifest.json'
            manifest = I.read_json(path); manifest['controls_provenance'] = {'unrelated': True}
            write(path, json.dumps(manifest).encode()); reseal_kit(kit)
            with self.subTest(level=level), self.assertRaisesRegex(ValueError, 'provenance requires'):
                I.validate_kit(kit, public=True)

    def test_known_normal_http_upgrade_can_add_optional_ssh(self):
        self.private(ssh=True)
        self.execute()
        (self.mount / 'dump.sh').write_bytes((self.mount / 'yyos-http-boot.sh').read_bytes())
        (self.mount / 'yyos-http-boot.sh').unlink()
        shutil.rmtree(self.mount / I.SSH)
        expected = I.ROOT_FILES - {'SHA256SUMS', 'yyos-http-boot.sh'}
        expected |= {I.HTTP + '/' + name for name in I.runtime(self.mount / I.HTTP, allow_site=True)}
        sums(self.mount, expected)
        result = self.execute()
        self.assertTrue(result['upgrade'])
        self.assertTrue(result['ssh_enabled'])
        self.assertEqual((self.mount / I.HTTP / 'httpd.conf').read_bytes(), AUTH)

    def test_private_input_and_fat_like_output_permissions_are_refused(self):
        password = self.root / 'web-password'
        password.write_bytes(b'fixture-private-password\n')
        password.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'mode0600'):
            I.private_input(password, 4096)
        password.chmod(0o600)
        args = SimpleNamespace(kit=self.kit, output=self.root / 'private', username='admin', password_file=password,
                               client_public_key=None, host_key=None, generate_ssh_keys=True)
        original = Path.stat
        def permissions(path, *a, **kw):
            value = original(path, *a, **kw)
            if any(part.startswith('.yyos-provision-') for part in path.parts) and stat.S_ISDIR(value.st_mode):
                values = list(value); values[0] = (value.st_mode & ~0o777) | 0o777
                return os.stat_result(values)
            return value
        with patch.object(Path, 'stat', permissions), patch.object(I, 'write_host_new') as writes:
            with self.assertRaisesRegex(ValueError, 'mode0700'):
                I.provision(args)
            writes.assert_not_called()
        self.assertFalse(args.output.exists())

    def test_private_host_file_permissions_checked_before_secret_bytes(self):
        output = self.root / 'private-output'
        output.mkdir(mode=0o700)
        secret = output / 'credential'
        original = os.fstat
        def permissions(fd):
            value = original(fd)
            values = list(value)
            values[0] = (value.st_mode & ~0o777) | 0o777
            return os.stat_result(values)
        with patch.object(os, 'fstat', permissions), patch.object(os, 'fdopen') as writer:
            with self.assertRaisesRegex(ValueError, 'permissions'):
                I.write_host_new(secret, b'fixture-private-secret')
            writer.assert_not_called()
        self.assertFalse(secret.exists())


class StorageGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yyos-mount-test-')
        self.addCleanup(self.tmp.cleanup)
        self.mount = Path(self.tmp.name)
        dev = self.mount.stat().st_dev
        self.block = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=dev)
        self.mounted = {'target': str(self.mount), 'source': '/dev/fixture1', 'fstype': 'vfat', 'options': 'rw,nosuid',
                        'uuid': 'ABCD-1234', 'maj:min': f'{os.major(dev)}:{os.minor(dev)}'}
        self.partition = {'path': '/dev/fixture1', 'type': 'part', 'rm': True, 'ro': False, 'fstype': 'vfat',
                          'uuid': 'ABCD-1234', 'maj:min': self.mounted['maj:min'], 'mountpoints': [str(self.mount)]}
        self.disk = {'path': '/dev/fixture', 'type': 'disk', 'rm': True, 'ro': False, 'children': [self.partition]}

    def check(self):
        original = os.stat
        def metadata(path, *args, **kwargs):
            return self.block if str(path) == '/dev/fixture1' else original(path, *args, **kwargs)
        def commands(command):
            return {'filesystems': [self.mounted]} if command[0] == 'findmnt' else {'blockdevices': [self.disk]}
        with patch.object(I, 'command_json', side_effect=commands), patch.object(I.os, 'stat', side_effect=metadata):
            return I.mounted_card(self.mount, '/dev/fixture1', 'ABCD-1234')

    def test_visible_removable_rw_partition_is_accepted(self):
        self.assertEqual(self.check()['uuid'], 'ABCD-1234')

    def test_nonremovable_readonly_wrong_device_and_superfloppy_refused(self):
        for node, key, value in ((self.disk, 'rm', False), (self.disk, 'ro', True),
                                  (self.partition, 'type', 'disk'), (self.partition, 'uuid', 'FFFF-FFFF'),
                                  (self.mounted, 'options', 'ro,nosuid')):
            old = node[key]; node[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.check()
            node[key] = old
        self.block.st_rdev += 1
        with self.assertRaises(ValueError):
            self.check()


if __name__ == '__main__':
    unittest.main()
