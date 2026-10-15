#!/usr/bin/env python3
"""Synthetic storage and fake LAN transport; never contact or execute a camera."""
import contextlib
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
PASSWORD = 'SyntheticNewPassword1234'


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
        for value in ('Ab123456', PASSWORD, 'HasPunctuation12!@#$%^&*()'):
            MEDIA.validate_password(value)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(MEDIA.password_file(private_file(root / 'new', PASSWORD.encode() + b'\r\n')), PASSWORD)
            self.assertEqual(MEDIA.password_file(private_file(root / 'old', b''), old=True), '')

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
