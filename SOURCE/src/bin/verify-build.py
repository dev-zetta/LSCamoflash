#!/usr/bin/env python3
"""Check default uClibc packages and execute their ARM programs under QEMU.

This verifies packaging and basic userspace behavior; it does not access camera
hardware or establish physical installation, streaming, or motor acceptance.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile


RUNTIME_CHECKS = [
    ('bin/busybox', ['echo', 'arm-runtime-ok'], {0}),
    ('bin/tcpdump', ['--version'], {0}),
    ('bin/openssl', ['version'], {0}),
    ('bin/strace', ['-V'], {0}),
    ('bin/sqlite3', ['-version'], {0}),
    ('bin/sqlcipher', ['-version'], {0}),
    ('bin/msmtp', ['--version'], {0}),
    ('bin/curl', ['--version'], {0}),
    ('bin/upnpc', ['-h'], {0}),
    # These tools deliberately return nonzero after printing usage.
    ('sbin/mosquitto', ['-h'], {3}),
    ('bin/mosquitto_pub', ['--help'], {1}),
    ('bin/mosquitto_sub', ['--help'], {1}),
    ('bin/mosquitto_rr', ['--help'], {1}),
    ('bin/mosquitto_passwd', ['-h'], {1}),
    ('sbin/onvif_srvd', ['--help'], {0}),
    ('bin/ffmpeg', ['-version'], {0}),
    ('bin/ffprobe', ['-version'], {0}),
    ('bin/php', ['-v'], {0}),
    ('bin/php-cgi', ['-v'], {0}),
    ('bin/php', ['-r', 'echo json_encode(["sum" => 2 + 3, "sha256" => hash("sha256", "camoflash")]), "\\n";'], {0}),
    ('bin/sqlite3', [':memory:', 'select 2+3;'], {0}),
    ('bin/sqlcipher', [':memory:', 'PRAGMA cipher_version;'], {0}),
    ('bin/motor', [], {1}),
]
REQUIRED_ARCHIVE_FILES = {
    'mmcblk0p1/hostapd',
    'mmcblk0p1/bootstrap.sh',
    'mmcblk0p1/busybox',
    'mmcblk0p2/HACK/bin/busybox',
    'mmcblk0p2/HACK/bin/php',
    'mmcblk0p2/HACK/sbin/onvif_srvd',
    'mmcblk0p2/HACK/sbin/anyka_ipc_wrapper.sh',
}


def scan_elfs(build):
    """Reject accidentally packaged native host programs or libraries."""
    elfs = []
    for path in build.rglob('*'):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            header = stream.read(20)
        if not header.startswith(b'\x7fELF'):
            continue
        if len(header) != 20 or header[5] not in (1, 2):
            raise ValueError(f'Invalid ELF header: {path}')
        machine = struct.unpack('<H' if header[5] == 1 else '>H', header[18:20])[0]
        if header[4] != 1 or machine != 40:
            raise ValueError(f'Expected ELF32 ARM, found class={header[4]} machine={machine}: {path}')
        elfs.append(str(path.relative_to(build)))
    if not elfs:
        raise ValueError(f'No ELF programs found in {build}')
    return elfs


def run_runtime_checks(hack, qemu):
    results = []
    for relative, arguments, allowed in RUNTIME_CHECKS:
        path = hack / relative
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f'Missing packaged program: {path}')
        command = [qemu, '-L', str(hack), '-E', f'LD_LIBRARY_PATH={hack / "lib"}',
                   str(path), *arguments]
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=40)
        record = dict(executable=relative, arguments=arguments,
                      exit_code=result.returncode, output=result.stdout)
        results.append(record)
        if result.returncode not in allowed:
            raise RuntimeError(f'Unexpected runtime result: {record}')
        if 'error while loading shared libraries' in result.stdout or "can't load library" in result.stdout:
            raise RuntimeError(f'Missing packaged runtime library: {record}')
        if relative == 'bin/busybox' and result.stdout.strip() != 'arm-runtime-ok':
            raise RuntimeError(f'BusyBox did not execute the requested command: {record}')
        if relative == 'bin/php' and arguments[0] == '-r':
            expected = {'sum': 5, 'sha256': hashlib.sha256(b'camoflash').hexdigest()}
            if json.loads(result.stdout) != expected:
                raise RuntimeError(f'PHP JSON/hash evaluation failed: {record}')
        if relative == 'bin/sqlite3' and arguments[0] == ':memory:' and result.stdout.strip() != '5':
            raise RuntimeError(f'SQLite query failed: {record}')
        if relative == 'bin/sqlcipher' and arguments[0] == ':memory:' and '4.5.5' not in result.stdout:
            raise RuntimeError(f'SQLCipher extension was not enabled: {record}')
    return results


def check_bootstrap(build, qemu):
    """The early hook must run on ARM926 without an SD library overlay."""
    for name in ('hostapd', 'busybox'):
        path = build / 'mmcblk0p1' / name
        data = path.read_bytes()
        if len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01':
            raise ValueError(f'Native bootstrap is not an ELF32 LE executable: {name}')
        fields = struct.unpack_from('<HHIIIIIHHHHHH', data, 16)
        kind, machine, _, _, phoff, _, flags, _, phsize, phcount, _, _, _ = fields
        if kind != 2 or machine != 40 or flags & 0x400 or flags & 0xff000000 != 0x05000000:
            raise ValueError(f'Native bootstrap is not ARM EABI5 soft-float: {name}')
        if not phcount or phsize < 32 or phoff + phsize * phcount > len(data):
            raise ValueError(f'Invalid bootstrap program headers: {name}')
        for number in range(phcount):
            if struct.unpack_from('<I', data, phoff + number * phsize)[0] in (2, 3):
                raise ValueError(f'Native bootstrap requires dynamic libraries: {name}')
    # Oversized arguments force a rejection before checking or using any mount.
    native = subprocess.run([qemu, '-cpu', 'arm926', str(build / 'mmcblk0p1/hostapd'), *(['probe'] * 129)],
                            capture_output=True, text=True, timeout=10)
    busybox = subprocess.run([qemu, '-cpu', 'arm926', str(build / 'mmcblk0p1/busybox'), 'echo', 'bootstrap-arm926-ok'],
                             capture_output=True, text=True, timeout=10)
    if native.returncode != 2 or busybox.returncode != 0 or busybox.stdout.strip() != 'bootstrap-arm926-ok':
        raise RuntimeError('Packaged native bootstrap did not execute safely on ARM926')
    return {'static_arm_eabi5': True, 'arm926_checks': 2, 'native_rejection_exit': native.returncode}


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_sources(source, build):
    """Ensure incremental builds include the latest installer and runtime files."""
    template = source / 'src/sdcard'
    generated_version = Path('mmcblk0p2/HACK/etc/version.txt')
    checked = 0
    for original in template.rglob('*'):
        if not original.is_file():
            continue
        relative = original.relative_to(template)
        if relative == generated_version:
            continue
        copied = build / relative
        if not copied.is_file() or file_digest(original) != file_digest(copied):
            raise ValueError(f'Built file does not match current source: {relative}')
        checked += 1
    if not checked:
        raise ValueError(f'No source templates found in {template}')
    if file_digest(source / 'version.txt') != file_digest(build / generated_version):
        raise ValueError('Built version does not match SOURCE/version.txt')
    return checked


def check_archive(path, update, build):
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        names = {entry.name.removeprefix('./') for entry in members}
        missing = REQUIRED_ARCHIVE_FILES - names
        if not update:
            missing |= {'install.sh', 'install.ps1', 'LICENSE.MIT', 'LICENSE.md'} - names
        if missing:
            raise ValueError(f'{path.name} is missing {sorted(missing)}')
        if update and any(name == 'mmcblk0p2/HACK/etc' or name.startswith('mmcblk0p2/HACK/etc/') for name in names):
            raise ValueError(f'{path.name} would overwrite camera configuration')
        if update and 'mmcblk0p2/HACK/var/spool/cron/crontabs/root' in names:
            raise ValueError(f'{path.name} would overwrite the local crontab')
        checked = 0
        for member in members:
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError(f'Unsafe archive entry: {member.name}')
            if not member.isfile():
                continue
            built = build / relative
            if not built.is_file() or built.stat().st_size != member.size:
                raise ValueError(f'Archive file differs from build: {member.name}')
            with archive.extractfile(member) as stream:
                archived_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if archived_digest != file_digest(built):
                raise ValueError(f'Archive file hash differs from build: {member.name}')
            checked += 1
        count = len(names)
    return dict(name=path.name, size=path.stat().st_size, sha256=file_digest(path),
                entries=count, regular_files_verified=checked)


def main():
    source = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=source / 'build')
    parser.add_argument('--archive-dir', type=Path, default=source)
    parser.add_argument('--qemu', default=shutil.which('qemu-arm') or 'qemu-arm')
    parser.add_argument('--output', type=Path, help='Save complete JSON results including runtime output')
    args = parser.parse_args()
    build = args.build_dir.resolve()
    version = (source / 'version.txt').read_text().strip()
    source_files = check_sources(source, build)
    elfs = scan_elfs(build)
    runtime = run_runtime_checks(build / 'mmcblk0p2/HACK', args.qemu)
    bootstrap = check_bootstrap(build, args.qemu)
    archives = [
        check_archive(args.archive_dir / f'LSCamoflash-{version}-uclibc.tar.gz', False, build),
        check_archive(args.archive_dir / f'update-{version}-uclibc.tgz', True, build),
    ]
    summary = dict(source_files_verified=source_files, version_verified=True,
                   elf_count=len(elfs), runtime_checks=len(runtime), bootstrap=bootstrap, archives=archives)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(summary, elfs=elfs, runtime=runtime), indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
