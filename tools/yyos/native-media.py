#!/usr/bin/env python3
"""Exact LSC 3225722 / YYOS 14.1.5 native media control from the owner's backup.

Requires host cryptography; LAN commands additionally require tinytuya==1.20.0.
Credentials and passwords are private files, never command-line values. `status`
and `preflight-guarded` only read. Legacy `configure` remains blocked. The explicit
`configure-guarded` path requires a pinned owner SSH session, both services off,
a durable private configuration backup and a new one-attempt journal directory.
Guarded writes require alphanumeric passwords and never auto-disable or replay.
New passwords are limited to 8–15 ASCII bytes: this firmware copies them into
16-byte native RTSP/ONVIF caches including the terminating NUL.
The stock DP238 handler logs its password request: subsequent raw camera logs
must remain private. Web-dashboard authentication does not protect these ports.
This implementation derives storage layout/crypto from the exact backed-up
executable, without executing or redistributing it or copying reference code.
"""
import argparse
import base64
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
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
# DP238 accepts up to 32 bytes, but the exact native managers use 16-byte caches
# with strcpy (RTSP@0x2550e8/0x255144, ONVIF@0x2300ac/0x230108).
MAX_NEW_PASSWORD_BYTES = 15
MAX_DATABASE = 1024 * 1024
PRIVATE_FIELDS = {'format', 'profile', 'firmware_version', 'app_sha256',
                  'device_id', 'local_key', 'protocol_version'}
CONFIGURE_PHASES = {'initial_status', 'password_request', 'password_confirmation',
                    'media_enable', 'final_status', 'ssh_preflight', 'preservation',
                    'ssh_recheck', 'password_readback', 'enabled_readback', 'operation_record'}
SSH_BUSYBOX_SHA = '052b061b58196c56792b6e950fa6535f2c89732b311adfdd815521213e625aa8'
SSH_OUTPUT_LIMIT = 100 * 1024
SSH_READ_TIMEOUT = 30

# Fixed read-only commands only. The base64 configuration frame is captured
# privately by the host; neither shell parameters nor commands come from CLI.
SSH_SNAPSHOT_SCRIPT = r'''set -eu
LC_ALL=C; export LC_ALL
BB=/mnt/sdcard/LSCamoflash-yyos-ssh/bin/busybox
bb() { "$BB" timeout -k 1 5 "$BB" "$@"; }
emit() { printf '%s=%s\n' "$1" "$2"; }
for path in /appfs /appfs/bin /appfs/bin/yy_cam /config /config/param.conf /mnt /mnt/sdcard /mnt/sdcard/LSCamoflash-yyos-ssh /mnt/sdcard/LSCamoflash-yyos-ssh/bin "$BB" /dev/mmcblk0p1 /dev/mtdblock4; do
 [ ! -L "$path" ] || exit 1
done
[ -f "$BB" ] && [ -x "$BB" ] && [ -f /config/param.conf ] && [ -b /dev/mmcblk0p1 ] && [ -b /dev/mtdblock4 ] || exit 1
printf 'LSCAMOFLASH_YYOS_NATIVE_SNAPSHOT_V1\n'
emit uid "$(bb id -u)"
emit hardware "$(bb awk -F: '/^Hardware[ \t]*:/{gsub(/^[ \t]+|[ \t]+$/,"",$2);print $2}' /proc/cpuinfo)"
emit app_sha256 "$(bb sha256sum /appfs/bin/yy_cam | bb awk '{print $1}')"
emit busybox_sha256 "$(bb sha256sum "$BB" | bb awk '{print $1}')"
set -- $(bb pidof yy_cam)
[ "$#" = 1 ] || exit 1
case "$1" in ''|*[!0-9]*) exit 1;; esac
[ "$1" -gt 1 ] && [ "$(bb readlink /proc/"$1"/exe)" = /appfs/bin/yy_cam ] || exit 1
emit stock_pid "$1"
emit stock_start_time "$(bb sed 's/^.*) //' /proc/"$1"/stat | bb awk '{print $20}')"
emit running_app_sha256 "$(bb sha256sum /proc/"$1"/exe | bb awk '{print $1}')"
mount_facts() {
 prefix=$1; point=$2; device=$3; fs=$4
 emit "${prefix}_mount_matches" "$(bb awk -v p="$point" -v d="$device" -v fs="$fs" '$1==d && $2==p && $3==fs && "," $4 "," ~ /,rw,/ {n++} END{print n+0}' /proc/mounts)"
 emit "${prefix}_visible_dev" "$(bb stat -c %d "$point")"
 emit "${prefix}_device_number" "$(bb stat -c %t:%T "$device")"
 emit "${prefix}_magic" "$(bb stat -f -c %t "$point")"
}
mount_facts sd /mnt/sdcard /dev/mmcblk0p1 vfat
mount_facts config /config /dev/mtdblock4 jffs2
for field in type size erasesize writesize oobsize offset; do emit "mtd_${field}" "$(bb cat /sys/class/mtd/mtd4/"$field")"; done
set -- $(bb stat -c '%u %g %a %s %i' /config/param.conf)
[ "$#" = 5 ] || exit 1
emit config_uid "$1"; emit config_gid "$2"; emit config_mode "$3"; emit config_bytes "$4"; emit config_inode "$5"
[ "$4" -gt 0 ] && [ "$4" -le 65536 ] || exit 1
emit config_sha256 "$(bb sha256sum /config/param.conf | bb awk '{print $1}')"
listeners=$(bb netstat -tln)
emit rtsp_listening "$(printf '%s\n' "$listeners" | bb awk '($1=="tcp" || $1=="tcp6") && $4~/:8554$/ && $6=="LISTEN"{yes=1} END{print yes+0}')"
emit onvif_listening "$(printf '%s\n' "$listeners" | bb awk '($1=="tcp" || $1=="tcp6") && $4~/:5000$/ && $6=="LISTEN"{yes=1} END{print yes+0}')"
emit param_base64 "$(bb base64 /config/param.conf | bb tr -d '\n')"
emit config_sha256_after "$(bb sha256sum /config/param.conf | bb awk '{print $1}')"
'''


class ProfileSnapshot:
    """Private values deliberately have no data-bearing repr or CLI serializer."""
    def __init__(self, metadata, param, flags, passwords):
        self.metadata, self.param, self.flags, self.passwords = metadata, param, flags, passwords
        self.sha256 = hashlib.sha256(param).hexdigest()
        self.identity = {key: value for key, value in metadata.items()
                         if not key.startswith('config_') and key not in
                         {'param_base64', 'rtsp_listening', 'onvif_listening'}}


def parse_native_ini(param):
    require(type(param) is bytes and 0 < len(param) <= 65536 and
            all(value >= 32 or value in (9, 10, 13) for value in param) and 127 not in param,
            'invalid_native_configuration')
    section = None
    sections, keys, flags, passwords = set(), set(), {}, {}
    for raw in param.split(b'\n'):
        line = raw[:-1] if raw.endswith(b'\r') else raw
        require(b'\r' not in line, 'invalid_native_configuration')
        if not line.strip(b' \t') or re.match(rb'[ \t]*[;#]', line):
            continue
        if re.match(rb'[ \t]*\[', line):
            match = re.fullmatch(rb'[ \t]*\[([A-Za-z0-9_.-]+)\][ \t]*(?:[;#].*)?', line)
            require(match is not None, 'invalid_native_configuration')
            section = match[1].lower()
            require(section not in sections, 'duplicate_native_configuration')
            sections.add(section)
            continue
        match = re.fullmatch(rb'[ \t]*([A-Za-z0-9_.-]+)[ \t]*=(.*)', line)
        require(section is not None and match is not None, 'invalid_native_configuration')
        identity = section, match[1].lower()
        require(identity not in keys, 'duplicate_native_configuration')
        keys.add(identity)
        if identity in ((b'rtsp', b'rtsp_on_off'), (b'onvif', b'onvif_on_off')):
            value = re.fullmatch(rb'[ \t]*([01])[ \t]*(?:[;#].*)?', match[2])
            require(value is not None, 'invalid_native_flag')
            flags[section.decode()] = value[1] == b'1'
        if identity in ((b'rtsp', b'rtsp_password'), (b'onvif', b'onvif_password')):
            value = match[2].strip(b' \t')
            # Initial guarded writes use alphanumeric passwords. Existing
            # complex escaped representations are refused before mutation.
            if value[:1] in (b'"', b"'"):
                require(len(value) >= 2 and value[-1:] == value[:1] and
                        value[:1] not in value[1:-1], 'unsupported_password_encoding')
                value = value[1:-1]
            else:
                require(b';' not in value and b'#' not in value and b'"' not in value and b"'" not in value,
                        'unsupported_password_encoding')
            require(len(value) <= 63 and all(33 <= byte <= 126 for byte in value) and b'\\' not in value,
                    'unsupported_password_encoding')
            passwords[section.decode()] = value.decode('ascii')
    return ({name: flags.get(name, False) for name in ('rtsp', 'onvif')},
            {name: passwords.get(name, '') for name in ('rtsp', 'onvif')})


def parse_ssh_snapshot(data):
    require(type(data) is bytes and len(data) <= SSH_OUTPUT_LIMIT, 'invalid_ssh_snapshot')
    lines = data.split(b'\n')
    require(lines[0] == b'LSCAMOFLASH_YYOS_NATIVE_SNAPSHOT_V1' and lines[-1] == b'', 'invalid_ssh_snapshot')
    metadata = {}
    for line in lines[1:-1]:
        key, separator, value = line.partition(b'=')
        require(separator and re.fullmatch(rb'[a-z][a-z0-9_]*', key) is not None, 'invalid_ssh_snapshot')
        key = key.decode('ascii')
        require(key not in metadata, 'invalid_ssh_snapshot')
        try:
            metadata[key] = value.decode('ascii')
        except UnicodeError:
            raise MediaError('invalid_ssh_snapshot') from None
    expected = {'uid', 'hardware', 'app_sha256', 'busybox_sha256', 'stock_pid', 'stock_start_time',
                'running_app_sha256', 'config_uid', 'config_gid', 'config_mode', 'config_bytes',
                'config_inode', 'config_sha256', 'config_sha256_after', 'rtsp_listening',
                'onvif_listening', 'param_base64'}
    expected |= {prefix + '_' + key for prefix in ('sd', 'config')
                 for key in ('mount_matches', 'visible_dev', 'device_number', 'magic')}
    geometry = {'type': 'nor', 'size': '262144', 'erasesize': '4096', 'writesize': '256',
                'oobsize': '0', 'offset': '7995392'}
    expected |= {'mtd_' + key for key in geometry}
    require(set(metadata) == expected, 'invalid_ssh_snapshot')
    require(metadata['uid'] == '0' and metadata['hardware'] == 'AK3918AV130' and
            metadata['app_sha256'] == metadata['running_app_sha256'] == APP_SHA256 and
            metadata['busybox_sha256'] == SSH_BUSYBOX_SHA, 'unsupported_live_profile')
    for key in ('stock_pid', 'stock_start_time', 'config_inode', 'config_bytes'):
        require(re.fullmatch(r'[1-9][0-9]{0,19}', metadata[key]) is not None, 'invalid_ssh_snapshot')
    require(int(metadata['stock_pid']) > 1 and int(metadata['config_bytes']) <= 65536,
            'invalid_ssh_snapshot')
    require(metadata['config_uid'] == metadata['config_gid'] == '0' and
            re.fullmatch(r'[0-7]{3}', metadata['config_mode']) is not None and
            int(metadata['config_mode'], 8) & 0o022 == 0, 'unsafe_live_configuration')
    for prefix, magic in (('sd', '4d44'), ('config', '72b6')):
        require(metadata[prefix + '_mount_matches'] == '1' and metadata[prefix + '_magic'] == magic,
                'unsupported_live_mount')
        pair = metadata[prefix + '_device_number']
        require(re.fullmatch(r'[0-9a-fA-F]{1,5}:[0-9a-fA-F]{1,5}', pair) is not None and
                re.fullmatch(r'[0-9]{1,20}', metadata[prefix + '_visible_dev']) is not None,
                'unsupported_live_mount')
        major, minor = (int(part, 16) for part in pair.split(':'))
        require((major, minor) == ((179, 1) if prefix == 'sd' else (31, 4)) and
                int(metadata[prefix + '_visible_dev']) == os.makedev(major, minor), 'unsupported_live_mount')
    require(all(metadata['mtd_' + key] == value for key, value in geometry.items()), 'unsupported_live_geometry')
    require(all(metadata[key] in ('0', '1') for key in ('rtsp_listening', 'onvif_listening')),
            'invalid_ssh_snapshot')
    try:
        param = base64.b64decode(metadata['param_base64'], validate=True)
    except (ValueError, TypeError):
        raise MediaError('invalid_ssh_snapshot') from None
    require(base64.b64encode(param).decode() == metadata['param_base64'] and
            len(param) == int(metadata['config_bytes']) and
            hashlib.sha256(param).hexdigest() == metadata['config_sha256'] == metadata['config_sha256_after'],
            'configuration_snapshot_changed')
    flags, passwords = parse_native_ini(param)
    return ProfileSnapshot(metadata, param, flags, passwords)


class SSHProfile:
    def __init__(self, host, client_key, known_hosts, timeout=3, ssh_executable=None):
        validate_target(host, timeout, 0)
        self.host, self.timeout = host, timeout
        self.client_key, self.known_hosts = Path(client_key).absolute(), Path(known_hosts).absolute()
        for path in (self.client_key, self.known_hosts):
            # These filenames also enter OpenSSH configuration parsing. Refuse
            # expansion/quoting metacharacters; ordinary spaces are quoted.
            require(re.fullmatch(r'/[A-Za-z0-9_./ -]+', str(path)) is not None,
                    'unsupported_ssh_input_path')
            require(not any(part.is_symlink() for part in (path, *path.parents)), 'unsafe_private_file')
        key = private_bytes(self.client_key, 16384)
        require(key.startswith(b'-----BEGIN OPENSSH PRIVATE KEY-----\n'), 'invalid_ssh_client_key')
        hosts = private_bytes(self.known_hosts, 4096)
        rows = [line.split() for line in hosts.splitlines() if line.strip() and not line.lstrip().startswith(b'#')]
        require(len(rows) == 1 and len(rows[0]) == 3 and rows[0][0] == ('[' + host + ']:2222').encode() and
                rows[0][1] == b'ssh-ed25519', 'invalid_ssh_host_pin')
        try:
            blob = base64.b64decode(rows[0][2], validate=True)
        except (ValueError, TypeError):
            raise MediaError('invalid_ssh_host_pin') from None
        require(len(blob) == 51 and blob[:19] == b'\0\0\0\x0bssh-ed25519\0\0\0\x20', 'invalid_ssh_host_pin')
        self.input_hashes = hashlib.sha256(key).digest(), hashlib.sha256(hosts).digest()
        self.executable = ssh_executable or shutil.which('ssh')
        require(self.executable is not None, 'openssh_required')

    def snapshot(self):
        require(self.input_hashes == (hashlib.sha256(private_bytes(self.client_key, 16384)).digest(),
                                      hashlib.sha256(private_bytes(self.known_hosts, 4096)).digest()),
                'ssh_authentication_files_changed')
        command = [str(self.executable), '-F', '/dev/null', '-T', '-p', '2222', '-i', str(self.client_key),
                   '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'UserKnownHostsFile="' + str(self.known_hosts) + '"', '-o', 'GlobalKnownHostsFile=/dev/null',
                   '-o', 'UpdateHostKeys=no', '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
                   '-o', 'ClearAllForwardings=yes', '-o', 'ForwardAgent=no', '-o', 'ConnectionAttempts=1',
                   '-o', 'ConnectTimeout=' + str(int(self.timeout)), '-o', 'LogLevel=ERROR',
                   'root@' + self.host, '/bin/sh', '-s']
        try:
            import resource
            def cap_output():
                resource.setrlimit(resource.RLIMIT_FSIZE, (SSH_OUTPUT_LIMIT, SSH_OUTPUT_LIMIT))
            with tempfile.TemporaryFile() as output:
                result = subprocess.run(command, input=SSH_SNAPSHOT_SCRIPT.encode(), stdout=output,
                                        stderr=subprocess.DEVNULL, timeout=SSH_READ_TIMEOUT, preexec_fn=cap_output)
                require(result.returncode == 0, 'ssh_snapshot_failed')
                output.seek(0)
                return parse_ssh_snapshot(output.read(SSH_OUTPUT_LIMIT + 1))
        except MediaError:
            raise
        except Exception:
            raise MediaError('ssh_snapshot_failed') from None


class MediaError(Exception):
    """Only fixed public error codes may cross the CLI boundary."""
    def __init__(self, code, native_errcode=None):
        super().__init__(code)
        self.code = code
        self.native_errcode = native_errcode
        self.phase = None
        self.password_change_acknowledged = False
        self.media_enable_attempted = False
        self.guarded_operation = False
        self.operation_journal_preserved = False


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
    require(type(password) is str and 8 <= len(password) <= MAX_NEW_PASSWORD_BYTES and
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


def verified_media_status(transport):
    # Queued asynchronous notifications may arrive before the status response.
    # Only known, well-formed partials permit another read-only query. Never
    # combine separate notifications into a successful complete status.
    for _ in range(3):
        response = transport.status()
        response_error(response)
        require(type(response) is dict and type(response.get('dps')) is dict,
                'invalid_status_response')
        dps = response['dps']
        for number in ('237', '239'):
            require(number not in dps or type(dps[number]) is bool, 'missing_media_status')
        if '238' in dps:
            require(password_result(response), 'invalid_password_response')
        if '237' in dps and '239' in dps:
            after = safe_status(response)
            require(after['dp237'] is True and after['dp239'] is True, 'media_verification_failed')
            return after
        require(bool(dps) and set(dps) <= {'237', '238', '239'}, 'invalid_status_response')
    raise MediaError('missing_media_status')


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
        return verified_media_status(transport)
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


def guarded_inputs(credentials, host, password, old_password, timeout, retries):
    validate_credentials(credentials)
    validate_target(host, timeout, retries)
    validate_password(password)
    require(re.fullmatch(r'[A-Za-z0-9]+', password) is not None, 'guarded_password_alnum_required')
    require(old_password is None or (type(old_password) is str and len(old_password) <= 63 and
            all(33 <= ord(c) <= 126 for c in old_password)), 'invalid_old_password')


def require_off(snapshot):
    require(not any(snapshot.flags.values()) and
            snapshot.metadata['rtsp_listening'] == snapshot.metadata['onvif_listening'] == '0',
            'native_services_must_be_off')


def guarded_old_password(snapshot, status, supplied):
    require(status['dp237'] is False, 'native_services_must_be_off')
    rtsp, onvif = snapshot.passwords['rtsp'], snapshot.passwords['onvif']
    require(hmac.compare_digest(rtsp, onvif), 'native_password_state_mismatch')
    if status['dp239']:
        require(supplied is not None and supplied != '', 'old_password_file_required')
        require(hmac.compare_digest(onvif, supplied), 'native_password_state_mismatch')
        return supplied
    require(onvif in ('', EMPTY_PASSWORD_WIRE_VALUE) and
            supplied in (None, '', EMPTY_PASSWORD_WIRE_VALUE), 'native_password_state_mismatch')
    return EMPTY_PASSWORD_WIRE_VALUE


def preflight_guarded(credentials, host, password, client_key, known_hosts, old_password=None,
                      timeout=3, retries=0, ssh_factory=None, transport_factory=None):
    transport = None
    try:
        guarded_inputs(credentials, host, password, old_password, timeout, retries)
        ssh = (ssh_factory or SSHProfile)(host, client_key, known_hosts, timeout)
        snapshot = ssh.snapshot()
        require_off(snapshot)
        transport = (transport_factory or TuyaTransport)(credentials, host, timeout, retries)
        status = safe_status(transport.status())
        guarded_old_password(snapshot, status, old_password)
        return {'ok': True, 'profile': PROFILE, 'guarded_preflight_passed': True,
                'live_identity_verified': True, 'both_native_flags_off': True,
                'native_listeners_absent': True, 'configuration_written': False}
    except MediaError as error:
        error.phase = 'ssh_preflight'
        error.guarded_operation = True
        raise
    except BaseException:
        error = MediaError('guarded_preflight_failed')
        error.phase = 'ssh_preflight'
        error.guarded_operation = True
        raise error from None
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def private_new(path, data):
    private_directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600, 'unsafe_operation_permissions')
        private_directory(path.parent)
    except BaseException:
        os.close(descriptor)
        try:
            path.unlink()
        except OSError:
            pass
        raise
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def private_directory(path):
    info = path.stat(follow_symlinks=False)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'unsafe_operation_permissions')


def private_json(path, value):
    private_new(path, json.dumps(value, sort_keys=True, indent=2).encode() + b'\n')


def guarded_failure(error):
    result = {'ok': False, 'error': error.code, 'phase': error.phase,
              'password_change_acknowledged': error.password_change_acknowledged,
              'media_enable_attempted': error.media_enable_attempted,
              'guarded_operation': True, 'operation_journal_preserved': error.operation_journal_preserved}
    if error.native_errcode is not None:
        result['native_errcode'] = error.native_errcode
    return result


def configure_guarded(credentials, host, password, client_key, known_hosts, operation_directory,
                      old_password=None, timeout=3, retries=0, ssh_factory=None, transport_factory=None):
    transport = None
    phase = 'ssh_preflight'
    acknowledged = attempted = journal = False
    directory = Path(operation_directory)
    created = False
    result = error = None
    try:
        guarded_inputs(credentials, host, password, old_password, timeout, retries)
        require(directory.is_absolute() and not any(path.is_symlink() for path in (directory, *directory.parents)),
                'unsafe_operation_directory')
        require(not directory.exists(), 'operation_directory_exists_do_not_replay')
        ssh = (ssh_factory or SSHProfile)(host, client_key, known_hosts, timeout)
        snapshot = ssh.snapshot()
        require_off(snapshot)
        transport = (transport_factory or TuyaTransport)(credentials, host, timeout, retries)
        initial_status = safe_status(transport.status())
        wire_old = guarded_old_password(snapshot, initial_status, old_password)
        phase = 'preservation'
        directory.mkdir(mode=0o700)
        private_directory(directory)
        created = True
        sync_directory(directory.parent)
        private_new(directory / 'param-before.conf', snapshot.param)
        metadata = {key: value for key, value in snapshot.metadata.items() if key != 'param_base64'}
        private_json(directory / 'snapshot-before.json', metadata)
        private_json(directory / 'recovery-plan.json', {
            'profile': PROFILE, 'original_configuration': 'param-before.conf',
            'automatic_rollback': False, 'raw_flash_write': False,
            'ambiguous_result': 'Read status only; retain this journal and do not replay writes.',
            'reachable_recovery': 'A separate reviewed both-native-off operation is required.',
            'offline_recovery': 'Use the exact-profile documented recover-native-off procedure after owner review.',
            'whole_configuration_restore': False,
        })
        private_json(directory / 'attempt-started.json', {
            'format': 'lscamoflash-yyos-guarded-native-operation-v1', 'profile': PROFILE,
            'host': host, 'created_unix_seconds': int(time.time()), 'app_sha256': APP_SHA256,
            'configuration_before_sha256': snapshot.sha256, 'new_password_bytes': len(password),
            'write_replay_allowed': False, 'original_preserved': True,
        })
        journal = True
        phase = 'ssh_recheck'
        fresh = ssh.snapshot()
        require(fresh.identity == snapshot.identity and fresh.sha256 == snapshot.sha256,
                'live_state_changed_before_write')
        require_off(fresh)
        current_status = safe_status(transport.status())
        require(current_status == initial_status, 'live_state_changed_before_write')
        guarded_old_password(fresh, current_status, old_password)
        phase = 'password_request'
        payload = json.dumps({'oldpwd': wire_old, 'newpwd': password}, separators=(',', ':'))
        require(len(payload) <= 255, 'invalid_password_request')
        response = transport.set_value(238, payload)
        phase = 'password_confirmation'
        accepted = password_result(response)
        for _ in range(2):
            if accepted:
                break
            accepted = password_result(transport.receive())
        require(accepted, 'password_confirmation_missing')
        acknowledged = True
        phase = 'password_readback'
        changed = ssh.snapshot()
        require(changed.identity == snapshot.identity, 'live_identity_changed')
        require_off(changed)
        require(all(hmac.compare_digest(value, password) for value in changed.passwords.values()),
                'native_password_readback_failed')
        private_json(directory / 'password-readback.json', {'configuration_sha256': changed.sha256,
                     'both_passwords_verified': True, 'password_bytes': len(password), 'both_flags_off': True})
        phase = 'media_enable'
        attempted = True
        response_error(transport.set_value(237, True))
        phase = 'enabled_readback'
        enabled = ssh.snapshot()
        require(enabled.identity == snapshot.identity, 'live_identity_changed')
        require(all(enabled.flags.values()) and
                all(hmac.compare_digest(value, password) for value in enabled.passwords.values()),
                'native_configuration_readback_failed')
        phase = 'final_status'
        status = verified_media_status(transport)
        result = {'ok': True, 'profile': PROFILE, 'guarded_operation': True,
                  'password_change_acknowledged': True, 'media_enable_attempted': True,
                  'configuration_readback_verified': True, 'operation_journal_preserved': True,
                  'write_replay_allowed': False, 'normal_boot_verified': False, 'status': status}
        private_json(directory / 'enabled-readback.json', {'configuration_sha256': enabled.sha256,
                     'both_passwords_verified': True, 'password_bytes': len(password), 'both_flags_on': True})
    except MediaError as caught:
        error = caught
    except BaseException:
        error = MediaError('guarded_configuration_failed')
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass
    if error is not None:
        error.phase, error.password_change_acknowledged, error.media_enable_attempted = phase, acknowledged, attempted
        error.guarded_operation, error.operation_journal_preserved = True, journal
        result = guarded_failure(error)
    if created:
        try:
            private_json(directory / 'attempt-result.json', result)
        except Exception:
            if error is None:
                error = MediaError('operation_record_failed')
                error.phase, error.password_change_acknowledged, error.media_enable_attempted = 'operation_record', acknowledged, attempted
                error.guarded_operation, error.operation_journal_preserved = True, journal
    if error is not None:
        raise error
    return result


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    credentials = subparsers.add_parser('credentials', help='offline verified-backup recovery; never prints keys')
    credentials.add_argument('--backup-run', type=Path, required=True)
    credentials.add_argument('--output', type=Path, required=True, help='new private0600 JSON; never overwritten')
    for command in ('status', 'configure', 'preflight-guarded', 'configure-guarded'):
        helps = {'status': 'read-only Tuya status', 'configure': 'blocked legacy write path',
                 'preflight-guarded': 'read-only fresh SSH/Tuya eligibility check',
                 'configure-guarded': 'one guarded attempt; requires both native services already off'}
        sub = subparsers.add_parser(command, help=helps[command])
        sub.add_argument('--credentials', type=Path, required=True)
        sub.add_argument('--host', required=True, help='explicit RFC1918 IPv4 address; no autodiscovery/cloud')
        sub.add_argument('--timeout', type=float, default=3, help='socket timeout1..10seconds')
        sub.add_argument('--retries', type=int, default=0, help='additional connection attempts0..2; writes never replayed')
        if command != 'status':
            sub.add_argument('--password-file', type=Path, required=True,
                             help='private new password; guarded commands require8..15ASCIIletters/digits and all3classes')
            sub.add_argument('--old-password-file', type=Path,
                             help='required when DP239 is true; omitted only for the firmware default-password state')
        if command in ('preflight-guarded', 'configure-guarded'):
            sub.add_argument('--ssh-key', type=Path, required=True, help='private owner OpenSSH key file')
            sub.add_argument('--ssh-known-hosts', type=Path, required=True, help='private exact Ed25519 host pin for TCP2222')
        if command == 'configure-guarded':
            sub.add_argument('--operation-directory', type=Path, required=True,
                             help='new absolute private backup/journal directory; an existing path is never replayed')
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
                if args.command == 'configure':
                    result = configure(identity, args.host, password, old_password, args.timeout, args.retries)
                elif args.command == 'preflight-guarded':
                    result = preflight_guarded(identity, args.host, password, args.ssh_key, args.ssh_known_hosts,
                                               old_password, args.timeout, args.retries)
                else:
                    result = configure_guarded(identity, args.host, password, args.ssh_key, args.ssh_known_hosts,
                                               args.operation_directory, old_password, args.timeout, args.retries)
    except MediaError as error:
        result = {'ok': False, 'error': error.code}
        if error.native_errcode is not None:
            result['native_errcode'] = error.native_errcode
        if error.phase in CONFIGURE_PHASES:
            result.update(phase=error.phase,
                          password_change_acknowledged=error.password_change_acknowledged,
                          media_enable_attempted=error.media_enable_attempted)
        if error.guarded_operation:
            result.update(guarded_operation=True, operation_journal_preserved=error.operation_journal_preserved)
        print(json.dumps(result, sort_keys=True))
        return 1
    except Exception:
        print(json.dumps({'ok': False, 'error': 'operation_failed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
