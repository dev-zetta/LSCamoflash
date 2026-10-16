#!/usr/bin/env python3
"""Synthetic storage and fake LAN transport; never contact or execute a camera."""
import contextlib
import base64
import hashlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import stat
import struct
import tarfile
import tempfile
import time
import unittest
from unittest import mock
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('yyos_native_media', REPO / 'tools/yyos/native-media.py')
MEDIA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEDIA)
KEY = bytes(range(16))
DEVICE_ID = 'FakeCameraDevice000001'
LOCAL_KEY = 'SyntheticKey1234'
PASSWORD = 'SyntheticAbc123'


def records():
    return {'gw_di': json.dumps({'id': DEVICE_ID, 'swv': '14.1.5', 'dev_swv': '14.1.5',
                                 'lpv': '3.5'}).encode() + b'\0',
            'gw_ai': json.dumps({'lckey': LOCAL_KEY, 'other_secret': 'DO-NOT-EMIT'}).encode(),
            'other': b'opaque\0private\0record'}


def encrypt(plain):
    padding = 16 - len(plain) % 16
    cipher = Cipher(algorithms.AES(bytes([9, 8, 11, 10, 13, 12, 15, 14,
                                        1, 0, 3, 2, 5, 4, 7, 6])), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(plain + bytes([padding]) * padding) + encryptor.finalize()


def database(values=None):
    values = values or records()
    table = bytearray(28 + len(values) * 56)
    struct.pack_into('<I', table, 24, len(values))
    for number, (name, plain) in enumerate(values.items()):
        ciphertext = encrypt(plain)
        position = 28 + number * 56
        struct.pack_into('<I', table, position, 1)
        table[position + 4:position + 4 + len(name)] = name.encode()
        struct.pack_into('<I', table, position + 44, len(table))
        struct.pack_into('<H', table, position + 48, len(ciphertext))
        struct.pack_into('<I', table, position + 52, zlib.crc32(ciphertext))
        table += ciphertext
    fix_header(table)
    return bytes(table)


def fix_header(data):
    count = struct.unpack_from('<I', data, 24)[0]
    struct.pack_into('<I', data, 0, zlib.crc32(data[4:28 + count * 56]))


def credentials():
    return MEDIA.credential_document(records())


def private_file(path, data):
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def archive_bytes(app=b'SYNTHETIC-YYOS-APP', db=None, backup_db=None, duplicate=False, symlink=False):
    result = io.BytesIO()
    payloads = {'appfs/bin/yy_cam': app, 'config/tuya/tuya_enckey.db': KEY,
                'config/tuya/tuya_user.db': db or database(),
                'config/tuya/tuya_user.db_bak': backup_db or db or database()}
    with tarfile.open(fileobj=result, mode='w') as archive:
        for name, payload in payloads.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            if symlink and name == 'appfs/bin/yy_cam':
                member.type = tarfile.SYMTYPE
                member.linkname = '/outside-private-file'
                archive.addfile(member)
            else:
                archive.addfile(member, io.BytesIO(payload))
        if duplicate:
            member = tarfile.TarInfo('./appfs/bin/yy_cam')
            member.size = len(app)
            archive.addfile(member, io.BytesIO(app))
    return result.getvalue()


def complete_backup(root):
    """Regular-file evidence exercises the real complete-backup host verifier."""
    sizes = (262144, 1572864, 1376256, 4784128, 262144, 131072)
    partitions = ['id\tbytes\terase_bytes\ttype\twrite_bytes\toob_bytes\tdev\toffset']
    attempts = ['id\tattempt\tread\tdd_exit\tresult\tbytes\tsha256']
    proc = ['dev: size erasesize name']
    offset = 0
    for number, size in enumerate(sizes):
        identity = f'mtd{number}'
        payload = bytes([number]) * size
        digest = hashlib.sha256(payload).hexdigest()
        partitions.append(f'{identity}\t{size}\t4096\tnor\t256\t0\t90:{number * 2}\t{offset}')
        proc.append(f'{identity}: {size:08x} 00001000 "SYNTHETIC-{number}"')
        metadata = {'type': 'nor', 'size': str(size), 'erasesize': '4096',
                    'writesize': '256', 'oobsize': '0', 'dev': f'90:{number * 2}', 'offset': str(offset)}
        for name, value in metadata.items():
            path = root / 'meta' / identity / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value + '\n')
        for read in (1, 2):
            path = root / 'partitions' / identity / f'read{read}.bin'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            attempts.append(f'{identity}\t1\t{read}\t0\tok\t{size}\t{digest}')
        offset += size
    (root / 'meta/proc-mtd.txt').write_text('\n'.join(proc) + '\n')
    (root / 'partitions.tsv').write_text('\n'.join(partitions) + '\n')
    (root / 'read-attempts.tsv').write_text('\n'.join(attempts) + '\n')
    (root / 'stock-userspace.tar').write_bytes(archive_bytes())
    checksums = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            checksums.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(root)))
    (root / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
    (root / 'status.txt').write_text('VERIFIED_NOR_BACKUP\npartitions=6\ntotal_partition_bytes=8388608\nflash_image_concatenated=no\n')


class DatabaseTests(unittest.TestCase):
    def test_binary_derived_key_permutation(self):
        self.assertEqual(MEDIA.derive_key(KEY), bytes([9, 8, 11, 10, 13, 12, 15, 14,
                                                     1, 0, 3, 2, 5, 4, 7, 6]))

    def test_full_roundtrip_and_profile_metadata(self):
        self.assertEqual(MEDIA.decode_database(database(), KEY), records())
        result = MEDIA.credential_document(MEDIA.decode_database(database(), KEY))
        self.assertEqual(result['device_id'], DEVICE_ID)
        self.assertEqual(result['local_key'], LOCAL_KEY)
        self.assertEqual(result['protocol_version'], 3.5)
        self.assertEqual(result['app_sha256'], MEDIA.APP_SHA256)
        self.assertNotIn('other_secret', result)

    def test_crc_and_descriptor_refusals(self):
        for case in ('header', 'ciphertext', 'count', 'active', 'bounds', 'unaligned',
                     'overlap', 'duplicate', 'name'):
            with self.subTest(case=case):
                data = bytearray(database())
                first, second = 28, 84
                if case == 'header':
                    data[4] ^= 1
                elif case == 'ciphertext':
                    data[-1] ^= 1
                elif case == 'count':
                    struct.pack_into('<I', data, 24, 129)
                elif case == 'active':
                    struct.pack_into('<I', data, first, 0)
                elif case == 'bounds':
                    struct.pack_into('<I', data, first + 44, len(data) - 1)
                elif case == 'unaligned':
                    struct.pack_into('<H', data, first + 48, 15)
                elif case == 'overlap':
                    data[second + 44:second + 56] = data[first + 44:first + 56]
                elif case == 'duplicate':
                    data[second + 4:second + 37] = data[first + 4:first + 37]
                elif case == 'name':
                    data[first + 4:first + 37] = b'X' * 33
                if case not in ('header', 'count', 'ciphertext'):
                    fix_header(data)
                with self.assertRaises(MEDIA.MediaError):
                    MEDIA.decode_database(bytes(data), KEY)

    def test_full_padding_not_only_last_byte(self):
        data = bytearray(database())
        descriptor = 28
        offset = struct.unpack_from('<I', data, descriptor + 44)[0]
        length = struct.unpack_from('<H', data, descriptor + 48)[0]
        dec = Cipher(algorithms.AES(MEDIA.derive_key(KEY)), modes.ECB()).decryptor()
        plain = bytearray(dec.update(data[offset:offset + length]) + dec.finalize())
        plain[-2:] = b'\x03\x02'
        enc = Cipher(algorithms.AES(MEDIA.derive_key(KEY)), modes.ECB()).encryptor()
        data[offset:offset + length] = enc.update(bytes(plain)) + enc.finalize()
        struct.pack_into('<I', data, descriptor + 52, zlib.crc32(data[offset:offset + length]))
        fix_header(data)
        with self.assertRaisesRegex(MEDIA.MediaError, 'database_padding'):
            MEDIA.decode_database(bytes(data), KEY)

    def test_wrong_key_and_limits(self):
        for data, key in ((database(), b'bad'), (b'X' * (MEDIA.MAX_DATABASE + 1), KEY),
                          (b'', KEY), (database(), b'X' * 16)):
            with self.subTest(length=len(data), key_length=len(key)), self.assertRaises(MEDIA.MediaError):
                MEDIA.decode_database(data, key)

    def test_firmware_identity_protocol_and_duplicate_json(self):
        for field, value in [('swv', '14.1.6'), ('dev_swv', '14.1.4'), ('lpv', '3.3'),
                             ('lpv', True), ('id', '../bad')]:
            values = records()
            identity = json.loads(values['gw_di'].rstrip(b'\0'))
            identity[field] = value
            values['gw_di'] = json.dumps(identity).encode()
            with self.subTest(field=field, value=value), self.assertRaises(MEDIA.MediaError):
                MEDIA.credential_document(values)
        values = records()
        values['gw_ai'] = b'{"lckey":"SyntheticKey1234","lckey":"DifferentKeyValue"}'
        with self.assertRaisesRegex(MEDIA.MediaError, 'duplicate_json_key'):
            MEDIA.credential_document(values)

    def test_archive_exact_hash_duplicates_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for case in ('wrong-binary', 'duplicate', 'symlink'):
                with self.subTest(case=case), mock.patch.object(MEDIA, 'verified_archive',
                        return_value=io.BytesIO(archive_bytes(duplicate=case == 'duplicate',
                                                             symlink=case == 'symlink'))):
                    with self.assertRaises(MEDIA.MediaError):
                        MEDIA.recover_credentials(root, root / case)
                    self.assertFalse((root / case).exists())

    def test_new_private_file_only_and_no_stdout_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'credentials.json'
            app = b'SYNTHETIC-YYOS-APP'
            with mock.patch.object(MEDIA, 'APP_SHA256', hashlib.sha256(app).hexdigest()), \
                    mock.patch.object(MEDIA, 'verified_archive', side_effect=lambda _: io.BytesIO(archive_bytes())):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = MEDIA.recover_credentials(root, target)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertTrue(result['credentials_written'])
                self.assertEqual(MEDIA.load_credentials(target)['local_key'], LOCAL_KEY)
                for secret in (DEVICE_ID, LOCAL_KEY, 'DO-NOT-EMIT'):
                    self.assertNotIn(secret, output.getvalue() + json.dumps(result))
                previous = target.read_bytes()
                with self.assertRaises(MEDIA.MediaError):
                    MEDIA.recover_credentials(root, target)
                self.assertEqual(target.read_bytes(), previous)
                link = root / 'link.json'
                link.symlink_to(target)
                with self.assertRaisesRegex(MEDIA.MediaError, 'unsafe_output_path'):
                    MEDIA.recover_credentials(root, link)

    def test_private_input_permissions_symlink_and_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = private_file(root / 'identity', json.dumps(credentials()).encode())
            self.assertEqual(MEDIA.load_credentials(target), credentials())
            target.chmod(0o644)
            with self.assertRaisesRegex(MEDIA.MediaError, 'unsafe_private_file'):
                MEDIA.load_credentials(target)
            target.chmod(0o600)
            link = root / 'link'
            link.symlink_to(target)
            with self.assertRaises(MEDIA.MediaError):
                MEDIA.load_credentials(link)
            os.mkfifo(root / 'fifo', 0o600)
            with self.assertRaises(MEDIA.MediaError):
                MEDIA.load_credentials(root / 'fifo')

    def test_complete_host_verifier_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'status.txt').write_text('FAILED\n')
            with self.assertRaisesRegex(MEDIA.MediaError, 'backup_verification_failed'):
                MEDIA.recover_credentials(root, root / 'identity')
            self.assertFalse((root / 'identity').exists())

    def test_real_complete_verifier_chain_and_tampered_read_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'run'
            root.mkdir()
            complete_backup(root)
            target = Path(directory) / 'private.json'
            output = io.StringIO()
            with mock.patch.object(MEDIA, 'APP_SHA256', hashlib.sha256(b'SYNTHETIC-YYOS-APP').hexdigest()):
                with contextlib.redirect_stdout(output):
                    code = MEDIA.main(['credentials', '--backup-run', str(root), '--output', str(target)])
                self.assertEqual(code, 0)
                self.assertEqual(MEDIA.load_credentials(target), credentials())
                self.assertTrue(json.loads(output.getvalue())['credentials_written'])
                (root / 'partitions/mtd0/read2.bin').write_bytes(b'corrupted independently-read data')
                with self.assertRaisesRegex(MEDIA.MediaError, 'backup_verification_failed'):
                    MEDIA.recover_credentials(root, Path(directory) / 'tampered.json')
                self.assertFalse((Path(directory) / 'tampered.json').exists())
            for secret in (DEVICE_ID, LOCAL_KEY, 'DO-NOT-EMIT'):
                self.assertNotIn(secret, output.getvalue())

    def test_differing_database_copies_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'identity'
            with mock.patch.object(MEDIA, 'APP_SHA256', hashlib.sha256(b'SYNTHETIC-YYOS-APP').hexdigest()), \
                    mock.patch.object(MEDIA, 'verified_archive', return_value=io.BytesIO(
                        archive_bytes(backup_db=database({'other': b'different valid database'})))):
                with self.assertRaisesRegex(MEDIA.MediaError, 'database_copies_differ'):
                    MEDIA.recover_credentials(Path(directory), target)
            self.assertFalse(target.exists())


class FakeTransport:
    def __init__(self, statuses=None, writes=None, received=None, failure=None):
        self.statuses = list(statuses or [{'dps': {'237': False, '239': False}}])
        self.writes = list(writes or [])
        self.received = list(received or [])
        self.failure = failure
        self.calls = []

    def status(self):
        self.calls.append(('status',))
        if self.failure:
            raise RuntimeError(self.failure)
        return self.statuses.pop(0)

    def set_value(self, dp, value):
        self.calls.append(('set', dp, value))
        return self.writes.pop(0) if self.writes else None

    def receive(self):
        self.calls.append(('receive',))
        return self.received.pop(0) if self.received else None

    def close(self):
        self.calls.append(('close',))


OLD_GUARDED = 'OldSyntheticAb1' + 'x' * 9


def native_param(password=OLD_GUARDED, rtsp=False, onvif=False):
    return ('[rtsp]\nrtsp_on_off=%d\nrtsp_password=%s\n[onvif]\nonvif_on_off=%d\nonvif_password=%s\n' %
            (rtsp, password, onvif, password)).encode()


def snapshot_frame(param=None, **changes):
    param = param if param is not None else native_param()
    checksum = hashlib.sha256(param).hexdigest()
    metadata = {'uid': '0', 'hardware': 'AK3918AV130', 'app_sha256': MEDIA.APP_SHA256,
                'busybox_sha256': MEDIA.SSH_BUSYBOX_SHA, 'stock_pid': '446', 'stock_start_time': '100',
                'running_app_sha256': MEDIA.APP_SHA256, 'config_uid': '0', 'config_gid': '0',
                'config_mode': '644', 'config_bytes': str(len(param)), 'config_inode': '81',
                'config_sha256': checksum, 'config_sha256_after': checksum,
                'rtsp_listening': '0', 'onvif_listening': '0', 'param_base64': base64.b64encode(param).decode(),
                'sd_mount_matches': '1', 'sd_visible_dev': str(os.makedev(179, 1)),
                'sd_device_number': 'b3:1', 'sd_magic': '4d44', 'config_mount_matches': '1',
                'config_visible_dev': str(os.makedev(31, 4)), 'config_device_number': '1f:4', 'config_magic': '72b6',
                'mtd_type': 'nor', 'mtd_size': '262144', 'mtd_erasesize': '4096', 'mtd_writesize': '256',
                'mtd_oobsize': '0', 'mtd_offset': '7995392'}
    metadata.update(changes)
    return ('LSCAMOFLASH_YYOS_NATIVE_SNAPSHOT_V1\n' + ''.join(key + '=' + value + '\n'
                                                          for key, value in metadata.items())).encode()


def snapshot(param=None, **changes):
    return MEDIA.parse_ssh_snapshot(snapshot_frame(param, **changes))


class FakeSSH:
    def __init__(self, values):
        self.values, self.calls = list(values), 0

    def snapshot(self):
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class GuardedConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.operation = self.root / 'new-operation'
        self.initial = snapshot()
        self.changed = snapshot(native_param(PASSWORD))
        self.enabled = snapshot(native_param(PASSWORD, True, True), rtsp_listening='1', onvif_listening='1')

    def flow(self, ssh=None, transport=None, old=OLD_GUARDED, operation=None):
        ssh = ssh or FakeSSH([self.initial, self.initial, self.changed, self.enabled])
        transport = transport or FakeTransport(statuses=[{'dps': {'237': False, '239': True}},
                                                         {'dps': {'237': False, '239': True}},
                                                         {'dps': {'237': True, '239': True}}],
                                               writes=[{'dps': {'238': '{"res":"ok"}'}}])
        result = MEDIA.configure_guarded(credentials(), '192.168.88.17', PASSWORD,
                                         self.root / 'owner-key', self.root / 'known-hosts',
                                         operation or self.operation, old_password=old,
                                         ssh_factory=lambda *args: ssh, transport_factory=lambda *args: transport)
        return result, ssh, transport

    def test_guarded_success_has_durable_private_backup_before_password_write(self):
        operation = self.operation
        original = self.initial.param
        class CheckedTransport(FakeTransport):
            def set_value(inner, dp, value):
                self.assertEqual((operation / 'param-before.conf').read_bytes(), original)
                self.assertTrue((operation / 'attempt-started.json').is_file())
                self.assertEqual(operation.stat().st_mode & 0o777, 0o700)
                self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in operation.iterdir()))
                return super().set_value(dp, value)
        transport = CheckedTransport(statuses=[{'dps': {'237': False, '239': True}},
                                               {'dps': {'237': False, '239': True}},
                                               {'dps': {'237': True, '239': True}}],
                                     writes=[{'dps': {'238': '{"res":"ok"}'}}])
        result, ssh, _ = self.flow(transport=transport)
        self.assertTrue(result['configuration_readback_verified'])
        self.assertFalse(result['normal_boot_verified'] or result['write_replay_allowed'])
        writes = [call for call in transport.calls if call[0] == 'set']
        self.assertEqual([call[1] for call in writes], [238, 237])
        self.assertEqual(json.loads(writes[0][2]), {'oldpwd': OLD_GUARDED, 'newpwd': PASSWORD})
        self.assertEqual(writes[1], ('set', 237, True))
        self.assertEqual(ssh.calls, 4)
        self.assertEqual(json.loads((operation / 'attempt-result.json').read_bytes()), result)
        self.assertIs(MEDIA.NATIVE_ENABLEMENT_ALLOWED, False)

    def test_preflight_on_one_on_or_listener_on_refuses_before_tuya_and_journal(self):
        for state in (snapshot(native_param(rtsp=True, onvif=True)), snapshot(native_param(rtsp=True)),
                      snapshot(native_param(onvif=True)), snapshot(rtsp_listening='1'), snapshot(onvif_listening='1')):
            factory = mock.Mock()
            with self.subTest(flags=state.flags), self.assertRaisesRegex(MEDIA.MediaError, 'native_services_must_be_off'):
                MEDIA.configure_guarded(credentials(), '192.168.88.17', PASSWORD, 'key', 'hosts', self.operation,
                                         old_password=OLD_GUARDED, ssh_factory=lambda *args: FakeSSH([state]),
                                         transport_factory=factory)
            factory.assert_not_called()
            self.assertFalse(self.operation.exists())

    def test_read_only_preflight_and_old_password_state(self):
        fake = FakeTransport([{'dps': {'237': False, '239': True}}])
        result = MEDIA.preflight_guarded(credentials(), '192.168.88.17', PASSWORD, 'key', 'hosts',
                                         old_password=OLD_GUARDED, ssh_factory=lambda *args: FakeSSH([self.initial]),
                                         transport_factory=lambda *args: fake)
        self.assertTrue(result['guarded_preflight_passed'])
        self.assertFalse(result['configuration_written'])
        self.assertEqual(fake.calls, [('status',), ('close',)])
        self.assertFalse(self.operation.exists())
        for old in (None, '', 'WrongSyntheticAb1'):
            with self.subTest(old=old), self.assertRaises(MEDIA.MediaError):
                self.flow(old=old)
            self.assertFalse(self.operation.exists())

    def test_missing_default_flags_and_passwords_require_authenticated_default_state(self):
        state = snapshot(b'[dp]\nsiren_onoff=0\n')
        self.assertEqual(state.flags, {'rtsp': False, 'onvif': False})
        self.assertEqual(MEDIA.guarded_old_password(state, {'dp237': False, 'dp239': False}, None), 'admin')
        with self.assertRaises(MEDIA.MediaError):
            MEDIA.guarded_old_password(state, {'dp237': False, 'dp239': True}, OLD_GUARDED)

    def test_duplicate_malformed_and_reordered_ini(self):
        reordered = b'[onvif]\nonvif_password=' + OLD_GUARDED.encode() + b'\nonvif_on_off=0\n[rtsp]\nrtsp_password=' + OLD_GUARDED.encode() + b'\nrtsp_on_off=0\n'
        self.assertEqual(snapshot(reordered).passwords, self.initial.passwords)
        for param in (native_param() + b'[RTSP]\nother=1\n', native_param() + b'ONVIF_PASSWORD=duplicate\n',
                      native_param().replace(b'rtsp_on_off=0', b'rtsp_on_off=01'),
                      native_param() + b'bad assignment\n', native_param() + b'bad=\0\n'):
            with self.subTest(size=len(param)), self.assertRaises(MEDIA.MediaError):
                snapshot(param)

    def test_wrong_identity_geometry_writability_and_snapshot_hash_refuse(self):
        for changes in ({'uid': '1000'}, {'hardware': 'different'}, {'running_app_sha256': '0' * 64},
                        {'app_sha256': '0' * 64}, {'busybox_sha256': '0' * 64}, {'sd_mount_matches': '0'},
                        {'config_mount_matches': '0'}, {'sd_visible_dev': '1'}, {'config_device_number': '1f:5'},
                        {'mtd_writesize': '1'}, {'mtd_type': 'nand'}, {'mtd_oobsize': '16'},
                        {'config_mode': '666'}, {'config_sha256_after': '0' * 64}):
            with self.subTest(changes=changes), self.assertRaises(MEDIA.MediaError):
                snapshot(**changes)
        frame = snapshot_frame()
        for data in (frame + b'uid=0\n', frame.replace(b'uid=0\n', b'uid=0\nuid=0\n'), b'not a frame',
                     frame.replace(b'uid=0\n', b'')):
            with self.assertRaises(MEDIA.MediaError):
                MEDIA.parse_ssh_snapshot(data)

    def test_identity_config_or_tuya_race_refuses_before_write(self):
        for fresh in (snapshot(native_param() + b'; changed bytes\n'), snapshot(stock_start_time='101')):
            operation = self.root / ('race-' + fresh.sha256[:8] + fresh.metadata['stock_start_time'])
            fake = FakeTransport([{'dps': {'237': False, '239': True}}])
            with self.assertRaisesRegex(MEDIA.MediaError, 'live_state_changed_before_write'):
                self.flow(ssh=FakeSSH([self.initial, fresh]), transport=fake, operation=operation)
            self.assertFalse(any(call[0] == 'set' for call in fake.calls))
            self.assertTrue((operation / 'attempt-started.json').exists())
        fake = FakeTransport([{'dps': {'237': False, '239': True}}, {'dps': {'237': True, '239': True}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'live_state_changed_before_write'):
            self.flow(ssh=FakeSSH([self.initial, self.initial]), transport=fake)
        self.assertFalse(any(call[0] == 'set' for call in fake.calls))

    def test_backup_and_attempt_fsync_failures_never_write(self):
        real_fsync = MEDIA.os.fsync
        for failed_call in (1, 2, 8, 9):
            counter = [0]
            def fsync(descriptor):
                counter[0] += 1
                if counter[0] == failed_call:
                    raise OSError('synthetic private failure ' + PASSWORD + LOCAL_KEY)
                return real_fsync(descriptor)
            fake = FakeTransport([{'dps': {'237': False, '239': True}}])
            with self.subTest(failed_call=failed_call), mock.patch.object(MEDIA.os, 'fsync', side_effect=fsync):
                with self.assertRaises(MEDIA.MediaError) as caught:
                    self.flow(transport=fake, operation=self.root / ('fsync-' + str(failed_call)))
            self.assertEqual(caught.exception.phase, 'preservation')
            self.assertFalse(any(call[0] == 'set' for call in fake.calls))
            self.assertNotIn(PASSWORD, str(caught.exception))

    def test_actual_insecure_journal_permissions_refuse_before_secret_or_tuya_write(self):
        real_stat = Path.stat
        def insecure(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if path == self.operation:
                values = list(info); values[0] = (info.st_mode & ~0o777) | 0o777
                return os.stat_result(values)
            return info
        fake = FakeTransport([{'dps': {'237': False, '239': True}}])
        with mock.patch.object(Path, 'stat', insecure), self.assertRaisesRegex(MEDIA.MediaError, 'unsafe_operation_permissions'):
            self.flow(transport=fake)
        self.assertFalse(any(call[0] == 'set' for call in fake.calls))
        self.assertEqual(list(self.operation.iterdir()), [])

    def test_actual_insecure_new_journal_file_refuses_before_any_bytes(self):
        real_fstat = os.fstat
        def insecure(descriptor):
            info = real_fstat(descriptor)
            if stat.S_ISREG(info.st_mode):
                values = list(info); values[0] = (info.st_mode & ~0o777) | 0o777
                return os.stat_result(values)
            return info
        fake = FakeTransport([{'dps': {'237': False, '239': True}}])
        with mock.patch.object(MEDIA.os, 'fstat', insecure), self.assertRaisesRegex(MEDIA.MediaError, 'unsafe_operation_permissions'):
            self.flow(transport=fake)
        self.assertFalse(any(call[0] == 'set' for call in fake.calls))
        self.assertTrue(all(path.stat().st_size == 0 for path in self.operation.iterdir()))

    def test_password_rejection_and_mismatched_readback_never_enable(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': True}}] * 2,
                             writes=[{'dps': {'238': '{"res":"failed","errcode":1}'}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'native_password_rejected') as caught:
            self.flow(transport=fake)
        self.assertEqual(caught.exception.phase, 'password_confirmation')
        self.assertNotIn(('set', 237, True), fake.calls)
        mismatch = native_param(PASSWORD).replace(b'onvif_password=' + PASSWORD.encode(), b'onvif_password=' + OLD_GUARDED.encode())
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': True}}] * 2,
                             writes=[{'dps': {'238': '{"res":"ok"}'}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'native_password_readback_failed') as caught:
            self.flow(ssh=FakeSSH([self.initial, self.initial, snapshot(mismatch)]), transport=fake,
                      operation=self.root / 'mismatch')
        self.assertTrue(caught.exception.password_change_acknowledged)
        self.assertNotIn(('set', 237, True), fake.calls)

    def test_ambiguous_enable_failure_is_journaled_and_cannot_replay(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': True}}] * 2,
                             writes=[{'dps': {'238': '{"res":"ok"}'}}, {'Error': PASSWORD, 'Err': '901'}])
        with self.assertRaises(MEDIA.MediaError) as caught:
            self.flow(transport=fake)
        self.assertEqual(caught.exception.phase, 'media_enable')
        self.assertTrue(caught.exception.media_enable_attempted and caught.exception.operation_journal_preserved)
        result = (self.operation / 'attempt-result.json').read_text()
        for value in (PASSWORD, OLD_GUARDED, LOCAL_KEY, DEVICE_ID):
            self.assertNotIn(value, result)
        factory = mock.Mock()
        with self.assertRaisesRegex(MEDIA.MediaError, 'operation_directory_exists_do_not_replay'):
            MEDIA.configure_guarded(credentials(), '192.168.88.17', PASSWORD, 'key', 'hosts', self.operation,
                                     old_password=OLD_GUARDED, ssh_factory=factory)
        factory.assert_not_called()

    def test_post_enable_partial_flags_fail_without_rollback(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': True}}] * 2,
                             writes=[{'dps': {'238': '{"res":"ok"}'}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'native_configuration_readback_failed') as caught:
            self.flow(ssh=FakeSSH([self.initial, self.initial, self.changed,
                                   snapshot(native_param(PASSWORD, True, False))]), transport=fake)
        self.assertEqual(caught.exception.phase, 'enabled_readback')
        self.assertEqual([call[1] for call in fake.calls if call[0] == 'set'], [238, 237])

    def test_guarded_punctuation_and_symlink_operation_refuse_before_provider(self):
        factory = mock.Mock()
        for password in ('Ab12!@#$%^&*()', PASSWORD):
            target = self.operation
            if password == PASSWORD:
                target.symlink_to(self.root, target_is_directory=True)
            with self.subTest(password=password), self.assertRaises(MEDIA.MediaError):
                MEDIA.configure_guarded(credentials(), '192.168.88.17', password, 'key', 'hosts', target,
                                         old_password=OLD_GUARDED, ssh_factory=factory)
        factory.assert_not_called()

    def test_guarded_final_partial_status_is_read_only_bounded_and_not_merged(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': True}}] * 2 +
                             [{'dps': {'237': True}}, {'dps': {'238': '{"res":"ok"}'}},
                              {'dps': {'237': True, '239': True}}],
                             writes=[{'dps': {'238': '{"res":"ok"}'}}])
        result, _, _ = self.flow(transport=fake)
        self.assertTrue(result['configuration_readback_verified'])
        self.assertEqual(sum(call == ('status',) for call in fake.calls), 5)
        self.assertEqual([call[1] for call in fake.calls if call[0] == 'set'], [238, 237])


class GuardedDisableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.operation = self.root / 'disable-operation'
        self.on = snapshot(native_param(PASSWORD, True, True), rtsp_listening='1', onvif_listening='1')
        self.off = snapshot(native_param(PASSWORD))

    def flow(self, ssh=None, transport=None, operation=None):
        ssh = ssh or FakeSSH([self.on, self.on, self.off])
        transport = transport or FakeTransport(statuses=[{'dps': {'237': True, '239': True}},
                                                         {'dps': {'237': True, '239': True}},
                                                         {'dps': {'237': False, '239': True}}])
        result = MEDIA.disable_guarded(credentials(), '192.168.88.17', self.root / 'key',
                                       self.root / 'hosts', operation or self.operation,
                                       ssh_factory=lambda *args: ssh, transport_factory=lambda *args: transport)
        return result, ssh, transport

    def test_one_disable_after_private_durable_preservation_and_fresh_recheck(self):
        operation = self.operation
        class CheckedTransport(FakeTransport):
            def set_value(inner, dp, value):
                self.assertEqual((operation / 'param-before.conf').read_bytes(), self.on.param)
                self.assertEqual(operation.stat().st_mode & 0o777, 0o700)
                self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in operation.iterdir()))
                for name in ('snapshot-before.json', 'recovery-plan.json', 'attempt-started.json', 'disable-request.json'):
                    self.assertTrue((operation / name).is_file())
                return super().set_value(dp, value)
        fake = CheckedTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2 +
                                          [{'dps': {'237': False, '239': True}}])
        result, ssh, _ = self.flow(transport=fake)
        self.assertTrue(result['disable_attempted'] and result['passwords_unchanged'])
        self.assertFalse(result['noop'] or result['normal_boot_verified'] or result['write_replay_allowed'])
        self.assertEqual([call for call in fake.calls if call[0] == 'set'], [('set', 237, False)])
        self.assertEqual(ssh.calls, 3)
        self.assertEqual(json.loads((operation / 'attempt-result.json').read_bytes()), result)
        self.assertIs(MEDIA.NATIVE_ENABLEMENT_ALLOWED, False)

    def test_both_off_is_read_only_noop_but_existing_directory_refuses(self):
        fake = FakeTransport([{'dps': {'237': False, '239': False}}])
        result, ssh, _ = self.flow(ssh=FakeSSH([self.off]), transport=fake)
        self.assertTrue(result['noop'])
        self.assertFalse(result['disable_attempted'] or result['configuration_written'])
        self.assertEqual(ssh.calls, 1)
        self.assertEqual(fake.calls, [('status',), ('close',)])
        self.assertFalse(self.operation.exists())
        self.operation.mkdir()
        factory = mock.Mock()
        with self.assertRaisesRegex(MEDIA.MediaError, 'operation_directory_exists_do_not_replay'):
            MEDIA.disable_guarded(credentials(), '192.168.88.17', 'key', 'hosts', self.operation,
                                  ssh_factory=factory)
        factory.assert_not_called()

    def test_missing_flags_use_proven_default_off_only_for_read_only_noop(self):
        for param in (b'[dp]\nsiren_onoff=0\n', b'[rtsp]\nrtsp_on_off=0\n'):
            fake = FakeTransport([{'dps': {'237': False, '239': False}}])
            result, _, _ = self.flow(ssh=FakeSSH([snapshot(param)]), transport=fake)
            self.assertTrue(result['noop'])
            self.assertFalse(result['disable_attempted'] or self.operation.exists())
            self.assertEqual(fake.calls, [('status',), ('close',)])

    def test_partial_flags_or_listener_mismatch_refuse_before_tuya_and_journal(self):
        for state in (snapshot(native_param(PASSWORD, True, False)),
                      snapshot(native_param(PASSWORD, False, True)),
                      snapshot(native_param(PASSWORD, True, True)),
                      snapshot(rtsp_listening='1'), snapshot(onvif_listening='1')):
            factory = mock.Mock()
            with self.subTest(flags=state.flags), self.assertRaisesRegex(MEDIA.MediaError, 'native_service_state_mismatch'):
                MEDIA.disable_guarded(credentials(), '192.168.88.17', 'key', 'hosts', self.operation,
                                      ssh_factory=lambda *args: FakeSSH([state]), transport_factory=factory)
            factory.assert_not_called()
            self.assertFalse(self.operation.exists())

    def test_incomplete_or_mismatched_tuya_state_refuses_before_preservation(self):
        for state, response in ((self.on, {'dps': {'237': False, '239': True}}),
                                (self.off, {'dps': {'237': True, '239': True}}),
                                (self.on, {'dps': {'237': True}}),
                                (self.on, {'dps': {'237': True, '239': 'true'}})):
            fake = FakeTransport([response])
            with self.subTest(response=response), self.assertRaises(MEDIA.MediaError):
                self.flow(ssh=FakeSSH([state]), transport=fake)
            self.assertFalse(self.operation.exists())
            self.assertFalse(any(call[0] == 'set' for call in fake.calls))

    def test_full_config_identity_or_tuya_race_never_writes(self):
        for index, fresh in enumerate((snapshot(self.on.param + b'; changed full bytes\n',
                                               rtsp_listening='1', onvif_listening='1'),
                                       snapshot(self.on.param, stock_start_time='101',
                                                rtsp_listening='1', onvif_listening='1'))):
            fake = FakeTransport([{'dps': {'237': True, '239': True}}])
            with self.subTest(index=index), self.assertRaisesRegex(MEDIA.MediaError, 'live_state_changed_before_write'):
                self.flow(ssh=FakeSSH([self.on, fresh]), transport=fake, operation=self.root / ('race-' + str(index)))
            self.assertFalse(any(call[0] == 'set' for call in fake.calls))
        fake = FakeTransport([{'dps': {'237': True, '239': True}}, {'dps': {'237': True, '239': False}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'live_state_changed_before_write'):
            self.flow(ssh=FakeSSH([self.on, self.on]), transport=fake)
        self.assertFalse(any(call[0] == 'set' for call in fake.calls))

    def test_backup_or_request_journal_failure_never_writes(self):
        original = MEDIA.private_new
        for name in ('param-before.conf', 'snapshot-before.json', 'recovery-plan.json',
                     'attempt-started.json', 'disable-request.json'):
            def fail(path, data):
                if path.name == name:
                    raise OSError('private synthetic failure ' + PASSWORD + LOCAL_KEY)
                return original(path, data)
            fake = FakeTransport([{'dps': {'237': True, '239': True}}] * 2)
            with self.subTest(name=name), mock.patch.object(MEDIA, 'private_new', side_effect=fail):
                with self.assertRaises(MEDIA.MediaError) as caught:
                    self.flow(transport=fake, operation=self.root / name)
            self.assertFalse(caught.exception.disable_attempted)
            self.assertFalse(any(call[0] == 'set' for call in fake.calls))
            self.assertNotIn(PASSWORD, str(caught.exception))

    def test_real_directory_or_backup_file_fsync_failure_blocks_disable_write(self):
        original = os.fsync
        for failed_call in (1, 2):
            count = [0]
            def fail(descriptor):
                count[0] += 1
                if count[0] == failed_call:
                    raise OSError('private synthetic failure ' + PASSWORD)
                return original(descriptor)
            fake = FakeTransport([{'dps': {'237': True, '239': True}}])
            with self.subTest(failed_call=failed_call), mock.patch.object(MEDIA.os, 'fsync', side_effect=fail):
                with self.assertRaises(MEDIA.MediaError) as caught:
                    self.flow(transport=fake, operation=self.root / ('fsync-' + str(failed_call)))
            self.assertEqual(caught.exception.phase, 'preservation')
            self.assertFalse(caught.exception.disable_attempted)
            self.assertFalse(any(call[0] == 'set' for call in fake.calls))

    def test_ambiguous_ack_or_transport_exception_verifies_read_only_without_replay(self):
        for index, response in enumerate((None, {'Error': PASSWORD, 'Err': '901'})):
            fake = FakeTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2 +
                                          [{'dps': {'237': False, '239': True}}], writes=[response])
            result, _, _ = self.flow(transport=fake, operation=self.root / ('ack-' + str(index)))
            self.assertEqual(result['disable_response'], 'not_reported' if response is None else 'ambiguous')
            self.assertEqual([call for call in fake.calls if call[0] == 'set'], [('set', 237, False)])
        class RaisedTransport(FakeTransport):
            def set_value(inner, dp, value):
                inner.calls.append(('set', dp, value))
                raise TimeoutError(PASSWORD + LOCAL_KEY)
        fake = RaisedTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2 +
                                        [{'dps': {'237': False, '239': True}}])
        result, _, _ = self.flow(transport=fake)
        self.assertEqual(result['disable_response'], 'ambiguous')
        self.assertEqual([call for call in fake.calls if call[0] == 'set'], [('set', 237, False)])

    def test_delayed_partial_transition_is_bounded_to_five_reads_four_sleeps(self):
        transition = snapshot(native_param(PASSWORD, False, True), onvif_listening='1')
        fake = FakeTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2 +
                                      [{'dps': {'237': False, '239': True}}])
        with mock.patch.object(MEDIA.time, 'sleep') as sleep:
            result, ssh, _ = self.flow(ssh=FakeSSH([self.on, self.on] + [transition] * 4 + [self.off]), transport=fake)
        self.assertTrue(result['both_native_flags_off'])
        self.assertEqual(ssh.calls, 7)
        self.assertEqual(sleep.call_args_list, [mock.call(1)] * 4)
        fake = FakeTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2)
        with mock.patch.object(MEDIA.time, 'sleep') as sleep:
            with self.assertRaisesRegex(MEDIA.MediaError, 'native_disable_readback_timeout') as caught:
                self.flow(ssh=FakeSSH([self.on] * 7), transport=fake, operation=self.root / 'timeout')
        self.assertTrue(caught.exception.disable_attempted and caught.exception.operation_journal_preserved)
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual([call for call in fake.calls if call[0] == 'set'], [('set', 237, False)])

    def test_post_write_identity_or_password_change_refuses_without_rollback(self):
        for name, changed in (('identity', snapshot(self.off.param, stock_start_time='101')),
                              ('password', snapshot(native_param('ChangedAbc123')))):
            fake = FakeTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2)
            with self.subTest(name=name), self.assertRaises(MEDIA.MediaError) as caught:
                self.flow(ssh=FakeSSH([self.on, self.on, changed]), transport=fake, operation=self.root / name)
            self.assertTrue(caught.exception.disable_attempted)
            self.assertEqual([call for call in fake.calls if call[0] == 'set'], [('set', 237, False)])

    def test_final_tuya_requires_one_complete_off_response_and_unchanged_password_state(self):
        for index, responses in enumerate(([{'dps': {'237': False}}, {'dps': {'239': True}}, {'dps': {'237': False}}],
                                            [{'dps': {'237': True, '239': True}}],
                                            [{'dps': {'237': False, '239': False}}])):
            fake = FakeTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2 + responses)
            with self.subTest(index=index), self.assertRaises(MEDIA.MediaError):
                self.flow(transport=fake, operation=self.root / ('status-' + str(index)))
            self.assertEqual([call for call in fake.calls if call[0] == 'set'], [('set', 237, False)])
            self.assertLessEqual(sum(call == ('status',) for call in fake.calls), 5)

    def test_failed_attempt_cannot_replay_before_any_provider(self):
        fake = FakeTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2)
        with mock.patch.object(MEDIA.time, 'sleep'), self.assertRaises(MEDIA.MediaError):
            self.flow(ssh=FakeSSH([self.on] * 7), transport=fake)
        factory = mock.Mock()
        with self.assertRaisesRegex(MEDIA.MediaError, 'operation_directory_exists_do_not_replay'):
            MEDIA.disable_guarded(credentials(), '192.168.88.17', 'key', 'hosts', self.operation,
                                  ssh_factory=factory)
        factory.assert_not_called()

    def test_cli_needs_no_password_and_failure_serializes_attempt_without_secrets(self):
        identity = private_file(self.root / 'credentials', json.dumps(credentials()).encode())
        fake = FakeTransport(statuses=[{'dps': {'237': True, '239': True}}] * 2)
        output = io.StringIO()
        with mock.patch.object(MEDIA, 'SSHProfile', return_value=FakeSSH([self.on] * 7)), \
                mock.patch.object(MEDIA, 'TuyaTransport', return_value=fake), \
                mock.patch.object(MEDIA.time, 'sleep'), contextlib.redirect_stdout(output):
            code = MEDIA.main(['disable-guarded', '--credentials', str(identity), '--host', '192.168.88.17',
                               '--ssh-key', str(self.root / 'key'), '--ssh-known-hosts', str(self.root / 'hosts'),
                               '--operation-directory', str(self.operation)])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertTrue(result['disable_attempted'] and result['operation_journal_preserved'])
        self.assertEqual((result['error'], result['phase']), ('native_disable_readback_timeout', 'disabled_readback'))
        self.assertNotIn('password_change_acknowledged', result)
        for value in (PASSWORD, LOCAL_KEY, DEVICE_ID):
            self.assertNotIn(value, output.getvalue())


class SSHProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = private_file(self.root / 'key', b'-----BEGIN OPENSSH PRIVATE KEY-----\nSYNTHETIC\n-----END OPENSSH PRIVATE KEY-----\n')
        blob = b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(range(32))
        self.hosts = private_file(self.root / 'known_hosts', b'[192.168.88.17]:2222 ssh-ed25519 ' + base64.b64encode(blob) + b'\n')
        self.frame = private_file(self.root / 'frame', snapshot_frame())
        self.args = self.root / 'args'
        self.stdin = self.root / 'stdin'
        self.executable = self.root / 'fake-ssh'
        self.executable.write_text('#!' + os.sys.executable + '\nimport pathlib,sys,json\n' +
                                  'pathlib.Path(' + repr(str(self.args)) + ').write_text(json.dumps(sys.argv[1:]))\n' +
                                  'pathlib.Path(' + repr(str(self.stdin)) + ').write_bytes(sys.stdin.buffer.read())\n' +
                                  'sys.stdout.buffer.write(pathlib.Path(' + repr(str(self.frame)) + ').read_bytes())\n')
        self.executable.chmod(0o755)

    def provider(self):
        return MEDIA.SSHProfile('192.168.88.17', self.key, self.hosts, ssh_executable=self.executable)

    def test_actual_subprocess_uses_pinned_key_fixed_read_only_script(self):
        result = self.provider().snapshot()
        self.assertFalse(any(result.flags.values()))
        args = json.loads(self.args.read_text())
        self.assertEqual(args[:2], ['-F', '/dev/null'])
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('BatchMode=yes', args)
        self.assertIn('ClearAllForwardings=yes', args)
        self.assertIn('PasswordAuthentication=no', args)
        self.assertIn('GlobalKnownHostsFile=/dev/null', args)
        self.assertEqual(args[-3:], ['root@192.168.88.17', '/bin/sh', '-s'])
        self.assertEqual(self.stdin.read_bytes(), MEDIA.SSH_SNAPSHOT_SCRIPT.encode())
        for value in (PASSWORD, OLD_GUARDED, LOCAL_KEY, DEVICE_ID):
            self.assertNotIn(value, self.stdin.read_text())

    def test_known_hosts_filename_spaces_are_quoted_and_expansions_refused(self):
        spaced = private_file(self.root / 'known hosts', self.hosts.read_bytes())
        provider = MEDIA.SSHProfile('192.168.88.17', self.key, spaced, ssh_executable=self.executable)
        provider.snapshot()
        self.assertIn('UserKnownHostsFile="' + str(spaced) + '"', json.loads(self.args.read_text()))
        expansion = private_file(self.root / 'known-%h', self.hosts.read_bytes())
        with self.assertRaisesRegex(MEDIA.MediaError, 'unsupported_ssh_input_path'):
            MEDIA.SSHProfile('192.168.88.17', self.key, expansion, ssh_executable=self.executable)

    def test_bad_host_pin_permissions_changed_inputs_and_symlink_refuse(self):
        original = self.hosts.read_bytes()
        for data in (original.replace(b'192.168.88.17', b'192.168.88.18'), original + original,
                     original.replace(b'[192.168.88.17]:2222', b'*')):
            self.hosts.write_bytes(data)
            with self.assertRaises(MEDIA.MediaError):
                self.provider()
        self.hosts.write_bytes(original)
        provider = self.provider()
        self.hosts.write_bytes(original + b'# changed\n')
        with self.assertRaisesRegex(MEDIA.MediaError, 'ssh_authentication_files_changed'):
            provider.snapshot()
        self.hosts.write_bytes(original);self.hosts.chmod(0o644)
        with self.assertRaises(MEDIA.MediaError):
            self.provider()
        self.assertFalse(self.args.exists())

    def test_subprocess_timeout_oversize_and_invalid_output_are_fixed_errors(self):
        self.frame.write_bytes(b'x' * (MEDIA.SSH_OUTPUT_LIMIT + 1))
        with self.assertRaisesRegex(MEDIA.MediaError, 'ssh_snapshot_failed'):
            self.provider().snapshot()
        self.frame.write_bytes(b'invalid ' + PASSWORD.encode())
        with self.assertRaisesRegex(MEDIA.MediaError, 'invalid_ssh_snapshot'):
            self.provider().snapshot()
        self.executable.write_text('#!' + os.sys.executable + '\nimport time\ntime.sleep(2)\n')
        started = time.monotonic()
        with mock.patch.object(MEDIA, 'SSH_READ_TIMEOUT', 0.1), self.assertRaisesRegex(MEDIA.MediaError, 'ssh_snapshot_failed'):
            self.provider().snapshot()
        self.assertLess(time.monotonic() - started, 1.5)

    def test_preflight_cli_actual_provider_on_camera_refuses_without_tuya_or_output_secrets(self):
        self.frame.write_bytes(snapshot_frame(native_param(PASSWORD, True, True),
                                              rtsp_listening='1', onvif_listening='1'))
        identity = private_file(self.root / 'credentials', json.dumps(credentials()).encode())
        password = private_file(self.root / 'new-password', PASSWORD.encode())
        old = private_file(self.root / 'old-password', OLD_GUARDED.encode())
        output = io.StringIO()
        with mock.patch.object(MEDIA.shutil, 'which', return_value=str(self.executable)), \
                mock.patch.object(MEDIA, 'TuyaTransport') as factory, contextlib.redirect_stdout(output):
            code = MEDIA.main(['preflight-guarded', '--credentials', str(identity), '--host', '192.168.88.17',
                               '--password-file', str(password), '--old-password-file', str(old),
                               '--ssh-key', str(self.key), '--ssh-known-hosts', str(self.hosts)])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual((result['error'], result['phase']), ('native_services_must_be_off', 'ssh_preflight'))
        self.assertFalse(result['password_change_acknowledged'] or result['media_enable_attempted'])
        factory.assert_not_called()
        for value in (PASSWORD, OLD_GUARDED, LOCAL_KEY, DEVICE_ID):
            self.assertNotIn(value, output.getvalue())


class SafetyPolicyTests(unittest.TestCase):
    def test_production_native_enablement_stays_blocked(self):
        self.assertIs(MEDIA.NATIVE_ENABLEMENT_ALLOWED, False)


class TransportTests(unittest.TestCase):
    def setUp(self):
        # Protocol behavior remains testable without enabling live writes.
        guard = mock.patch.object(MEDIA, 'NATIVE_ENABLEMENT_ALLOWED', True)
        guard.start()
        self.addCleanup(guard.stop)

    def test_production_native_enablement_is_blocked_before_transport(self):
        factory = mock.Mock()
        with mock.patch.object(MEDIA, 'NATIVE_ENABLEMENT_ALLOWED', False):
            with self.assertRaisesRegex(MEDIA.MediaError, 'native_enablement_blocked_boot_loop'):
                MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=factory)
        factory.assert_not_called()

    def test_status_is_read_only_and_redacted(self):
        fake = FakeTransport([{'dps': {'237': False, '239': True, '238': PASSWORD,
                                      'other': LOCAL_KEY}, 'device_id': DEVICE_ID}])
        result = MEDIA.request_status(credentials(), '192.168.88.17', transport_factory=lambda *a: fake)
        self.assertFalse(result['dp237'])
        self.assertTrue(result['dp239'])
        self.assertEqual(fake.calls, [('status',), ('close',)])
        for value in (PASSWORD, DEVICE_ID, LOCAL_KEY):
            self.assertNotIn(value, json.dumps(result))

    def test_exact_password_then_boolean_enable_and_status(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': False}},
                                       {'dps': {'237': True, '239': True}}],
                             writes=[{'dps': {'238': '{"res":"ok"}'}}, None])
        result = MEDIA.configure(credentials(), '192.168.88.17', PASSWORD,
                                 transport_factory=lambda *a: fake)
        self.assertTrue(result['dp237'] and result['dp239'])
        self.assertEqual([call[0] for call in fake.calls], ['status', 'set', 'set', 'status', 'close'])
        self.assertEqual(fake.calls[1][1], 238)
        self.assertIs(type(fake.calls[1][2]), str)
        self.assertEqual(json.loads(fake.calls[1][2]), {'oldpwd': 'admin', 'newpwd': PASSWORD})
        self.assertEqual(fake.calls[2], ('set', 237, True))
        self.assertIs(type(fake.calls[2][2]), bool)

    def test_async_password_result_is_bounded(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': False}},
                                       {'dps': {'237': True, '239': True}}],
                             received=[{'dps': {'unrelated': PASSWORD}},
                                       {'dps': {'238': '{"res":"ok"}'}}])
        MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=lambda *a: fake)
        self.assertEqual(sum(call == ('receive',) for call in fake.calls), 2)
        self.assertEqual(fake.calls[-3:], [('set', 237, True), ('status',), ('close',)])

    def test_password_failure_never_enables(self):
        for response in (None, {'dps': {'238': '{"res":"failed","errcode":2}'}},
                         {'dps': {'238': '{"res":"ok","unexpected":true}'}},
                         {'dps': {'238': {'res': 'ok'}}},
                         {'Error': PASSWORD, 'Err': '904', 'Payload': LOCAL_KEY}):
            fake = FakeTransport(writes=[response])
            with self.subTest(response=response), self.assertRaises(MEDIA.MediaError):
                MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=lambda *a: fake)
            self.assertNotIn(('set', 237, True), fake.calls)
            self.assertEqual(fake.calls[-1], ('close',))
            self.assertLessEqual(sum(call == ('receive',) for call in fake.calls), 2)

    def test_nonempty_old_password_requires_private_input(self):
        fake = FakeTransport([{'dps': {'237': False, '239': True}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'old_password_file_required'):
            MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=lambda *a: fake)
        self.assertEqual(fake.calls, [('status',), ('close',)])
        fake = FakeTransport(statuses=[{'dps': {'237': True, '239': True}},
                                       {'dps': {'237': True, '239': True}}],
                             writes=[{'dps': {'238': '{"res":"ok"}'}}])
        MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, 'PreviousPassword12',
                        transport_factory=lambda *a: fake)
        self.assertEqual(json.loads(fake.calls[1][2])['oldpwd'], 'PreviousPassword12')

    def test_exact_firmware_empty_password_comparison_sentinel(self):
        class NativeContract(FakeTransport):
            def __init__(self):
                super().__init__()
                self.media, self.password_changed = False, False

            def status(self):
                self.calls.append(('status',))
                return {'dps': {'237': self.media, '239': self.password_changed}}

            def set_value(self, dp, value):
                self.calls.append(('set', dp, value))
                if dp == 238:
                    # Exact stock0x830bc replaces empty stored password with
                    # literaladmin beforestrcmp@0x830e4. Neither value is MD5.
                    if json.loads(value)['oldpwd'] != 'admin':
                        return {'dps': {'238': '{"res":"failed","errcode":1}'}}
                    self.password_changed = True
                    return {'dps': {'238': '{"res":"ok"}'}}
                self.media = value
                return None

        rejected = NativeContract()
        old_request = json.dumps({'oldpwd': '', 'newpwd': PASSWORD})
        self.assertEqual(json.loads(rejected.set_value(238, old_request)['dps']['238']),
                         {'res': 'failed', 'errcode': 1})
        self.assertFalse(rejected.password_changed or rejected.media)
        for old_password in (None, ''):
            with self.subTest(old_password=old_password):
                native = NativeContract()
                result = MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, old_password,
                                         transport_factory=lambda *a: native)
                self.assertTrue(result['dp237'] and result['dp239'])
                self.assertEqual(json.loads(native.calls[1][2])['oldpwd'], 'admin')
        native = FakeTransport([{'dps': {'237': False, '239': True}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'old_password_state_mismatch'):
            MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, '',
                            transport_factory=lambda *a: native)
        self.assertFalse(any(call[0] == 'set' for call in native.calls))

    def test_invalid_status_and_wrong_profile_never_write(self):
        for response in ({'dps': {'237': 0, '239': False}}, {'dps': {'237': False}},
                         {'Error': PASSWORD, 'Err': '902'}, None):
            fake = FakeTransport([response])
            with self.subTest(response=response), self.assertRaises(MEDIA.MediaError):
                MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=lambda *a: fake)
            self.assertFalse(any(call[0] == 'set' for call in fake.calls))
        identity = credentials()
        identity['app_sha256'] = '0' * 64
        factory = mock.Mock()
        with self.assertRaisesRegex(MEDIA.MediaError, 'unsupported_credentials_profile'):
            MEDIA.request_status(identity, '192.168.88.17', transport_factory=factory)
        factory.assert_not_called()

    def test_post_write_verification_must_match(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': False}},
                                       {'dps': {'237': True, '239': False}}],
                             writes=[{'dps': {'238': '{"res":"ok"}'}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'media_verification_failed'):
            MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=lambda *a: fake)

    def test_final_status_tolerates_only_known_partial_notifications(self):
        good = {'dps': {'237': True, '239': True}}
        for partials in (({'dps': {'237': True}}, {'dps': {'239': True}}),
                         ({'dps': {'238': '{"res":"ok"}'}}, {'dps': {'237': False, '238': '{"res":"ok"}'}})):
            with self.subTest(partials=partials):
                fake = FakeTransport(statuses=[{'dps': {'237': False, '239': False}}, *partials, good],
                                     writes=[{'dps': {'238': '{"res":"ok"}'}}])
                result = MEDIA.configure(credentials(), '192.168.88.17', PASSWORD,
                                         transport_factory=lambda *a: fake)
                self.assertTrue(result['dp237'] and result['dp239'])
                self.assertEqual(sum(call == ('status',) for call in fake.calls), 4)
                self.assertEqual([call[1] for call in fake.calls if call[0] == 'set'], [238, 237])
                self.assertEqual(sum(call == ('receive',) for call in fake.calls), 0)

    def test_final_status_queries_are_bounded_without_combining_partial_flags(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': False}},
                                       {'dps': {'237': True}}, {'dps': {'239': True}},
                                       {'dps': {'238': '{"res":"ok"}'}},
                                       {'dps': {'237': True, '239': True}}],
                             writes=[{'dps': {'238': '{"res":"ok"}'}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'missing_media_status') as caught:
            MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=lambda *a: fake)
        self.assertEqual(caught.exception.phase, 'final_status')
        self.assertTrue(caught.exception.password_change_acknowledged and caught.exception.media_enable_attempted)
        self.assertEqual(sum(call == ('status',) for call in fake.calls), 4)
        self.assertEqual(len(fake.statuses), 1)
        self.assertEqual([call[1] for call in fake.calls if call[0] == 'set'], [238, 237])
        self.assertEqual(fake.calls[-1], ('close',))

    def test_final_status_invalid_notifications_fail_without_another_query(self):
        for response in (None, {'dps': {}}, {'dps': {'unknown': LOCAL_KEY}},
                         {'dps': {'237': True, 'unknown': PASSWORD}},
                         {'dps': {'237': 1}}, {'dps': {'239': 'true'}},
                         {'dps': {'238': {'res': 'ok'}}},
                         {'dps': {'238': '{"res":"ok","extra":true}'}},
                         {'dps': {'237': True, '239': True, '238': 1}},
                         {'Error': PASSWORD, 'Err': '901', 'Payload': LOCAL_KEY}):
            with self.subTest(response=response):
                fake = FakeTransport(statuses=[{'dps': {'237': False, '239': False}}, response,
                                               {'dps': {'237': True, '239': True}}],
                                     writes=[{'dps': {'238': '{"res":"ok"}'}}])
                with self.assertRaises(MEDIA.MediaError) as caught:
                    MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=lambda *a: fake)
                self.assertEqual(caught.exception.phase, 'final_status')
                self.assertEqual(sum(call == ('status',) for call in fake.calls), 2)
                self.assertEqual([call[1] for call in fake.calls if call[0] == 'set'], [238, 237])
                for secret in (PASSWORD, LOCAL_KEY, DEVICE_ID):
                    self.assertNotIn(secret, str(caught.exception))

    def test_final_password_rejection_notification_remains_an_error(self):
        fake = FakeTransport(statuses=[{'dps': {'237': False, '239': False}},
                                       {'dps': {'238': '{"res":"failed","errcode":1}'}}],
                             writes=[{'dps': {'238': '{"res":"ok"}'}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'native_password_rejected') as caught:
            MEDIA.configure(credentials(), '192.168.88.17', PASSWORD, transport_factory=lambda *a: fake)
        self.assertEqual((caught.exception.phase, caught.exception.native_errcode), ('final_status', 1))
        self.assertEqual(sum(call == ('status',) for call in fake.calls), 2)
        self.assertEqual([call[1] for call in fake.calls if call[0] == 'set'], [238, 237])

    def test_standalone_read_only_status_still_requires_complete_response(self):
        fake = FakeTransport(statuses=[{'dps': {'237': True}}, {'dps': {'237': True, '239': True}}])
        with self.assertRaisesRegex(MEDIA.MediaError, 'missing_media_status'):
            MEDIA.request_status(credentials(), '192.168.88.17', transport_factory=lambda *a: fake)
        self.assertEqual(fake.calls, [('status',), ('close',)])

    def test_configure_failure_phases_distinguish_write_progress(self):
        class RequestFailure(FakeTransport):
            def set_value(self, dp, value):
                self.calls.append(('set', dp, value))
                raise RuntimeError(PASSWORD + LOCAL_KEY)

        good = {'dps': {'237': False, '239': False}}
        ok = {'dps': {'238': '{"res":"ok"}'}}
        cases = [
            ('initial_status', FakeTransport([None]), False, False, 'invalid_status_response'),
            ('password_request', RequestFailure(), False, False, 'configuration_request_failed'),
            ('password_confirmation', FakeTransport(writes=[{'dps': {'238': '{"res":"failed","errcode":1}'}}]),
             False, False, 'native_password_rejected'),
            ('media_enable', FakeTransport(writes=[ok, {'Error': PASSWORD, 'Err': '901'}]),
             True, True, 'tuya_transport_error'),
            ('final_status', FakeTransport(statuses=[good, None], writes=[ok, None]),
             True, True, 'invalid_status_response'),
        ]
        for phase, fake, acknowledged, attempted, code in cases:
            with self.subTest(phase=phase), self.assertRaises(MEDIA.MediaError) as result:
                MEDIA.configure(credentials(), '192.168.88.17', PASSWORD,
                                transport_factory=lambda *a: fake)
            self.assertEqual(result.exception.code, code)
            self.assertEqual(result.exception.phase, phase)
            self.assertIs(result.exception.password_change_acknowledged, acknowledged)
            self.assertIs(result.exception.media_enable_attempted, attempted)
            if not attempted:
                self.assertNotIn(('set', 237, True), fake.calls)
            self.assertEqual(fake.calls[-1], ('close',))

    def test_configure_cli_phase_metadata_contains_no_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = private_file(root / 'identity', json.dumps(credentials()).encode())
            password = private_file(root / 'password', PASSWORD.encode())
            fake = FakeTransport(statuses=[{'dps': {'237': False, '239': False}}, None],
                                 writes=[{'dps': {'238': '{"res":"ok"}'}}, None])
            output = io.StringIO()
            with mock.patch.object(MEDIA, 'TuyaTransport', return_value=fake), contextlib.redirect_stdout(output):
                code = MEDIA.main(['configure', '--credentials', str(identity), '--host', '192.168.88.17',
                                   '--password-file', str(password)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue()), {'ok': False, 'error': 'invalid_status_response',
                             'phase': 'final_status', 'password_change_acknowledged': True,
                             'media_enable_attempted': True})
            for secret in (PASSWORD, LOCAL_KEY, DEVICE_ID):
                self.assertNotIn(secret, output.getvalue())

    def test_password_policy_and_file_contents(self):
        for value in ('Ab1shrt', 'A' * 33 + 'a1', 'alllowercase1', 'ALLUPPERCASE1',
                      'NoNumbersHere', 'Has Space12', 'Has\nNewline12', 'NonasciiÄ123', 123, True):
            with self.subTest(value=value), self.assertRaises(MEDIA.MediaError):
                MEDIA.validate_password(value)
        for value in ('Ab123456', PASSWORD, 'Ab12!@#$%^&*()'):
            MEDIA.validate_password(value)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(MEDIA.password_file(private_file(root / 'new', PASSWORD.encode() + b'\r\n')), PASSWORD)
            self.assertEqual(MEDIA.password_file(private_file(root / 'old', b''), old=True), '')

    def test_new_password_fits_exact_native_cache_including_nul(self):
        self.assertEqual(len(PASSWORD.encode('ascii') + b'\0'), 16)
        MEDIA.validate_password(PASSWORD)
        for length in (16, 24, 32):
            value = 'Ab1' + 'x' * (length - 3)
            factory = mock.Mock()
            with self.subTest(length=length), self.assertRaisesRegex(MEDIA.MediaError, 'invalid_password'):
                MEDIA.configure(credentials(), '192.168.88.17', value, transport_factory=factory)
            factory.assert_not_called()
            with tempfile.TemporaryDirectory() as directory:
                path = private_file(Path(directory) / 'new', value.encode('ascii'))
                with self.assertRaisesRegex(MEDIA.MediaError, 'invalid_password'):
                    MEDIA.password_file(path)

    def test_old_password_file_retains_existing_value_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for length in (24, 63):
                value = 'Ab1' + 'x' * (length - 3)
                path = private_file(root / ('old-' + str(length)), value.encode('ascii'))
                self.assertEqual(MEDIA.password_file(path, old=True), value)
            path = private_file(root / 'old-64', b'x' * 64)
            with self.assertRaisesRegex(MEDIA.MediaError, 'invalid_old_password'):
                MEDIA.password_file(path, old=True)

    def test_lan_and_network_bounds_refuse_before_transport(self):
        for host in ('example.com', '8.8.8.8', '127.0.0.1', '::1', '0.0.0.0', '192.168.1.1:6668'):
            factory = mock.Mock()
            with self.subTest(host=host), self.assertRaises(MEDIA.MediaError):
                MEDIA.request_status(credentials(), host, transport_factory=factory)
            factory.assert_not_called()
        for timeout, retries in ((0, 0), (11, 0), (float('nan'), 0), (3, -1), (3, 3), (True, 0)):
            with self.subTest(timeout=timeout, retries=retries), self.assertRaises(MEDIA.MediaError):
                MEDIA.validate_target('192.168.88.17', timeout, retries)

    def test_cli_errors_never_print_secret_exception_or_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            identity = private_file(Path(directory) / 'identity', json.dumps(credentials()).encode())
            fake = FakeTransport(failure=PASSWORD + LOCAL_KEY + DEVICE_ID)
            output = io.StringIO()
            with mock.patch.object(MEDIA, 'TuyaTransport', return_value=fake), contextlib.redirect_stdout(output):
                code = MEDIA.main(['status', '--credentials', str(identity), '--host', '192.168.88.17'])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue()), {'ok': False, 'error': 'status_request_failed'})
            for value in (PASSWORD, LOCAL_KEY, DEVICE_ID):
                self.assertNotIn(value, output.getvalue())

    def test_tinytuya_write_retry_is_disabled_after_session(self):
        module = mock.Mock(__version__='1.20.0')
        with mock.patch.dict('sys.modules', {'tinytuya': module}):
            transport = MEDIA.TuyaTransport(credentials(), '192.168.88.17', 3, 0)
            transport.status()
            transport.set_value(238, 'synthetic-string')
        calls = module.Device.return_value.method_calls
        self.assertIn(mock.call.set_socketPersistent(True), calls)
        self.assertIn(mock.call.set_retry(False), calls)
        self.assertLess(calls.index(mock.call.status()), calls.index(mock.call.set_socketRetryLimit(0)))
        self.assertLess(calls.index(mock.call.set_socketRetryLimit(0)), calls.index(mock.call.set_value(238, 'synthetic-string')))

    def test_tinytuya_child_logger_cannot_emit_credentials(self):
        stream = io.StringIO()
        logger = logging.getLogger('tinytuya.core.fixture')
        previous = logger.handlers[:], logger.level, logger.propagate, logger.disabled
        logger.handlers = [logging.StreamHandler(stream)]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.disabled = False
        module = mock.Mock(__version__='1.20.0')
        def constructor(*args, **kwargs):
            logger.error('%s %s %s', LOCAL_KEY, DEVICE_ID, PASSWORD)
            return mock.Mock()
        module.Device.side_effect = constructor
        try:
            with mock.patch.dict('sys.modules', {'tinytuya': module}):
                MEDIA.TuyaTransport(credentials(), '192.168.88.17', 3, 0)
            self.assertEqual(stream.getvalue(), '')
        finally:
            logger.handlers, logger.level, logger.propagate, logger.disabled = previous

    def test_invalid_cli_arguments_do_not_echo_values(self):
        for extra in (['--local-key', LOCAL_KEY], ['--timeout', PASSWORD], ['--dp', DEVICE_ID]):
            stream = io.StringIO()
            with self.subTest(extra=extra), contextlib.redirect_stderr(stream):
                with self.assertRaises(SystemExit) as result:
                    MEDIA.main(['status', '--credentials', 'private.json', '--host', '192.168.88.17'] + extra)
            self.assertEqual(result.exception.code, 2)
            self.assertEqual(json.loads(stream.getvalue()), {'ok': False, 'error': 'invalid_arguments'})
            for value in (PASSWORD, LOCAL_KEY, DEVICE_ID):
                self.assertNotIn(value, stream.getvalue())


if __name__ == '__main__':
    unittest.main()
