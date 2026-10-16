#!/usr/bin/env python3
"""Assemble a separate YYOS management kit offline; never install or contact a camera."""
import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = REPO / 'SOURCE/src/yyos'
FILES = ('common.sh', 'start.sh', 'stop.sh', 'README.md', 'www/index.html',
         'www/dashboard.js', 'www/dashboard.css', 'www/cgi-bin/status.cgi', 'www/cgi-bin/recordings.cgi')
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
CONTROLS = module('yyos_native_controls_builder', HERE / 'build-controls.py')
CONTROL_FILES = ('bin/yyos-controls', 'bin/yyos-controls-cgi', 'COPYING.Controls',
                 'controls-provenance.json', 'www/cgi-bin/controls.cgi')


def controls_file(root, name, limit=32 * 1024 * 1024):
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or '..' in relative.parts:
        raise ValueError('Unsafe controls build inventory path')
    path = root.joinpath(*relative.parts)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Controls inputs must not contain symlink ancestors')
    AUTH.regular(path)
    if path.stat().st_size > limit:
        raise ValueError('Controls build input exceeds size limit')
    return path


def validate_controls(build_root, runtime=None, expected_proof=None, libc=None):
    """Validate production source/object proof; return proof and build-layout files.

    Source mapping keys are relative to a controls build root. Package producers
    preserve them under sources/controls/, including the pinned archives/objects.
    No native-control.key, fixture binary or host credential enters this mapping.
    """
    root = Path(build_root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError('Regular controls build directory required')
    proof = json.loads(controls_file(root, 'provenance.json', 1024 * 1024).read_text())
    if not isinstance(proof, dict) or any(not isinstance(proof.get(name), dict)
            for name in ('elf', 'qemu', 'libc')):
        raise ValueError('Controls provenance objects are malformed')
    h = CONTROLS.helpers()
    if (type(proof.get('schema')) is not int or proof['schema'] != 1
            or proof.get('name') != 'yyos-controls' or proof.get('version') != '1'
            or proof.get('source_archive_sha256') != CONTROLS.SOURCE_SHA256
            or proof.get('bridge_source_sha256') != CONTROLS.BRIDGE_SHA256
            or proof.get('clock_compat_sha256') != CONTROLS.CLOCK_SHA256
            or proof.get('build_script_sha256') != NOR.digest(HERE / 'build-controls.py')
            or proof.get('build_helper_sha256') != NOR.digest(HERE / 'build-dropbear.py')
            or proof.get('cflags') != CONTROLS.CFLAGS
            or proof.get('crypto_definitions') != CONTROLS.DEFINITIONS
            or proof.get('static_libc_version') != 'musl1.2.6'
            or proof.get('test_fixture_compiled') is not False
            or proof.get('keys_generated') is not False
            or proof.get('camera_contacted') is not False
            or proof.get('physical_hard_deadline_proven') is not False
            or type(proof.get('jog_ms')) is not int or proof['jog_ms'] != 200
            or proof.get('endpoint') != '127.0.0.1:6668'
            or proof.get('allowlist') != {'indicator': 101, 'timestamp_osd': 104, 'stop': 116,
                'jog_cardinals': {'up': '0', 'right': '2', 'down': '4', 'left': '6'}}
            or proof.get('elf', {}).get('static') is not True
            or proof.get('qemu', {}).get('passed') is not True
            or proof.get('qemu') != {'passed': True, 'cpu': 'arm926',
                'check': 'production invalid-interface exit2 before network'}):
        raise ValueError('Controls provenance differs from audited production build')
    if expected_proof is not None and proof != expected_proof:
        raise ValueError('Controls provenance differs from runtime manifest')
    library = proof.get('libc', {})
    if (not isinstance(library.get('gcc_runtime_notices'), dict)
            or any(not re.fullmatch(r'[0-9a-f]{64}', str(library.get(name, '')))
                   for name in ('license_sha256', 'provenance_sha256'))
            or library.get('name') != 'musl' or library.get('version') != '1.2.6'
            or library.get('source_archive_sha256') !=
                'd585fd3b613c66151fc3249e8ed44f77020cb5e6c1e635a616d3f9f82460512a'
            or set(library.get('gcc_runtime_notices', {})) != {'GCC-COPYING3', 'GCC-COPYING.RUNTIME'}
            or (libc is not None and library != libc)):
        raise ValueError('Controls static libc provenance mismatch')
    names = {'provenance.json', 'COPYING.Controls', 'dropbear-2026.94.tar.bz2',
             'bin/yyos-controls', 'objects/libyyoscrypto.a',
             'sources/yyos_controls.c', 'sources/yyos-clock-compat.c',
             'sources/build-controls.py', 'sources/build-dropbear.py', 'sources/build-musl.py',
             'sources/musl-1.2.6.tar.gz', 'sources/musl-provenance.json', 'sources/crypto-patches.json'}
    archive = controls_file(root, 'dropbear-2026.94.tar.bz2')
    h.verify_source(archive)
    if NOR.digest(controls_file(root, 'sources/yyos_controls.c')) != CONTROLS.BRIDGE_SHA256:
        raise ValueError('Controls bridge source mismatch')
    if NOR.digest(controls_file(root, 'sources/yyos-clock-compat.c')) != CONTROLS.CLOCK_SHA256:
        raise ValueError('Controls clock source mismatch')
    for name in ('build-controls.py', 'build-dropbear.py', 'build-musl.py'):
        if NOR.digest(controls_file(root, 'sources/' + name)) != NOR.digest(HERE / name):
            raise ValueError('Controls retained build script mismatch')
    if (NOR.digest(controls_file(root, 'sources/musl-1.2.6.tar.gz')) != library['source_archive_sha256']
            or NOR.digest(controls_file(root, 'sources/musl-provenance.json')) != library.get('provenance_sha256')):
        raise ValueError('Controls retained libc source/provenance mismatch')
    binary = controls_file(root, 'bin/yyos-controls', 8 * 1024 * 1024)
    if set(p.name for p in (root / 'bin').iterdir()) != {'yyos-controls'}:
        raise ValueError('Controls build contains an unexpected binary')
    if (NOR.digest(binary) != proof.get('binary_sha256')
            or binary.stat().st_size != proof.get('binary_bytes')
            or h.check_elf(binary) != proof.get('elf')
            or b'YYOS_FIXTURE_' in binary.read_bytes()
            or b'0123456789abcdef' in binary.read_bytes()):
        raise ValueError('Controls binary differs from production provenance')
    if NOR.digest(controls_file(root, 'objects/libyyoscrypto.a')) != proof.get('crypto_archive_sha256'):
        raise ValueError('Controls crypto archive mismatch')
    expected = [(f'objects/crypto-{i:02d}.o', 'dropbear-2026.94/libtomcrypt/src/' + name)
                for i, name in enumerate(CONTROLS.CRYPTO_SOURCES)]
    expected += [('objects/controls.o', 'sources/yyos_controls.c'),
                 ('objects/clock.o', 'sources/yyos-clock-compat.c')]
    objects = proof.get('objects')
    if (not isinstance(objects, list) or any(not isinstance(x, dict) for x in objects)
            or [(x.get('object'), x.get('source')) for x in objects] != expected):
        raise ValueError('Controls requires the exact 28 source/object mappings')
    with tempfile.TemporaryDirectory(prefix='yyos-controls-proof-') as temporary:
        pristine = h.unpack_source(archive, Path(temporary))
        patches = CONTROLS.patch_crypto(pristine / 'libtomcrypt')
        if patches != proof.get('crypto_patches') or patches != json.loads(
                controls_file(root, 'sources/crypto-patches.json', 65536).read_text()):
            raise ValueError('Controls crypto patches are not reproducible')
        for record in objects:
            for key in ('source', 'object'):
                path = controls_file(root, record[key])
                if NOR.digest(path) != record.get(key + '_sha256'):
                    raise ValueError('Controls retained source/object hash mismatch')
                names.add(record[key])
            if record['source'].startswith('dropbear-2026.94/'):
                original = Path(temporary) / record['source']
                if NOR.digest(original) != record['source_sha256']:
                    raise ValueError('Controls algorithm source differs from pinned patched upstream')
        for record in patches:
            name = 'dropbear-2026.94/libtomcrypt/' + record['file']
            if NOR.digest(controls_file(root, name)) != record['patched_sha256']:
                raise ValueError('Controls retained integration patch mismatch')
            names.add(name)
        notices = controls_file(root, 'COPYING.Controls', 1024 * 1024)
        if NOR.digest(notices) != proof.get('license_sha256'):
            raise ValueError('Controls license inventory mismatch')
        text = notices.read_text()
        labels = [('LSCamoflash MIT license', (REPO / 'LICENSE').read_text(), None),
                  ('Pinned LibTomCrypt license', (pristine / 'libtomcrypt/LICENSE').read_text(), None),
                  ('Static runtime COPYING.musl', None, library.get('license_sha256')),
                  ('Static runtime GCC-COPYING3', None, library['gcc_runtime_notices']['GCC-COPYING3']),
                  ('Static runtime GCC-COPYING.RUNTIME', None, library['gcc_runtime_notices']['GCC-COPYING.RUNTIME'])]
        for index, (label, exact, checksum) in enumerate(labels):
            marker = '===== ' + label + ' =====\n'
            if text.count(marker) != 1:
                raise ValueError('Controls license section is missing or duplicated')
            body = text.split(marker, 1)[1]
            next_marker = ('===== ' + labels[index + 1][0] + ' =====\n') if index + 1 < len(labels) else 'Only the listed LibTomCrypt'
            if next_marker not in body:
                raise ValueError('Controls license section boundary missing')
            body = body.split(next_marker, 1)[0]
            if not body.endswith('\n\n'):
                raise ValueError('Controls license section separator mismatch')
            body = body[:-2]
            if exact is not None and body != exact:
                raise ValueError('Controls source license differs from pinned notice')
            if checksum is not None:
                import hashlib
                if hashlib.sha256(body.encode()).hexdigest() != checksum:
                    raise ValueError('Controls runtime license differs from libc provenance')
    if runtime is not None:
        runtime = Path(runtime)
        for name, checksum in (('bin/yyos-controls', proof['binary_sha256']),
                               ('COPYING.Controls', proof['license_sha256'])):
            if NOR.digest(controls_file(runtime, name)) != checksum:
                raise ValueError('Runtime controls artifact differs from build proof')
        if json.loads(controls_file(runtime, 'controls-provenance.json', 1024 * 1024).read_text()) != proof:
            raise ValueError('Runtime controls proof mismatch')
    return proof, {name: controls_file(root, name) for name in sorted(names)}


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
    controls_root = getattr(args, 'controls_build', None)
    controls_musl = getattr(args, 'controls_musl_build', None)
    controls_proof = controls_compiler = controls_libc = None
    if bool(controls_root) != bool(controls_musl):
        raise ValueError('--controls-build and --controls-musl-build must be supplied together')
    if controls_root:
        controls_root = controls_root.absolute()
        controls_compiler, controls_libc = CONTROLS.helpers().validate_musl(controls_musl.absolute())
        controls_proof, _ = validate_controls(controls_root, libc=controls_libc)
    files = (*FILES, 'www/cgi-bin/controls.cgi') if controls_proof else FILES
    credentials = AUTH.password_config(args.password_file, args.username) if args.password_file else None
    copying, source_inputs = BACKUP.busybox_sources()
    for name in files:
        AUTH.regular(SOURCE / name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.yyos-management-build-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'kit'
        card = stage / 'card'
        runtime = card / 'LSCamoflash-yyos'
        runtime.mkdir(parents=True, mode=0o700)
        for name in files:
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
        recordings_source = REPO / 'SOURCE/src/contrib/yyos-recordings/yyos_recordings.c'
        AUTH.regular(recordings_source)
        subprocess.run([str(cc), *BACKUP.FLAGS, '-std=c99', '-Wall', '-Wextra', '-Werror',
                        str(recordings_source), '-o', str(runtime / 'bin/yyos-recordings')],
                       check=True, capture_output=True, timeout=120)
        recordings = NOR.validate_arm_elf(runtime / 'bin/yyos-recordings', readelf)
        controls_elf = controls_cgi_elf = controls_cgi_proof = None
        if controls_proof:
            for source_name, destination in (('bin/yyos-controls', runtime / 'bin/yyos-controls'),
                                             ('COPYING.Controls', runtime / 'COPYING.Controls'),
                                             ('provenance.json', runtime / 'controls-provenance.json')):
                shutil.copyfile(controls_file(controls_root, source_name), destination)
            controls_elf = NOR.validate_arm_elf(runtime / 'bin/yyos-controls', readelf)
            cgi_source = AUTH.regular(REPO / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c')
            subprocess.run([str(controls_compiler), *BACKUP.FLAGS,
                            str(cgi_source), str(controls_file(controls_root, 'objects/clock.o')),
                            '-o', str(runtime / 'bin/yyos-controls-cgi')],
                           check=True, capture_output=True, timeout=120)
            controls_cgi_elf = NOR.validate_arm_elf(runtime / 'bin/yyos-controls-cgi', readelf)
            controls_cgi_proof = {'source_sha256': NOR.digest(cgi_source),
                'binary_sha256': NOR.digest(runtime / 'bin/yyos-controls-cgi'),
                'libc_provenance_sha256': controls_libc['provenance_sha256'],
                'cflags': list(BACKUP.FLAGS),
                'clock_object_sha256': NOR.digest(controls_file(controls_root, 'objects/clock.o')),
                'clock_compat_sha256': CONTROLS.CLOCK_SHA256, 'elf': controls_cgi_elf}
            for name in ('bin/yyos-controls', 'bin/yyos-controls-cgi', 'www/cgi-bin/controls.cgi'):
                (runtime / name).chmod(0o755)
            validate_controls(controls_root, runtime, controls_proof, controls_libc)
        for name in ('telnetd', 'dump.sh'):
            (card / name).chmod(0o755)
        for name in ('start.sh', 'stop.sh', 'www/cgi-bin/status.cgi', 'www/cgi-bin/recordings.cgi', 'bin/yyos-recordings'):
            (runtime / name).chmod(0o755)
        (card / 'yy_telnet_start').touch(mode=0o600)
        shutil.copyfile(AUTH.regular(REPO / 'LICENSE'), runtime / 'LICENSE.MIT')
        (runtime / 'COPYING.BusyBox').write_bytes(copying)
        if credentials:
            (runtime / 'httpd.conf').write_bytes(credentials)
            (runtime / 'httpd.conf').chmod(0o600)
        names = (*files, 'bin/busybox', 'bin/yyos-recordings', 'LICENSE.MIT', 'COPYING.BusyBox')
        if controls_proof:
            names += ('bin/yyos-controls', 'bin/yyos-controls-cgi', 'COPYING.Controls', 'controls-provenance.json')
        manifest = {'format': FORMAT, 'target': '3225722 / SZ F26312 / V14.1.5 / AK3918AV130',
                    'stock_sha256': STOCK_SHA, 'busybox': elf, 'busybox_repository_sources': source_inputs,
                    'arm926_smoke': bool(qemu), 'credentials_provisioned': credentials is not None,
                    'native_media_verified': False, 'settings_write': bool(controls_proof), 'stock_app_managed': False,
                    'recordings': {'elf': recordings, 'source_sha256': NOR.digest(recordings_source),
                                   'read_only': True, 'format': 'yyos-v5-media', 'browser_playback': False},
                    'files': {name: NOR.digest(runtime / name) for name in sorted(names)}}
        if controls_proof:
            manifest.update(controls_provenance=controls_proof, controls_cgi=controls_cgi_proof,
                helpers={'yyos-controls': controls_elf, 'yyos-controls-cgi': controls_cgi_elf},
                native_control_key_provisioned=False)
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
            '**Experimental exact-profile kit; native setup and controls have separate acceptance gates.** '
            'The legacy native-media configure path remains blocked. The separate SSH-guarded disable/setup workflow retaining an existing verified 15-byte native password passed a short device check; first-time native provisioning and generalized password rotation remain unverified. '
            'The earlier 24-byte-password reboot loop and verified recovery remain documented separately. '
            'Authenticated HTTP, key-only SSH, native decoding, RTSP Digest and ONVIF WSSE passed short live checks alongside owner-reported Tuya app connectivity. '
            'Optional native controls are disabled until the owner provisions a private native-control.key outside www; public kits contain no native key. PTZ physical acceptance remains a separate gate in the current documentation. '
            'Recorded microphone sound was accepted in an earlier test; per-boot audio, direct VLC live playback, detailed app/recording behavior, repeated boots and long-term stability require separate acceptance. New UI/payload deployment is separate. '
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
    parser.add_argument('--controls-build', type=Path,
                        help='validated public build-controls.py output; omit for read-only management')
    parser.add_argument('--controls-musl-build', type=Path,
                        help='matching validated build-musl.py output, required with --controls-build')
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
