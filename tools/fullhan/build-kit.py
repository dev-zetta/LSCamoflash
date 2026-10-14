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
import uuid

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'SOURCE/src/fullhan'
FILES = ('start.sh', 'stop.sh', 'common.sh', 'README.md', 'www/index.html',
         'www/dashboard.js', 'www/dashboard.css', 'www/cgi-bin/status.cgi', 'www/cgi-bin/recordings.cgi')
ONVIF_FILES = ('onvif-start.sh', 'onvif-stop.sh', 'onvif-common.sh')
FORMAT = 'lscamoflash-fullhan-management-v2'
APPLETS = {'sh', 'httpd', 'id', 'sha256sum', 'awk', 'stat', 'find', 'sed', 'readlink',
           'netstat', 'ip', 'tr', 'mkdir', 'rmdir', 'rm', 'kill', 'sleep', 'df', 'cat', 'pidof'}
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


def compile_helper(source, destination, cc, readelf, qemu):
    regular(source)
    subprocess.run([str(cc), '-Os', '-std=c99', '-Wall', '-Wextra', '-Werror',
                    '-march=armv5te', '-mfloat-abi=soft', '-marm', '-static',
                    str(source), '-o', str(destination)], check=True, capture_output=True, timeout=120)
    metadata = NOR.validate_arm_elf(destination, readelf)
    if qemu:
        # Invalid CGI/CLI input must fail before accessing a device or socket.
        probe = subprocess.run([str(qemu), '-cpu', 'arm1176', str(destination)],
                               env={'REQUEST_METHOD': 'POST'}, capture_output=True, timeout=10)
        if destination.name == 'fullhan-discovery':
            valid = probe.returncode == 2
        else:
            valid = probe.returncode >= 0 and (b'Status: 401' in probe.stdout or b'Status: 405' in probe.stdout)
        if not valid:
            raise ValueError('Helper invalid-input smoke failed')
    return metadata


def onvif_credentials(password_file, username):
    regular(password_file)
    data = password_file.read_bytes().removesuffix(b'\n').removesuffix(b'\r')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', username) or not 1 <= len(data) <= 128 or any(v < 32 or v > 126 for v in data):
        raise ValueError('ONVIF credentials require a valid username and one printable password line of at most 128 bytes')
    return username.encode('ascii') + b'\n' + data + b'\n'


def build(args, repo=REPO):
    output = args.output.absolute()
    validate_output(output)
    busybox = regular(args.busybox.absolute())
    busybox_manifest = args.busybox_manifest or busybox.parent.parent / 'manifest.json'
    busybox_provenance = json.loads(regular(busybox_manifest).read_text())
    if busybox_provenance.get('format') != 'lscamoflash-fullhan-busybox-v1' or busybox_provenance.get('sha256') != NOR.digest(busybox) or busybox_provenance.get('cgi_range_header') is not True:
        raise ValueError('Fullhan BusyBox provenance must verify the CGI Range header patch')
    readelf = NOR.executable(args.readelf)
    cc = NOR.executable(args.cc)
    qemu = NOR.executable(args.qemu) if args.qemu else None
    elf = NOR.validate_arm_elf(busybox, readelf)
    if args.qemu:
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
    onvif_kit = args.onvif_kit.absolute() if args.onvif_kit else None
    if args.onvif_password_file and not onvif_kit:
        raise ValueError('--onvif-password-file requires --onvif-kit')
    onvif_auth = onvif_credentials(args.onvif_password_file, args.username) if args.onvif_password_file else None
    copying = busybox_license(repo)
    source = repo / 'SOURCE/src/fullhan'
    names = (*FILES, *ONVIF_FILES) if onvif_kit else FILES
    for name in names:
        regular(source / name)
    license_path = regular(repo / 'LICENSE')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.fullhan-build-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'LSCamoflash-fullhan'
        stage.mkdir(mode=0o700)
        for name in names:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
        (stage / 'bin').mkdir()
        shutil.copyfile(busybox, stage / 'bin/busybox')
        helpers = {}
        for name, input_name in (('fullhan-recordings', 'fullhan-recordings/fullhan_recordings.c'),
                                 ('fullhan-discovery', 'fullhan-discovery/discovery.c')):
            helpers[name] = compile_helper(repo / 'SOURCE/src/contrib' / input_name,
                                           stage / 'bin' / name, cc, readelf, qemu)
        if onvif_kit:
            for name in ('bin/onvif_srvd', 'COPYING.ONVIF'):
                shutil.copyfile(regular(onvif_kit / name), stage / name)
            NOR.validate_arm_elf(stage / 'bin/onvif_srvd', readelf)
            provenance = json.loads(regular(onvif_kit / 'manifest.json').read_text())
            if provenance.get('format') != 'lscamoflash-fullhan-onvif-v1' or provenance.get('sha256') != NOR.digest(stage / 'bin/onvif_srvd'):
                raise ValueError('ONVIF provenance does not match the packaged binary')
            if onvif_auth:
                (stage / 'onvif.auth').write_bytes(onvif_auth)
                (stage / 'onvif.uuid').write_text(str(uuid.uuid4()) + '\n')
                (stage / 'onvif.auth').chmod(0o600)
                (stage / 'onvif.uuid').chmod(0o600)
        for name in ('start.sh', 'stop.sh', 'bin/busybox', 'bin/fullhan-recordings', 'bin/fullhan-discovery', 'www/cgi-bin/status.cgi', 'www/cgi-bin/recordings.cgi', *ONVIF_FILES):
            if not (stage / name).exists():
                continue
            (stage / name).chmod(0o755)
        if onvif_kit:
            (stage / 'bin/onvif_srvd').chmod(0o755)
        shutil.copyfile(license_path, stage / 'LICENSE.MIT')
        (stage / 'COPYING.BusyBox').write_bytes(copying)
        if auth:
            (stage / 'httpd.conf').write_bytes(auth)
            (stage / 'httpd.conf').chmod(0o600)
        manifest = {'format': FORMAT, 'target': 'FH8626V100 / SZB22705 FW7.6.23',
                    'stock_sha256': 'ef9545b2f4fce419d71dadf7723a9cb010500c994a87a325a8c325b51648c8b2',
                    'busybox': elf, 'busybox_provenance': busybox_provenance, 'arm1176_smoke': bool(args.qemu),
                    'credentials_provisioned': auth is not None,
                    'helpers': helpers, 'onvif_included': onvif_kit is not None,
                    'onvif_credentials_provisioned': onvif_auth is not None,
                    'files': {name: NOR.digest(stage / name) for name in sorted((*names, 'bin/busybox', 'bin/fullhan-recordings', 'bin/fullhan-discovery', 'LICENSE.MIT', 'COPYING.BusyBox', *(('bin/onvif_srvd', 'COPYING.ONVIF') if onvif_kit else ())))}}
        if onvif_kit:
            manifest['onvif_provenance'] = provenance
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
    parser.add_argument('--busybox', type=Path, default=Path(os.environ.get('BB', str(REPO / 'SOURCE/fullhan-busybox/bin/busybox'))))
    parser.add_argument('--busybox-manifest', type=Path, help='matching isolated BusyBox provenance; defaults beside its bin directory')
    parser.add_argument('--readelf', default=os.environ.get('READELF', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-readelf')))
    parser.add_argument('--qemu', default=os.environ.get('QEMU_ARM'))
    parser.add_argument('--cc', default=os.environ.get('CC', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-gcc')))
    parser.add_argument('--onvif-kit', type=Path, help='separately built static ONVIF payload')
    parser.add_argument('--onvif-password-file', type=Path, help='private independent ONVIF password; never included by default')
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
