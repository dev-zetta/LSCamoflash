#!/usr/bin/env python3
"""Exact LSC 3225722 / YYOS 14.1.5 native media control from the owner's backup.

Requires host cryptography; LAN commands additionally require tinytuya==1.20.0.
Credentials and passwords are private files, never command-line values. `status`
only reads. Native enablement is blocked after a boot loop on this exact profile.
The retained configuration protocol is covered by synthetic tests only.
The stock DP238 handler logs its password request: subsequent raw camera logs
must remain private. Web-dashboard authentication does not protect these ports.
This implementation derives storage layout/crypto from the exact backed-up
executable, without executing or redistributing it or copying reference code.
"""
import argparse
import hashlib
import importlib.util
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tarfile
import zlib


REPO = Path(__file__).resolve().parents[2]
PROFILE = 'lsc-3225722-yyos-14.1.5'
FIRMWARE = '14.1.5'
APP_SHA256 = 'd76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7'
FORMAT = 'lscamoflash-yyos-native-credentials-v1'
EMPTY_PASSWORD_WIRE_VALUE = 'admin'
# Combined native enablement caused a confirmed boot loop on the target unit.
# Fixture tests exercise the protocol without permitting production writes.
NATIVE_ENABLEMENT_ALLOWED = False
MAX_DATABASE = 1024 * 1024
PRIVATE_FIELDS = {'format', 'profile', 'firmware_version', 'app_sha256',
                  'device_id', 'local_key', 'protocol_version'}
CONFIGURE_PHASES = {'initial_status', 'password_request', 'password_confirmation',
                    'media_enable', 'final_status'}


class MediaError(Exception):
    """Only fixed public error codes may cross the CLI boundary."""
    def __init__(self, code, native_errcode=None):
        super().__init__(code)
        self.code = code
        self.native_errcode = native_errcode
        self.phase = None
        self.password_change_acknowledged = False
        self.media_enable_attempted = False


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown values, including accidental secrets.
        self.exit(2, '{"ok":false,"error":"invalid_arguments"}\n')


def require(condition, code):
    if not condition:
        raise MediaError(code)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def parse_json(data, code):
    try:
        result = json.loads(data, object_pairs_hook=unique_object)
        require(type(result) is dict, code)
        return result
    except (ValueError, TypeError, UnicodeError):
        raise MediaError(code) from None


def derive_key(enckey):
    require(type(enckey) is bytes and len(enckey) == 16, 'invalid_encryption_key')
    halves = enckey[8:] + enckey[:8]
    return bytes(halves[index ^ 1] for index in range(16))


def decode_database(database, enckey):
    """Validate every descriptor/ciphertext before returning any plaintext."""
    require(type(database) is bytes and 28 <= len(database) <= MAX_DATABASE,
            'invalid_database_size')
    count = struct.unpack_from('<I', database, 24)[0]
    end = 28 + count * 56
    require(0 < count <= 128 and end <= len(database), 'invalid_database_table')
    require(struct.unpack_from('<I', database)[0] == zlib.crc32(database[4:end]),
            'database_header_crc')
    descriptors, names, ranges = [], set(), []
    for number in range(count):
        position = 28 + number * 56
        active = struct.unpack_from('<I', database, position)[0]
        name_field = database[position + 4:position + 37]
        require(active == 1 and b'\0' in name_field, 'invalid_database_record')
        name_bytes = name_field.split(b'\0', 1)[0]
        require(re.fullmatch(rb'[A-Za-z0-9_.-]{1,32}', name_bytes) is not None,
                'invalid_database_record')
        name = name_bytes.decode('ascii')
        offset = struct.unpack_from('<I', database, position + 44)[0]
        length = struct.unpack_from('<H', database, position + 48)[0]
        crc = struct.unpack_from('<I', database, position + 52)[0]
        require(name not in names and length > 0 and length % 16 == 0 and
                offset >= end and offset + length <= len(database), 'invalid_database_record')
        require(all(offset >= high or offset + length <= low for low, high in ranges),
                'overlapping_database_records')
        encrypted = database[offset:offset + length]
        require(zlib.crc32(encrypted) == crc, 'database_record_crc')
        names.add(name)
        ranges.append((offset, offset + length))
        descriptors.append((name, encrypted))
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        raise MediaError('cryptography_required') from None
    cipher = Cipher(algorithms.AES(derive_key(enckey)), modes.ECB())
    records = {}
    for name, encrypted in descriptors:
        decryptor = cipher.decryptor()
        plain = decryptor.update(encrypted) + decryptor.finalize()
        padding = plain[-1]
        require(1 <= padding <= 16 and plain[-padding:] == bytes([padding]) * padding,
                'database_padding')
        records[name] = plain[:-padding]
    return records


def credential_document(records):
    require('gw_di' in records and 'gw_ai' in records, 'missing_identity_records')
    device = parse_json(records['gw_di'].rstrip(b'\0'), 'invalid_device_record')
    active = parse_json(records['gw_ai'].rstrip(b'\0'), 'invalid_activation_record')
    require(device.get('swv') == FIRMWARE and device.get('dev_swv') == FIRMWARE,
            'unsupported_firmware')
    require(type(device.get('lpv')) in (str, float) and device['lpv'] in ('3.5', 3.5),
            'unsupported_protocol')
    document = {'format': FORMAT, 'profile': PROFILE, 'firmware_version': FIRMWARE,
                'app_sha256': APP_SHA256, 'device_id': device.get('id'),
                'local_key': active.get('lckey'), 'protocol_version': 3.5}
    validate_credentials(document)
    return document


def validate_credentials(document):
    require(type(document) is dict and set(document) == PRIVATE_FIELDS,
            'invalid_credentials_schema')
    require(document.get('format') == FORMAT and document.get('profile') == PROFILE and
            document.get('firmware_version') == FIRMWARE and
            document.get('app_sha256') == APP_SHA256, 'unsupported_credentials_profile')
    require(type(document.get('protocol_version')) in (float, int) and
            document['protocol_version'] == 3.5, 'unsupported_protocol')
    identity, key = document.get('device_id'), document.get('local_key')
    require(type(identity) is str and re.fullmatch(r'[A-Za-z0-9]{22}', identity) is not None,
            'invalid_device_id')
    require(type(key) is str and len(key) == 16 and all(33 <= ord(c) <= 126 for c in key),
            'invalid_local_key')
    return document


def private_bytes(path, maximum):
    """No symlink, device, oversized, other-owner or group/world-readable input."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                    info.st_mode & 0o077 == 0 and info.st_size <= maximum,
                    'unsafe_private_file')
            data = stream.read(maximum + 1)
            require(len(data) <= maximum, 'unsafe_private_file')
            return data
    except OSError:
        raise MediaError('private_file_unreadable') from None


def load_credentials(path):
    return validate_credentials(parse_json(private_bytes(path, 16384), 'invalid_credentials_json'))


def password_file(path, old=False):
    data = private_bytes(path, 128)
    # Permit exactly one conventional terminal newline, not arbitrary trimming.
    if data.endswith(b'\n'):
        data = data[:-1]
        if data.endswith(b'\r'):
            data = data[:-1]
    try:
        password = data.decode('ascii')
    except UnicodeError:
        raise MediaError('invalid_password') from None
    if old:
        require(len(password) <= 63 and all(33 <= ord(c) <= 126 for c in password),
                'invalid_old_password')
    else:
        validate_password(password)
    return password


def validate_password(password):
    require(type(password) is str and 8 <= len(password) <= 32 and
            all(33 <= ord(c) <= 126 for c in password) and
            re.search(r'[0-9]', password) is not None and
            re.search(r'[a-z]', password) is not None and
            re.search(r'[A-Z]', password) is not None, 'invalid_password')


def verified_archive(run):
    stream = None
    try:
        spec = importlib.util.spec_from_file_location('yyos_backup_verifier',
                                                     REPO / 'tools/firmware-backup/verify-backup.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        result = verifier.verify(Path(run))
        require(result.get('verified') is True and result.get('partition_count') == 6 and
                result.get('total_partition_bytes') == 8388608, 'unsupported_backup_profile')
        root = Path(run).resolve(strict=True)
        # Bind the archive subsequently read to the checksum the verifier checked.
        checksums = dict((line[66:], line[:64]) for line in
                         (root / 'SHA256SUMS').read_text().splitlines())
        archive_path = verifier.safe_file(root, 'stock-userspace.tar')
        stream = archive_path.open('rb')
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        require(digest.hexdigest() == checksums['stock-userspace.tar'], 'backup_changed')
        stream.seek(0)
        return stream
    except MediaError:
        if stream is not None:
            stream.close()
        raise
    except Exception:
        if stream is not None:
            stream.close()
        raise MediaError('backup_verification_failed') from None


def recover_credentials(run, output):
    wanted = {'appfs/bin/yy_cam': 8 * 1024 * 1024,
              'config/tuya/tuya_enckey.db': 16,
              'config/tuya/tuya_user.db': MAX_DATABASE,
              'config/tuya/tuya_user.db_bak': MAX_DATABASE}
    found = {}
    try:
        with verified_archive(run) as stream, tarfile.open(fileobj=stream, mode='r:') as archive:
            for number, member in enumerate(archive):
                require(number < 4096, 'archive_member_limit')
                name = member.name
                while name.startswith('./'):
                    name = name[2:]
                if name not in wanted:
                    continue
                require(name not in found and member.isfile() and
                        0 < member.size <= wanted[name], 'invalid_archive_input')
                source = archive.extractfile(member)
                require(source is not None, 'invalid_archive_input')
                with source:
                    found[name] = source.read(wanted[name] + 1)
                require(len(found[name]) == member.size, 'invalid_archive_input')
        require(set(found) == set(wanted), 'missing_archive_inputs')
        require(hashlib.sha256(found['appfs/bin/yy_cam']).hexdigest() == APP_SHA256,
                'unsupported_stock_binary')
        require(found['config/tuya/tuya_user.db'] == found['config/tuya/tuya_user.db_bak'],
                'database_copies_differ')
        document = credential_document(decode_database(found['config/tuya/tuya_user.db'],
                                                       found['config/tuya/tuya_enckey.db']))
        destination = Path(output).absolute()
        require(not any(p.is_symlink() for p in (destination, *destination.parents)),
                'unsafe_output_path')
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as target:
                os.fchmod(target.fileno(), 0o600)
                json.dump(document, target, indent=2)
                target.write('\n')
                target.flush()
                os.fsync(target.fileno())
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            destination.unlink()
            raise
        return {'ok': True, 'profile': PROFILE, 'protocol_version': 3.5,
                'credentials_written': True}
    except MediaError:
        raise
    except (OSError, ValueError, tarfile.TarError):
        raise MediaError('credential_recovery_failed') from None


def validate_target(host, timeout, retries):
    try:
        address = ipaddress.IPv4Address(host)
        allowed = any(address in ipaddress.IPv4Network(net) for net in
                      ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        require(allowed, 'invalid_lan_address')
    except (ValueError, TypeError):
        raise MediaError('invalid_lan_address') from None
    require(type(timeout) in (int, float) and 1 <= timeout <= 10 and
            type(retries) is int and 0 <= retries <= 2, 'invalid_network_bounds')


class TuyaTransport:
    def __init__(self, credentials, host, timeout, retries):
        try:
            import tinytuya
        except ImportError:
            raise MediaError('tinytuya_required') from None
        # Retry handling below is audited against this version's implementation.
        require(tinytuya.__version__ == '1.20.0', 'unsupported_tinytuya_version')
        for name in ['tinytuya', *list(logging.Logger.manager.loggerDict)]:
            if name == 'tinytuya' or name.startswith('tinytuya.'):
                logger = logging.getLogger(name)
                logger.handlers.clear()
                logger.addHandler(logging.NullHandler())
                logger.propagate = False
                logger.setLevel(logging.CRITICAL + 1)
                logger.disabled = True
        self.device = tinytuya.Device(credentials['device_id'], host, credentials['local_key'],
                                     version=3.5, connection_timeout=timeout,
                                     connection_retry_limit=retries + 1)
        self.device.set_socketPersistent(True)
        self.device.set_socketRetryDelay(0.1)
        self.device.set_retry(False)

    def status(self):
        return self.device.status()

    def set_value(self, dp, value):
        # Keep the authenticated socket, but never replay a write after timeout.
        # With limit0 TinyTuya also refuses to reconnect a lost socket for a write.
        self.device.set_socketRetryLimit(0)
        return self.device.set_value(dp, value)

    def receive(self):
        return self.device.receive()

    def close(self):
        self.device.close()


def response_error(response):
    if type(response) is dict and ('Error' in response or 'Err' in response):
        code = response.get('Err')
        number = int(code) if type(code) in (str, int) and re.fullmatch(r'[0-9]{1,4}', str(code)) else None
        raise MediaError('tuya_transport_error', number)


def safe_status(response):
    response_error(response)
    require(type(response) is dict and type(response.get('dps')) is dict, 'invalid_status_response')
    dps = response['dps']
    require(type(dps.get('237')) is bool and type(dps.get('239')) is bool,
            'missing_media_status')
    return {'ok': True, 'profile': PROFILE, 'protocol_version': 3.5,
            'dp237': dps['237'], 'dp239': dps['239']}


def request_status(credentials, host, timeout=3, retries=0, transport_factory=None):
    validate_credentials(credentials)
    validate_target(host, timeout, retries)
    transport = None
    try:
        transport = (transport_factory or TuyaTransport)(credentials, host, timeout, retries)
        return safe_status(transport.status())
    except MediaError:
        raise
    except Exception:
        raise MediaError('status_request_failed') from None
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass


def password_result(response):
    response_error(response)
    if type(response) is not dict or type(response.get('dps')) is not dict or '238' not in response['dps']:
        return False
    value = response['dps']['238']
    require(type(value) is str and len(value) <= 255, 'invalid_password_response')
    result = parse_json(value, 'invalid_password_response')
    if result == {'res': 'ok'}:
        return True
    number = result.get('errcode')
    require(type(number) is int and 0 <= number <= 255 and result.get('res') == 'failed',
            'invalid_password_response')
    raise MediaError('native_password_rejected', number)


def configure(credentials, host, password, old_password=None, timeout=3, retries=0,
              transport_factory=None):
    require(NATIVE_ENABLEMENT_ALLOWED, 'native_enablement_blocked_boot_loop')
    validate_credentials(credentials)
    validate_target(host, timeout, retries)
    validate_password(password)
    require(old_password is None or (type(old_password) is str and len(old_password) <= 63 and
            all(33 <= ord(c) <= 126 for c in old_password)), 'invalid_old_password')
    transport = None
    phase = 'initial_status'
    password_change_acknowledged = False
    media_enable_attempted = False
    try:
        transport = (transport_factory or TuyaTransport)(credentials, host, timeout, retries)
        before = safe_status(transport.status())  # No writes before authenticated status.
        if old_password is None:
            require(before['dp239'] is False, 'old_password_file_required')
            old_password = EMPTY_PASSWORD_WIRE_VALUE
        elif old_password == '':
            require(before['dp239'] is False, 'old_password_state_mismatch')
            old_password = EMPTY_PASSWORD_WIRE_VALUE
        # Exact firmware@0x830bc substitutes literal "admin" before comparing
        # oldpwd when the stored password is empty. This is a wire sentinel,
        # not the native RTSP/ONVIF password and not a hash of the old password.
        payload = json.dumps({'oldpwd': old_password, 'newpwd': password}, separators=(',', ':'))
        require(len(payload) <= 255, 'invalid_password_request')
        phase = 'password_request'
        response = transport.set_value(238, payload)
        phase = 'password_confirmation'
        accepted = password_result(response)
        for _ in range(2):
            if accepted:
                break
            accepted = password_result(transport.receive())
        require(accepted, 'password_confirmation_missing')
        password_change_acknowledged = True
        # A successful password response is mandatory before media enablement.
        phase = 'media_enable'
        media_enable_attempted = True
        response_error(transport.set_value(237, True))
        phase = 'final_status'
        after = safe_status(transport.status())
        require(after['dp237'] is True and after['dp239'] is True, 'media_verification_failed')
        return after
    except MediaError as error:
        error.phase = phase
        error.password_change_acknowledged = password_change_acknowledged
        error.media_enable_attempted = media_enable_attempted
        raise
    except Exception:
        error = MediaError('configuration_request_failed')
        error.phase = phase
        error.password_change_acknowledged = password_change_acknowledged
        error.media_enable_attempted = media_enable_attempted
        raise error from None
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    credentials = subparsers.add_parser('credentials', help='offline verified-backup recovery; never prints keys')
    credentials.add_argument('--backup-run', type=Path, required=True)
    credentials.add_argument('--output', type=Path, required=True, help='new private0600 JSON; never overwritten')
    for command in ('status', 'configure'):
        sub = subparsers.add_parser(command, help='read-only status' if command == 'status' else
                                   'blocked: this firmware encountered a native-service boot loop')
        sub.add_argument('--credentials', type=Path, required=True)
        sub.add_argument('--host', required=True, help='explicit RFC1918 IPv4 address; no autodiscovery/cloud')
        sub.add_argument('--timeout', type=float, default=3, help='socket timeout1..10seconds')
        sub.add_argument('--retries', type=int, default=0, help='additional connection attempts0..2; writes never replayed')
        if command == 'configure':
            sub.add_argument('--password-file', type=Path, required=True)
            sub.add_argument('--old-password-file', type=Path,
                             help='required when DP239 is true; omitted only for the firmware default-password state')
    args = parser.parse_args(argv)
    try:
        if args.command == 'credentials':
            result = recover_credentials(args.backup_run, args.output)
        else:
            identity = load_credentials(args.credentials)
            if args.command == 'status':
                result = request_status(identity, args.host, args.timeout, args.retries)
            else:
                password = password_file(args.password_file)
                old_password = password_file(args.old_password_file, old=True) if args.old_password_file else None
                result = configure(identity, args.host, password, old_password, args.timeout, args.retries)
    except MediaError as error:
        result = {'ok': False, 'error': error.code}
        if error.native_errcode is not None:
            result['native_errcode'] = error.native_errcode
        if error.phase in CONFIGURE_PHASES:
            result.update(phase=error.phase,
                          password_change_acknowledged=error.password_change_acknowledged,
                          media_enable_attempted=error.media_enable_attempted)
        print(json.dumps(result, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({'ok': False, 'error': 'operation_failed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
