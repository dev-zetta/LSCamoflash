#!/usr/bin/env python3
"""Assemble a private, opt-in YYOS SSH kit offline; never install or contact a camera."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'SOURCE/src/yyos-ssh'
RUNTIME_FILES = ('common.sh', 'start.sh', 'stop.sh', 'README.md')
PUBLIC_FILES = (*RUNTIME_FILES, 'bin/busybox', 'bin/dropbear', 'LICENSE.MIT',
                'COPYING.BusyBox', 'COPYING.Dropbear', 'manifest.json')
PRIVATE_FILES = ('authorized_keys', 'dropbear_ed25519_host_key', 'ssh.enabled')
FORMAT = 'lscamoflash-yyos-ssh-kit-v1'
VERSION = '2026.94'
SOURCE_SHA = 'e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81'
CLOCK_SOURCE_SHA = 'f3f3c87472abbaf78756f8245416b980b63e2e733b2c95072c5a71a2a5514655'
STOCK_SHA = 'd76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7'
APPLETS = {'sh', 'id', 'sha256sum', 'awk', 'stat', 'find', 'readlink', 'netstat',
           'ip', 'tr', 'mkdir', 'rmdir', 'rm', 'kill', 'sleep', 'cat', 'pidof',
           'timeout', 'cp', 'chmod', 'chown', 'sync', 'dd', 'wc', 'date', 'mv',
           'sed', 'base64', 'od'}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


BACKUP = module('yyos_ssh_backup_helpers', REPO / 'tools/firmware-backup/build-yyos-kit.py')
NOR = BACKUP.NOR


def regular(path, limit):
    path = Path(os.path.abspath(path))
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('Input files and parent directories must not be symlinks')
    if not stat.S_ISREG(path.lstat().st_mode) or not 0 < path.stat().st_size <= limit:
        raise ValueError('Input must be a bounded, nonempty regular file: ' + path.name)
    return path


def public_key(path):
    data = regular(path, 1024).read_bytes()
    try:
        text = data.decode('ascii')
    except UnicodeError:
        raise ValueError('Client key must be a single bare ASCII Ed25519 public key') from None
    match = re.fullmatch(r'ssh-ed25519 ([A-Za-z0-9+/]+={0,2})(?:\n)?', text)
    if not match:
        raise ValueError('Client key must be one bare ssh-ed25519 key without options or a comment')
    try:
        blob = base64.b64decode(match[1], validate=True)
    except ValueError:
        raise ValueError('Invalid Ed25519 public-key encoding') from None
    if (len(blob) != 51 or blob[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'
            or blob[19:] == bytes(32) or base64.b64encode(blob).decode() != match[1]):
        raise ValueError('Invalid Ed25519 public-key wire format')
    return ('ssh-ed25519 ' + match[1] + '\n').encode()


def host_key(path):
    data = regular(path, 83).read_bytes()
    # Dropbear's native Ed25519 key consists of the algorithm SSH string and
    # one 64-byte SSH string containing the 32-byte seed and 32-byte public key.
    if (len(data) != 83 or data[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x40'
            or data[19:51] == bytes(32) or data[51:] == bytes(32)):
        raise ValueError('Host key must be an 83-byte native Dropbear Ed25519 private key')
    return data


def source_license(path):
    path = regular(path, 32 * 1024 * 1024)
    if NOR.digest(path) != SOURCE_SHA:
        raise ValueError('Dropbear source archive does not match the pinned 2026.94 source')
    sections = []
    with tarfile.open(path, 'r:bz2') as archive:
        for name in ('LICENSE', 'libtomcrypt/LICENSE', 'libtommath/LICENSE'):
            member = archive.getmember('dropbear-' + VERSION + '/' + name)
            if not member.isfile() or not 0 < member.size <= 1024 * 1024:
                raise ValueError('Invalid Dropbear component license')
            sections.append(('===== Dropbear ' + VERSION + ': ' + name + ' =====\n').encode()
                            + archive.extractfile(member).read() + b'\n')
        for name in ('src/mlkem768.c', 'src/libcrux_mlkem768_sha3.h', 'src/sntrup761.c',
                     'src/ed25519.c', 'src/sshpty.c', 'src/atomicio.c'):
            member = archive.getmember('dropbear-' + VERSION + '/' + name)
            if not member.isfile() or not 0 < member.size <= 8 * 1024 * 1024:
                raise ValueError('Invalid Dropbear component notice source')
            prefix = archive.extractfile(member).read(16 * 1024)
            notices = [part for part in re.findall(rb'/\*.*?\*/', prefix, re.S)
                       if re.search(rb'copyright|public domain|SPDX-License|Permission is hereby', part, re.I)]
            if not notices:
                raise ValueError('Missing Dropbear component notice')
            sections.append(('===== Dropbear ' + VERSION + ': ' + name + ' notices =====\n').encode()
                            + b'\n'.join(notices) + b'\n')
    sections.append(b'\nThe static executable also includes its toolchain C runtime. Retain the matching toolchain sources and notices described in SOURCE/3RD_PARTY_LICENSES.md; this entire kit is not solely MIT-licensed.\n')
    return b'\n'.join(sections)


def provenance(path, binary):
    data = json.loads(regular(path, 128 * 1024).read_text())
    if (not isinstance(data, dict) or data.get('version') != VERSION
            or data.get('binary_sha256') != NOR.digest(binary)
            or data.get('source_archive_sha256') != SOURCE_SHA):
        raise ValueError('Dropbear provenance must bind this binary and the pinned source archive')
    # Keep source/build provenance only: never copy arbitrary host paths, test
    # output, environment or credential-related fields into the public manifest.
    keep = ('version', 'binary_sha256', 'source_archive_sha256', 'source_url',
            'configure_flags', 'make_args', 'cflags', 'ldflags', 'localoptions',
            'localoptions_sha256', 'compiler_version', 'compiler_sha256', 'static_libc_version', 'libc', 'toolchain',
            'toolchain_source', 'patches', 'build_script_sha256', 'yyos_clock_compat', 'yyos_clock_patch')
    result = {key: data[key] for key in keep if key in data}
    if not result.get('localoptions') or not result.get('configure_flags'):
        raise ValueError('Dropbear provenance must include localoptions and configure_flags')
    text = json.dumps(result)
    if len(text) > 64 * 1024 or '/home/' in text or '/mnt/' in text.replace('/mnt/sdcard', '') or '.local/' in text:
        raise ValueError('Dropbear build provenance must use portable paths without private host locations')
    options_text = result['localoptions']
    if (not isinstance(options_text, str)
            or result.get('localoptions_sha256') != hashlib.sha256(options_text.encode()).hexdigest()):
        raise ValueError('Dropbear localoptions content and hash must match')
    options = dict(re.findall(r'^#define ([A-Z0-9_]+) ([0-9]+)$', options_text, re.M))
    required = {'DROPBEAR_SVR_PASSWORD_AUTH': 0, 'DROPBEAR_SVR_PAM_AUTH': 0,
                'DROPBEAR_SVR_PUBKEY_AUTH': 1, 'DROPBEAR_ED25519': 1,
                'DROPBEAR_SVR_LOCALTCPFWD': 0, 'DROPBEAR_SVR_REMOTETCPFWD': 0,
                'DROPBEAR_SVR_LOCALSTREAMFWD': 0, 'DROPBEAR_SVR_REMOTESTREAMFWD': 0,
                'DROPBEAR_X11FWD': 0, 'DROPBEAR_SVR_AGENTFWD': 0, 'DROPBEAR_SFTPSERVER': 0}
    if any(options.get(key) != str(value) for key, value in required.items()):
        raise ValueError('Dropbear build must have public-key authentication only and forwarding/SFTP disabled')
    if not {'--enable-static', '--disable-syslog', '--disable-shadow'} <= set(result['configure_flags']):
        raise ValueError('Dropbear configure flags must preserve the static, stderr-only build contract')
    return result


def clock_proof(report, archive_path, object_path, source_path=None):
    """Check the audited legacy-clock object and reproduce the bounded text patch."""
    source_path = source_path or REPO / 'tools/yyos/yyos-clock-compat.c'
    source = regular(source_path, 64 * 1024)
    obj = regular(object_path, 128 * 1024)
    proof = report.get('yyos_clock_compat', {})
    data = obj.read_bytes()
    if (not isinstance(proof, dict) or proof.get('source_sha256') != CLOCK_SOURCE_SHA
            or NOR.digest(source) != CLOCK_SOURCE_SHA or proof.get('object_sha256') != NOR.digest(obj)
            or proof.get('timeouts_disabled') is not False
            or proof.get('kernel_time_abi') != 'ARM EABI signed time32 converted to libc time64'
            or proof.get('clock_source') != 'requested POSIX clock, including monotonic'
            or '-DLSCAMOFLASH_YYOS_CLOCK_COMPAT=1' not in report.get('cflags', '').split()
            or len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01'
            or struct.unpack_from('<HH', data, 16) != (1, 40)
            or struct.unpack_from('<I', data, 36)[0] & 0xFF000400 != 0x05000000):
        raise ValueError('Public musl SSH requires the audited ARM legacy-clock object and enabled fail-closed policy')
    with tarfile.open(regular(archive_path, 32 * 1024 * 1024), 'r:bz2') as archive:
        member = archive.getmember('dropbear-2026.94/src/dbutil.c')
        if not member.isfile() or not 0 < member.size <= 128 * 1024:
            raise ValueError('Invalid upstream clock-wrapper source')
        original = archive.extractfile(member).read()
    builder = module('yyos_clock_patch_validator', REPO / 'tools/yyos/build-dropbear.py')
    with tempfile.TemporaryDirectory(prefix='yyos-clock-proof-') as temporary:
        root = Path(temporary)
        (root / 'src').mkdir()
        (root / 'src/dbutil.c').write_bytes(original)
        expected = builder.patch_clock_fallback(root)
    if report.get('yyos_clock_patch') != expected:
        raise ValueError('Dropbear monotonic-clock patch provenance does not match the pinned upstream text')
    return proof


def boot_wrapper(http_hash):
    return f'''#!/bin/sh
# Normal YYOS background hook only: never launch stock or change debug mode.
set -u
[ "$#" -eq 1 ] && [ "$1" = /mnt/sdcard ] || exit 2
BB=/mnt/sdcard/busybox
HTTP=/mnt/sdcard/yyos-http-boot.sh
SSH=/mnt/sdcard/LSCamoflash-yyos-ssh
for directory in /mnt /mnt/sdcard; do
    [ -d "$directory" ] && [ ! -L "$directory" ] || exit 2
done
for file in "$BB" "$HTTP"; do
    [ -f "$file" ] && [ ! -L "$file" ] || exit 2
done
[ "$("$BB" timeout -k 1 5 "$BB" sha256sum "$HTTP" | "$BB" awk '{{print $1}}')" = {http_hash} ] || exit 1
# Execute the unchanged original HTTP entry in its own shell; its exec must
# not replace this wrapper. A failed HTTP attempt never starts stock again.
"$BB" timeout -k 2 35 "$BB" sh "$HTTP" /mnt/sdcard
HTTP_STATUS=$?
# The SSH runtime repeats exact profile, mount, payload, key and ownership
# checks. Detached null stdio keeps the native launcher's capture pipe private.
(
    for directory in "$SSH" "$SSH/bin"; do
        [ -d "$directory" ] && [ ! -L "$directory" ] || exit 2
    done
    for file in "$SSH/start.sh" "$SSH/SHA256SUMS"; do
        [ -f "$file" ] && [ ! -L "$file" ] || exit 2
    done
    (cd "$SSH" && "$BB" timeout -k 2 12 "$BB" sha256sum -c SHA256SUMS >/dev/null) || exit 1
    exec "$BB" timeout -k 2 150 "$BB" sh "$SSH/start.sh"
) </dev/null >/dev/null 2>&1 &
exit "$HTTP_STATUS"
'''.encode()


def build(args):
    output = args.output.absolute()
    BACKUP.validate_output(output)
    binary = regular(args.dropbear, 8 * 1024 * 1024)
    busybox = regular(args.busybox, 8 * 1024 * 1024)
    credential_free = getattr(args, 'credential_free', False)
    if credential_free:
        if args.client_public_key is not None or args.host_key is not None:
            raise ValueError('A credential-free build must not receive site keys')
        keys = None
    else:
        if args.client_public_key is None or args.host_key is None:
            raise ValueError('Provide both owner public key and host key, or explicitly use --credential-free')
        keys = (public_key(args.client_public_key), host_key(args.host_key))
    copying_dropbear = source_license(args.dropbear_source)
    build_info = provenance(args.dropbear_provenance, binary)
    libc = build_info.get('libc')
    if libc is not None:
        if not getattr(args, 'musl_build', None) or libc.get('name') != 'musl' or libc.get('version') != '1.2.6':
            raise ValueError('The musl-linked binary requires its matching --musl-build directory')
        musl = args.musl_build.absolute()
        for name, expected in {'COPYING.musl': libc.get('license_sha256'),
                               **libc.get('gcc_runtime_notices', {})}.items():
            if name not in {'COPYING.musl', 'GCC-COPYING3', 'GCC-COPYING.RUNTIME'}:
                raise ValueError('Unexpected static runtime license name')
            path = regular(musl / name, 256 * 1024)
            if NOR.digest(path) != expected:
                raise ValueError('Static runtime license differs from Dropbear provenance')
            copying_dropbear += ('\n===== Static runtime ' + name + ' =====\n').encode() + path.read_bytes()
        if set(libc.get('gcc_runtime_notices', {})) != {'GCC-COPYING3', 'GCC-COPYING.RUNTIME'}:
            raise ValueError('Musl builds must retain both GCC runtime notices')
        for name, key in (('musl-1.2.6.tar.gz', 'source_archive_sha256'), ('provenance.json', 'provenance_sha256')):
            if NOR.digest(regular(musl / name, 32 * 1024 * 1024)) != libc.get(key):
                raise ValueError('Musl source/provenance identity mismatch')
        clock_proof(build_info, args.dropbear_source, args.dropbear_provenance.parent / 'yyos-clock-compat.o')
    readelf = NOR.executable(args.readelf)
    reports = {name: NOR.validate_arm_elf(path, readelf) for name, path in
               (('dropbear', binary), ('busybox', busybox))}
    copying_busybox, busybox_inputs = BACKUP.busybox_sources()
    for name in RUNTIME_FILES:
        regular(SOURCE / name, 256 * 1024)
    http = regular(REPO / 'tools/yyos/boot.sh', 64 * 1024)
    wrapper = boot_wrapper(NOR.digest(http))
    qemu = NOR.executable(args.qemu) if args.qemu else None
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.yyos-ssh-build-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'kit'
        stage.mkdir(mode=0o700)
        runtime = stage / 'card/LSCamoflash-yyos-ssh'
        (runtime / 'bin').mkdir(parents=True, mode=0o700)
        for name in RUNTIME_FILES:
            shutil.copyfile(SOURCE / name, runtime / name)
        for name, path in (('busybox', busybox), ('dropbear', binary)):
            shutil.copyfile(path, runtime / 'bin' / name)
            (runtime / 'bin' / name).chmod(0o755)
        for name in ('start.sh', 'stop.sh'):
            (runtime / name).chmod(0o755)
        shutil.copyfile(regular(REPO / 'LICENSE', 128 * 1024), runtime / 'LICENSE.MIT')
        (runtime / 'COPYING.BusyBox').write_bytes(copying_busybox)
        (runtime / 'COPYING.Dropbear').write_bytes(copying_dropbear)
        if keys:
            for name, data in zip(PRIVATE_FILES, (*keys, b'enabled\n')):
                (runtime / name).write_bytes(data)
                (runtime / name).chmod(0o600)
        (stage / 'boot').mkdir()
        shutil.copyfile(http, stage / 'boot/normal-http-boot.sh')
        (stage / 'boot/boot.sh').write_bytes(wrapper)
        if keys:
            host_public = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + keys[1][51:]
            (stage / 'host-key.pub').write_bytes(b'ssh-ed25519 ' + base64.b64encode(host_public) + b'\n')
            (stage / 'host-key-fingerprint.txt').write_text(
                'SHA256:' + base64.b64encode(hashlib.sha256(host_public).digest()).decode().rstrip('=') + '\n')
        if qemu:
            applets = subprocess.run([str(qemu), '-cpu', 'arm926', str(runtime / 'bin/busybox'), '--list'],
                                     capture_output=True, text=True, check=True, timeout=15).stdout.splitlines()
            if APPLETS - set(applets):
                raise ValueError('BusyBox lacks required SSH-runtime applets')
            for path in (stage / 'boot/boot.sh', *(runtime / name for name in RUNTIME_FILES if name.endswith('.sh'))):
                subprocess.run([str(qemu), '-cpu', 'arm926', str(runtime / 'bin/busybox'), 'sh', '-n', str(path)],
                               capture_output=True, check=True, timeout=5)
            probe = subprocess.run([str(qemu), '-cpu', 'arm926', str(runtime / 'bin/dropbear'), '-h'],
                                   capture_output=True, timeout=5)
            if b'Dropbear server v2026.94' not in probe.stderr:
                raise ValueError('Dropbear ARM926 server smoke failed')
            if keys:
                keytool = Path(temporary) / 'dropbearkey'
                shutil.copyfile(binary, keytool)
                keytool.chmod(0o700)
                probe = subprocess.run([str(qemu), '-cpu', 'arm926', str(keytool), '-y', '-f', str(runtime / PRIVATE_FILES[1])],
                                       capture_output=True, check=True, timeout=5)
                expected = base64.b64encode(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + keys[1][51:])
                if [b'ssh-ed25519', expected] not in [line.split()[:2] for line in probe.stdout.splitlines()]:
                    raise ValueError('Dropbear keytool did not load the supplied Ed25519 host key')
        names = tuple(name for name in PUBLIC_FILES if name != 'manifest.json')
        manifest = {'format': FORMAT, 'target': '3225722 / SZ F26312 / V14.1.5 / AK3918AV130',
                    'stock_sha256': STOCK_SHA, 'port': 2222, 'password_authentication': False,
                    'forwarding': False, 'sftp': False, 'arm926_smoke': bool(qemu),
                    'credentials_provisioned': keys is not None,
                    'dropbear': reports['dropbear'], 'dropbear_build': build_info,
                    'busybox': reports['busybox'], 'busybox_repository_sources': busybox_inputs,
                    'credentials_excluded_from_checksums': list(PRIVATE_FILES),
                    'files': {name: NOR.digest(runtime / name) for name in sorted(names)}}
        (runtime / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        NOR.write_sums(runtime, PUBLIC_FILES)
        (stage / 'README.md').write_text(
            '# Optional YYOS SSH kit\n\n'
            'Experimental exact-profile root administration using Ed25519 keys on TCP2222. '
            + ('This output contains a private host key and owner public key: never publish or commit it. ' if keys else
               'This credential-free output contains no owner keys or enable marker and cannot start SSH until privately provisioned. ')
            +
            'Only card/LSCamoflash-yyos-ssh is the nested SSH payload. '
            'boot/normal-http-boot.sh is the byte-identical existing HTTP hook, staged as SD-root yyos-http-boot.sh; '
            'boot/boot.sh is the proposed SD-root dump.sh composition. These host files are not an installation command. '
            'Archive previous root hook files and verify the exact card/device/old payload before staging; '
            'keep the existing native telnetd and root BusyBox unchanged, preserve HTTP/auth/config/recordings, '
            'and stage the normal yy_telnet_start marker last. Never add or change yy_debug.ini.\n\n'
            'The public runtime checksums exclude authorized_keys, dropbear_ed25519_host_key and ssh.enabled. '
            'Start copies validated keys into protected RAM and retains stock processes/settings. '
            'No password or default credentials, public listener, forwarding, SCP or SFTP server is provided. '
            'Camera SSH, host fingerprint, wrong-key refusal, memory and normal cold-boot acceptance remain pending. '
            'See docs/yyos-ssh.md in the matching public source tree.\n')
        package = {'format': FORMAT + '-host-package', 'builder_sha256': NOR.digest(Path(__file__)),
                   'http_boot_source_sha256': NOR.digest(http), 'ssh_boot_wrapper_sha256': hashlib.sha256(wrapper).hexdigest(),
                   'private_output': keys is not None, 'private_inputs_excluded_from_public_checksums': list(PRIVATE_FILES)}
        (stage / 'manifest.json').write_text(json.dumps(package, indent=2, sort_keys=True) + '\n')
        public = ('README.md', 'manifest.json', *(('host-key.pub', 'host-key-fingerprint.txt') if keys else ()), 'boot/boot.sh', 'boot/normal-http-boot.sh',
                  *('card/LSCamoflash-yyos-ssh/' + name for name in (*PUBLIC_FILES, 'SHA256SUMS')))
        NOR.write_sums(stage, public)
        BACKUP.validate_output(output)
        if output.exists():
            output.rmdir()
        stage.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='absent or empty dedicated private host output')
    parser.add_argument('--dropbear', type=Path, required=True, help='static ARMv5 Dropbear2026.94 multicall binary')
    parser.add_argument('--dropbear-source', type=Path, required=True, help='pinned hydrated Dropbear2026.94 source tar.bz2')
    parser.add_argument('--dropbear-provenance', type=Path, required=True, help='portable JSON binding build options/source and binary hashes')
    parser.add_argument('--musl-build', type=Path, help='matching public musl build source, provenance and runtime notices')
    parser.add_argument('--credential-free', action='store_true', help='public disabled kit without keys or an enable marker')
    parser.add_argument('--client-public-key', type=Path, help='one bare Ed25519 public key; no options or comment')
    parser.add_argument('--host-key', type=Path, help='private native Dropbear Ed25519 host key; never an OpenSSH client private key')
    parser.add_argument('--busybox', type=Path, default=REPO / 'SOURCE/backup-kit/card/busybox')
    parser.add_argument('--readelf', default=os.environ.get('READELF', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi-readelf')))
    parser.add_argument('--qemu', default=os.environ.get('QEMU_ARM'), help='optional qemu-arm for ARM926 syntax/server/keytool checks')
    args = parser.parse_args()
    try:
        output = build(args)
    except (OSError, ValueError, KeyError, UnicodeError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, 'YYOS SSH kit build failed: ' + str(error) + '\n')
    print('Built private opt-in YYOS SSH kit: ' + str(output))
    print('No camera, card, stock process, debug mode or persistent setting was changed.')


if __name__ == '__main__':
    main()
