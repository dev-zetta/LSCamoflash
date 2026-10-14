#!/usr/bin/env python3
"""Build a separate manual Fullhan dashboard; never install or contact a device."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'SOURCE/src/fullhan'
FILES = ('start.sh', 'stop.sh', 'common.sh', 'README.md', 'www/index.html',
         'www/dashboard.js', 'www/cgi-bin/status.cgi')
FORMAT = 'lscamoflash-fullhan-management-v1'
APPLETS = {'sh', 'httpd', 'id', 'sha256sum', 'awk', 'stat', 'find', 'sed', 'readlink',
           'netstat', 'ip', 'tr', 'mkdir', 'rmdir', 'rm', 'kill', 'sleep'}
spec = importlib.util.spec_from_file_location('nor_kit_builder', REPO / 'tools/firmware-backup/build-kit.py')
NOR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NOR)


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular input file: ' + path.name)
    return path


def validate_output(output):
    if output.name != 'LSCamoflash-fullhan':
        raise ValueError('Output folder must be named LSCamoflash-fullhan')
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError('Output cannot use symlinks')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be absent or empty; existing files and credentials are never replaced')


def password_config(password_file, username):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', username):
        raise ValueError('Invalid management username')
    regular(password_file)
    data = password_file.read_bytes()
    if len(data) > 4096:
        raise ValueError('Password file is oversized')
    password = data.removesuffix(b'\n').removesuffix(b'\r')
    if not password or any(value < 32 or value == 127 for value in password):
        raise ValueError('Password file must contain one nonempty line without control characters')
    openssl = shutil.which('openssl')
    if not openssl:
        raise ValueError('Host OpenSSL is required for --password-file')
    # The password is stdin data, never a command argument or diagnostic output.
    hashed = subprocess.run([openssl, 'passwd', '-1', '-stdin'], input=password + b'\n',
                            capture_output=True, timeout=10)
    if hashed.returncode:
        raise ValueError('Host password hashing failed')
    value = hashed.stdout.decode('ascii').strip()
    if not re.fullmatch(r'\$1\$[A-Za-z0-9./]{1,8}\$[A-Za-z0-9./]{22}', value):
        raise ValueError('Unexpected host password hash format')
    return ('I:index.html\n/:' + username + ':' + value + '\n').encode()


def busybox_license(repo):
    recipe = (repo / 'SOURCE/Makefile').read_text()
    match = re.search(r'^BUSYBOX\s*:?=\s*(busybox-[A-Za-z0-9._+-]+)\s*$', recipe, re.M)
    if not match:
        raise ValueError('Missing declared BusyBox version')
    name = match[1]
    archive_path = regular(repo / 'SOURCE/download' / (name + '.tar.bz2'))
    with tarfile.open(archive_path, 'r:bz2') as archive:
        member = archive.getmember(name + '/LICENSE')
        if not member.isfile() or member.size > 1024 * 1024:
            raise ValueError('Invalid BusyBox license member')
        return archive.extractfile(member).read()


def build(args, repo=REPO):
    output = args.output.absolute()
    validate_output(output)
    busybox = regular(args.busybox.absolute())
    readelf = NOR.executable(args.readelf)
    elf = NOR.validate_arm_elf(busybox, readelf)
    if args.qemu:
        qemu = NOR.executable(args.qemu)
        applets = subprocess.run([str(qemu), '-cpu', 'arm1176', str(busybox), '--list'],
                                 check=True, capture_output=True, text=True, timeout=15).stdout.splitlines()
        if APPLETS - set(applets):
            raise ValueError('BusyBox lacks required pilot applets')
        smoke = subprocess.run([str(qemu), '-cpu', 'arm1176', str(busybox), 'echo', 'fullhan-static-arm1176-ok'],
                               check=True, capture_output=True, text=True, timeout=5)
        if smoke.stdout.strip() != 'fullhan-static-arm1176-ok':
            raise ValueError('BusyBox ARM1176 smoke failed')
        auth_probe = subprocess.run([str(qemu), '-cpu', 'arm1176', str(busybox), 'httpd', '-m', ''],
                                    capture_output=True, text=True, timeout=5)
        if auth_probe.returncode or not re.fullmatch(r'\$1\$[A-Za-z0-9./]{1,8}\$[A-Za-z0-9./]{22}', auth_probe.stdout.strip()):
            raise ValueError('BusyBox must provide HTTP Basic authentication with MD5-crypt support')
    auth = password_config(args.password_file, args.username) if args.password_file else None
    copying = busybox_license(repo)
    source = repo / 'SOURCE/src/fullhan'
    for name in FILES:
        regular(source / name)
    license_path = regular(repo / 'LICENSE')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.fullhan-build-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'LSCamoflash-fullhan'
        stage.mkdir(mode=0o700)
        for name in FILES:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
        (stage / 'bin').mkdir()
        shutil.copyfile(busybox, stage / 'bin/busybox')
        for name in ('start.sh', 'stop.sh', 'bin/busybox', 'www/cgi-bin/status.cgi'):
            (stage / name).chmod(0o755)
        shutil.copyfile(license_path, stage / 'LICENSE.MIT')
        (stage / 'COPYING.BusyBox').write_bytes(copying)
        if auth:
            (stage / 'httpd.conf').write_bytes(auth)
            (stage / 'httpd.conf').chmod(0o600)
        manifest = {'format': FORMAT, 'target': 'FH8626V100 / SZB22705 FW7.6.23',
                    'stock_sha256': 'ef9545b2f4fce419d71dadf7723a9cb010500c994a87a325a8c325b51648c8b2',
                    'busybox': elf, 'arm1176_smoke': bool(args.qemu),
                    'credentials_provisioned': auth is not None,
                    'files': {name: NOR.digest(stage / name) for name in sorted((*FILES, 'bin/busybox', 'LICENSE.MIT', 'COPYING.BusyBox'))}}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Credentials are intentionally site-owned, not part of the public
        # payload checksum list. Runtime validates their strict auth grammar.
        names = sorted((*manifest['files'], 'manifest.json'))
        (stage / 'SHA256SUMS').write_text(''.join(NOR.digest(stage / name) + '  ' + name + '\n' for name in names))
        validate_output(output)
        stage.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'SOURCE/fullhan-kit/LSCamoflash-fullhan')
    parser.add_argument('--busybox', type=Path, default=Path(os.environ.get('BB', str(REPO / 'SOURCE/build/mmcblk0p2/HACK/bin/busybox'))))
    parser.add_argument('--readelf', default=os.environ.get('READELF', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-readelf')))
    parser.add_argument('--qemu', default=os.environ.get('QEMU_ARM'))
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password-file', type=Path, help='private host file; no default password')
    args = parser.parse_args()
    try:
        output = build(args)
    except (OSError, ValueError, KeyError, UnicodeError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Fullhan pilot build failed: ' + str(error) + '\n')
    print('Built separate manual Fullhan pilot: ' + str(output))
    print('Authentication is mandatory. Building does not install or contact a camera.')


if __name__ == '__main__':
    main()
