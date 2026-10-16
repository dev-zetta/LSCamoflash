#!/usr/bin/env python3
"""Assemble a separate YYOS management kit offline; never install or contact a camera."""
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
HERE = Path(__file__).resolve().parent
SOURCE = REPO / 'SOURCE/src/yyos'
FILES = ('common.sh', 'start.sh', 'stop.sh', 'README.md', 'www/index.html',
         'www/dashboard.js', 'www/dashboard.css', 'www/cgi-bin/status.cgi')
ROOT_FILES = {'telnetd', 'busybox', 'dump.sh', 'yy_telnet_start', 'SHA256SUMS'}
FORMAT = 'lscamoflash-yyos-management-v1'
STOCK_SHA = 'd76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7'
APPLETS = {'sh', 'httpd', 'id', 'sha256sum', 'awk', 'stat', 'find', 'sed', 'readlink',
           'netstat', 'ip', 'tr', 'mkdir', 'rmdir', 'rm', 'kill', 'sleep', 'df', 'cat', 'pidof', 'timeout'}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


AUTH = module('yyos_auth_builder', REPO / 'tools/fullhan/build-kit.py')
BACKUP = module('yyos_backup_builder', REPO / 'tools/firmware-backup/build-yyos-kit.py')
NOR = BACKUP.NOR


def output_guard(output):
    if any(p.is_symlink() for p in (output, *output.parents)) or output.is_mount():
        raise ValueError('Output must not be a symlink or mountpoint')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be absent or empty; existing files and credentials are never replaced')


def build(args):
    output = args.output.absolute()
    output_guard(output)
    busybox = AUTH.regular(args.busybox.absolute())
    if busybox.stat().st_size > 8 * 1024 * 1024 or not os.access(busybox, os.X_OK):
        raise ValueError('BusyBox must be executable and no larger than 8 MiB')
    cc = NOR.executable(args.cc)
    readelf = NOR.executable(args.readelf or str(cc).removesuffix('gcc') + 'readelf')
    elf = NOR.validate_arm_elf(busybox, readelf)
    qemu = NOR.executable(args.qemu) if args.qemu else None
    if qemu:
        applets = subprocess.run([str(qemu), '-cpu', 'arm926', str(busybox), '--list'],
                                 check=True, capture_output=True, text=True, timeout=15).stdout.splitlines()
        if APPLETS - set(applets):
            raise ValueError('BusyBox lacks required YYOS management applets')
        auth = subprocess.run([str(qemu), '-cpu', 'arm926', str(busybox), 'httpd', '-m', ''],
                              check=True, capture_output=True, text=True, timeout=5).stdout.strip()
        if not re.fullmatch(r'\$1\$[A-Za-z0-9./]{1,8}\$[A-Za-z0-9./]{22}', auth):
            raise ValueError('BusyBox HTTP authentication with MD5-crypt is required')
        subprocess.run([str(qemu), '-cpu', 'arm926', str(busybox), 'sh', '-n', str(HERE / 'boot.sh')],
                       check=True, capture_output=True, timeout=5)
    credentials = AUTH.password_config(args.password_file, args.username) if args.password_file else None
    copying, source_inputs = BACKUP.busybox_sources()
    for name in FILES:
        AUTH.regular(SOURCE / name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.yyos-management-build-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'kit'
        card = stage / 'card'
        runtime = card / 'LSCamoflash-yyos'
        runtime.mkdir(parents=True, mode=0o700)
        for name in FILES:
            destination = runtime / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, destination)
        (runtime / 'bin').mkdir()
        for destination in (card / 'busybox', runtime / 'bin/busybox'):
            shutil.copyfile(busybox, destination)
            destination.chmod(0o755)
        shutil.copyfile(HERE / 'boot.sh', card / 'dump.sh')
        subprocess.run([str(cc), *BACKUP.FLAGS, str(REPO / 'tools/firmware-backup/hostapd.c'),
                        '-o', str(card / 'telnetd')], check=True, capture_output=True, timeout=120)
        launcher = NOR.validate_arm_elf(card / 'telnetd', readelf)
        for name in ('telnetd', 'dump.sh'):
            (card / name).chmod(0o755)
        for name in ('start.sh', 'stop.sh', 'www/cgi-bin/status.cgi'):
            (runtime / name).chmod(0o755)
        (card / 'yy_telnet_start').touch(mode=0o600)
        shutil.copyfile(AUTH.regular(REPO / 'LICENSE'), runtime / 'LICENSE.MIT')
        (runtime / 'COPYING.BusyBox').write_bytes(copying)
        if credentials:
            (runtime / 'httpd.conf').write_bytes(credentials)
            (runtime / 'httpd.conf').chmod(0o600)
        names = (*FILES, 'bin/busybox', 'LICENSE.MIT', 'COPYING.BusyBox')
        manifest = {'format': FORMAT, 'target': '3225722 / SZ F26312 / V14.1.5 / AK3918AV130',
                    'stock_sha256': STOCK_SHA, 'busybox': elf, 'busybox_repository_sources': source_inputs,
                    'arm926_smoke': bool(qemu), 'credentials_provisioned': credentials is not None,
                    'native_media_verified': False, 'settings_write': False, 'stock_app_managed': False,
                    'files': {name: NOR.digest(runtime / name) for name in sorted(names)}}
        (runtime / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        NOR.write_sums(runtime, (*names, 'manifest.json'))
        public = ['LSCamoflash-yyos/' + name for name in (*names, 'manifest.json', 'SHA256SUMS')]
        NOR.write_sums(card, (*public, *(ROOT_FILES - {'SHA256SUMS'})))
        package = {'format': FORMAT + '-boot-kit', 'native_launcher': launcher,
                   'native_entry_source_sha256': NOR.digest(REPO / 'tools/firmware-backup/hostapd.c'),
                   'boot_wrapper_sha256': NOR.digest(HERE / 'boot.sh'),
                   'builder_sha256': NOR.digest(HERE / 'build-kit.py'),
                   'credentials_excluded_from_checksums': True,
                   'card_public_files': {name: NOR.digest(card / name) for name in sorted((*public, *ROOT_FILES))}}
        (stage / 'manifest.json').write_text(json.dumps(package, indent=2, sort_keys=True) + '\n')
        (stage / 'README.md').write_text(
            '# YYOS management boot kit\n\n'
            '**Known reboot-loop block: do not enable native RTSP/ONVIF or bypass the production configuration gate.** '
            'Repeated reboots were confirmed after an approved 24-byte-password attempt. '
            'Native enablement remains blocked before transport. Recovery and one native-off normal cold boot passed short verification. '
            'A separate controlled 15-byte trial passed short TCP/UDP decoding, RTSP Digest and ONVIF WSSE checks. '
            'Native-enabled normal cold boot, owner app checks and long-term stability remain pending; recorded microphone sound was accepted by the owner; the exact reboot cause is unproven. New UI/payload deployment is separate. '
            'See https://github.com/dev-zetta/LSCamoflash/blob/main/docs/yyos-recovery.md. '
            'This kit is not a recovery procedure.\n\n'
            'Experimental exact-profile management for 3225722 / SZ F26312 / V14.1.5. '
            'Only card/ belongs on the spare SD card. Building does not access a camera or write a card. '
            'The native telnetd filename starts our bounded launcher, not a Telnet server. '
            'The root dump.sh now starts the guarded management service; it is not a firmware dumper.\n\n'
            'Authentication is mandatory. A credential-free build cannot start; provision a private '
            'httpd.conf through --password-file, outside www/. Passwords and private builds must not be published. '
            'The web password is independent of native RTSP/ONVIF authentication.\n\n'
            'Archive any known previous root boot payload before staging. Preserve recordings, diagnostic output '
            'and firmware backups. Never copy legacy AP/debug/factory/update markers. Verify checksums, stage '
            'yy_telnet_start last, flush and safely eject. Remove only that root marker to disable autostart. '
            'See card/LSCamoflash-yyos/README.md for capability and acceptance limits.\n')
        NOR.write_sums(stage, ('manifest.json', 'README.md', *('card/' + name for name in (*public, *ROOT_FILES))))
        output_guard(output)
        if output.exists():
            output.rmdir()
        stage.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='absent or empty dedicated host kit directory')
    parser.add_argument('--busybox', type=Path, default=Path(os.environ.get('BB', str(REPO / 'SOURCE/build/mmcblk0p2/HACK/bin/busybox'))))
    parser.add_argument('--cc', default=os.environ.get('CC', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi-gcc')))
    parser.add_argument('--readelf', default=os.environ.get('READELF'))
    parser.add_argument('--qemu', default=os.environ.get('QEMU_ARM'))
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password-file', type=Path, help='private host password line; no default credentials')
    args = parser.parse_args()
    try:
        output = build(args)
    except (OSError, ValueError, KeyError, UnicodeError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, 'YYOS management build failed: ' + str(error) + '\n')
    print('Built separate YYOS management boot kit: ' + str(output))
    print('Building never installs or contacts a camera. Authentication is mandatory for startup.')


if __name__ == '__main__':
    main()
