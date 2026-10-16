#!/usr/bin/env python3
"""Combine credential-free YYOS HTTP/optional SSH kits and their public source notices."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


INSTALL = module('yyos_package_install_helpers', REPO / 'tools/yyos/install-kit.py')
SSH = module('yyos_package_ssh_helpers', REPO / 'tools/yyos/build-ssh-kit.py')


def public_input(root):
    root = INSTALL.clean(root)
    if set(INSTALL.sums(root, root / 'SHA256SUMS')) != INSTALL.tree(root) - {'SHA256SUMS'}:
        raise ValueError('Input kit contains unknown, private or missing files')
    return root


def source_inputs(controls=False):
    names = {'tools/yyos/package-kit.py', 'tools/yyos/install-kit.py', 'tools/yyos/build-kit.py',
             'tools/yyos/build-ssh-kit.py', 'tools/yyos/build-dropbear.py', 'tools/yyos/build-musl.py',
             'tools/yyos/dropbear-localoptions.h', 'tools/yyos/boot.sh', 'tools/yyos/yyos-clock-compat.c',
             'tools/yyos/convert-recording.py', 'tools/yyos/recording-requirements.txt',
             'docs/yyos-setup.md', 'docs/yyos-recordings.md'}
    directories = ['SOURCE/src/yyos', 'SOURCE/src/yyos-ssh', 'SOURCE/src/contrib/yyos-recordings']
    if controls:
        names.add('tools/yyos/build-controls.py')
        names.add('docs/yyos-controls.md')
        directories.append('SOURCE/src/contrib/yyos-controls')
    for relative in directories:
        root = REPO / relative
        if root.exists():
            for path in root.rglob('*'):
                if path.is_file():
                    names.add(path.relative_to(REPO).as_posix())
    return {name: INSTALL.sha(INSTALL.regular(REPO / name)) for name in sorted(names)}


def controls_builder():
    return module('yyos_package_management_builder', INSTALL.regular(REPO / 'tools/yyos/build-kit.py'))


def validate_controls_cgi(runtime, libc):
    manifest = INSTALL.read_json(runtime / 'manifest.json')
    proof = manifest.get('controls_cgi', {})
    source = REPO / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c'
    objects = manifest.get('controls_provenance', {}).get('objects', [])
    clocks = [entry.get('object_sha256') for entry in objects if isinstance(entry, dict)
              and entry.get('object') == 'objects/clock.o'] if isinstance(objects, list) else []
    if (proof.get('source_sha256') != INSTALL.sha(INSTALL.regular(source))
            or proof.get('binary_sha256') != INSTALL.sha(INSTALL.regular(runtime / 'bin/yyos-controls-cgi'))
            or proof.get('libc_provenance_sha256') != libc.get('provenance_sha256')
            or proof.get('clock_compat_sha256') != SSH.CLOCK_SOURCE_SHA
            or len(clocks) != 1 or proof.get('clock_object_sha256') != clocks[0]
            or proof.get('cflags') != list(controls_builder().BACKUP.FLAGS)
            or proof.get('elf') != manifest.get('helpers', {}).get('yyos-controls-cgi')):
        raise ValueError('Controls CGI differs from current source/binary/libc/clock provenance')


def validate_packaged_controls(sources_root, runtime, libc):
    """Revalidate relocated public controls evidence using the shared builder."""
    sources_root = INSTALL.clean(sources_root)
    controls = sources_root / 'controls'
    validate_controls_cgi(runtime, libc)
    cgi_source = INSTALL.regular(sources_root / 'yyos_controls_cgi.c')
    if INSTALL.sha(cgi_source) != INSTALL.sha(INSTALL.regular(REPO / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c')):
        raise ValueError('Packaged controls CGI source differs from current source')
    names = INSTALL.tree(controls)
    if not names or len(names) > 128:
        raise ValueError('Invalid packaged controls source/object inventory')
    expected = INSTALL.read_json(runtime / 'manifest.json').get('controls_provenance')
    with tempfile.TemporaryDirectory(prefix='yyos-packaged-controls-') as temporary:
        root = Path(temporary)
        # Restore only known build-relative locations; never extract or execute
        # a packaged script. The validator imports the current project builder.
        for name in names:
            INSTALL.safe_name(name)
            INSTALL.write_new(root / name, INSTALL.regular(controls / name).read_bytes())
        _, mapping = controls_builder().validate_controls(root, runtime=runtime, expected_proof=expected, libc=libc)
        if set(mapping) != names:
            raise ValueError('Packaged controls contains unknown or missing source/object files')
    return {'yyos_controls_cgi.c': cgi_source,
            **{'controls/' + name: controls / name for name in sorted(names)}}


def build(args):
    management = public_input(args.management_kit)
    ssh_kit = public_input(args.ssh_kit)
    output = INSTALL.clean(args.output)
    INSTALL.output_empty(output)
    normal = management / 'card'
    http = normal / INSTALL.HTTP
    secure = ssh_kit / 'card' / INSTALL.SSH
    INSTALL.runtime(http)
    INSTALL.runtime(secure, ssh=True)
    main = INSTALL.read_json(http / 'manifest.json')
    server = INSTALL.read_json(secure / 'manifest.json')
    control_payload = {'bin/yyos-controls', 'bin/yyos-controls-cgi', 'COPYING.Controls',
                       'controls-provenance.json', 'www/cgi-bin/controls.cgi'}
    control_files = set(main['files']) & control_payload
    controls = getattr(args, 'controls_build', None)
    if control_files and control_files != control_payload:
        raise ValueError('Controls helpers, CGI, license and provenance must be included together')
    if bool(control_files) != (controls is not None):
        raise ValueError('Included controls require their matching --controls-build, and vice versa')
    if main.get('credentials_provisioned') is not False or main.get('arm926_smoke') is not True:
        raise ValueError('Public management input must be credential-free and ARM926-tested')
    if server.get('credentials_provisioned') is not False or server.get('arm926_smoke') is not True:
        raise ValueError('Public SSH input must be credential-free and ARM926-tested')
    if INSTALL.read_json(ssh_kit / 'manifest.json').get('private_output') is not False:
        raise ValueError('SSH input must be built explicitly with --credential-free')
    if {path.name for path in normal.iterdir()} != {'telnetd', 'busybox', 'dump.sh', 'yy_telnet_start', 'SHA256SUMS', INSTALL.HTTP}:
        raise ValueError('Expected the unchanged normal HTTP boot kit')
    if (normal / 'dump.sh').read_bytes() != (REPO / 'tools/yyos/boot.sh').read_bytes():
        raise ValueError('HTTP boot differs from current project source')
    if (ssh_kit / 'boot/normal-http-boot.sh').read_bytes() != (normal / 'dump.sh').read_bytes():
        raise ValueError('SSH HTTP companion differs from the normal HTTP kit')
    expected_wrapper = SSH.boot_wrapper(INSTALL.sha(normal / 'dump.sh'))
    if (ssh_kit / 'boot/boot.sh').read_bytes() != expected_wrapper:
        raise ValueError('Combined boot wrapper differs from current source')
    for root, source, files in ((http, REPO / 'SOURCE/src/yyos', main['files']),
                                (secure, REPO / 'SOURCE/src/yyos-ssh', server['files'])):
        for name in files:
            if (source / name).is_file() and INSTALL.sha(source / name) != INSTALL.sha(root / name):
                raise ValueError('Packaged runtime differs from current source: ' + name)
    if any(INSTALL.sha(path) != INSTALL.sha(normal / 'busybox') for path in (http / 'bin/busybox', secure / 'bin/busybox')):
        raise ValueError('All YYOS BusyBox copies must be byte-identical')
    musl = INSTALL.clean(args.musl_build)
    dropbear = INSTALL.clean(args.dropbear_build)
    provenance = SSH.provenance(dropbear / 'provenance.json', secure / 'bin/dropbear')
    if provenance.get('build_script_sha256') != INSTALL.sha(INSTALL.regular(REPO / 'tools/yyos/build-dropbear.py')):
        raise ValueError('Dropbear provenance differs from the current packaged build recipe')
    libc = provenance.get('libc', {})
    if libc.get('name') != 'musl' or libc.get('version') != '1.2.6':
        raise ValueError('Public YYOS SSH requires the isolated static musl1.2.6 build')
    for name, key in (('musl-1.2.6.tar.gz', 'source_archive_sha256'), ('COPYING.musl', 'license_sha256'),
                      ('provenance.json', 'provenance_sha256')):
        if INSTALL.sha(INSTALL.regular(musl / name)) != libc.get(key):
            raise ValueError('Musl source/license/provenance identity mismatch')
    if INSTALL.read_json(musl / 'provenance.json').get('build_script_sha256') != INSTALL.sha(INSTALL.regular(REPO / 'tools/yyos/build-musl.py')):
        raise ValueError('Musl provenance differs from the current packaged build recipe')
    musl_license = (musl / 'COPYING.musl').read_bytes()
    if musl_license not in (secure / 'COPYING.Dropbear').read_bytes():
        raise ValueError('SSH runtime must retain the complete musl notice')
    if set(libc.get('gcc_runtime_notices', {})) != {'GCC-COPYING3', 'GCC-COPYING.RUNTIME'}:
        raise ValueError('Both GCC runtime notices are required')
    for name, expected in libc['gcc_runtime_notices'].items():
        if INSTALL.sha(INSTALL.regular(musl / name)) != expected or (musl / name).read_bytes() not in (secure / 'COPYING.Dropbear').read_bytes():
            raise ValueError('Missing or changed GCC runtime notice')
    source_archive = INSTALL.regular(dropbear / 'dropbear-2026.94.tar.bz2')
    if INSTALL.sha(source_archive) != SSH.SOURCE_SHA:
        raise ValueError('Dropbear source archive differs from its pinned identity')
    SSH.clock_proof(provenance, source_archive, dropbear / 'yyos-clock-compat.o')
    controls_proof = None
    control_sources = {}
    if controls is not None:
        controls = INSTALL.clean(controls)
        validate_controls_cgi(http, libc)
        controls_proof, control_sources = controls_builder().validate_controls(controls, runtime=http,
                                    expected_proof=main.get('controls_provenance'), libc=libc)
    projects = source_inputs(controls=controls is not None)
    readelf = SSH.NOR.executable(args.readelf)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.yyos-package-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'kit'
        card = stage / 'card'
        for name in INSTALL.tree(normal):
            INSTALL.write_new(card / name, (normal / name).read_bytes(), bool((normal / name).stat().st_mode & 0o111))
        for name in INSTALL.tree(secure):
            INSTALL.write_new(card / INSTALL.SSH / name, (secure / name).read_bytes(), bool((secure / name).stat().st_mode & 0o111))
        INSTALL.write_new(card / 'yyos-http-boot.sh', (normal / 'dump.sh').read_bytes(), True)
        (card / 'dump.sh').write_bytes(expected_wrapper)
        SSH.NOR.write_sums(card, INSTALL.tree(card) - {'SHA256SUMS'})
        binaries = {name: SSH.NOR.validate_arm_elf(card / name, readelf) for name in
                    sorted({'telnetd', 'busybox'} | {p.relative_to(card).as_posix() for folder in (INSTALL.HTTP, INSTALL.SSH)
                    for p in (card / folder / 'bin').iterdir() if p.is_file()})}
        INSTALL.write_new(stage / 'install-kit.py', (REPO / 'tools/yyos/install-kit.py').read_bytes(), True)
        INSTALL.write_new(stage / 'SETUP.md', (REPO / 'docs/yyos-setup.md').read_bytes())
        INSTALL.write_new(stage / 'RECORDINGS.md', (REPO / 'docs/yyos-recordings.md').read_bytes())
        if controls is not None:
            INSTALL.write_new(stage / 'CONTROLS.md', INSTALL.regular(REPO / 'docs/yyos-controls.md').read_bytes())
        INSTALL.write_new(stage / 'tools/convert-recording.py', (REPO / 'tools/yyos/convert-recording.py').read_bytes(), True)
        INSTALL.write_new(stage / 'tools/recording-requirements.txt', (REPO / 'tools/yyos/recording-requirements.txt').read_bytes())
        INSTALL.write_new(stage / 'README.md',
            b'# Separate YYOS camera kit\n\nCredential-free exact-profile management for LSC3225722 / SZ F26312 / V14.1.5. Read SETUP.md, verify release checksums and provision a separate private host copy before installation. HTTP authentication is mandatory; SSH is optional and disabled until explicitly provisioned. Never copy owner client private keys to the card. The guarded Linux installer preserves recognized existing authentication/logs and unrelated card data, and never formats or writes firmware.\n')
        source_files = {'dropbear-2026.94.tar.bz2': source_archive, 'musl-1.2.6.tar.gz': musl / 'musl-1.2.6.tar.gz',
                        'COPYING.musl': musl / 'COPYING.musl', 'musl-provenance.json': musl / 'provenance.json',
                        'GCC-COPYING3': musl / 'GCC-COPYING3', 'GCC-COPYING.RUNTIME': musl / 'GCC-COPYING.RUNTIME',
                        'build-musl.py': REPO / 'tools/yyos/build-musl.py', 'build-dropbear.py': REPO / 'tools/yyos/build-dropbear.py',
                        'dropbear-localoptions.h': REPO / 'tools/yyos/dropbear-localoptions.h',
                        'yyos-clock-compat.c': REPO / 'tools/yyos/yyos-clock-compat.c',
                        'yyos-clock-compat.o': dropbear / 'yyos-clock-compat.o'}
        for name, path in source_files.items():
            INSTALL.write_new(stage / 'sources' / name, INSTALL.regular(path).read_bytes())
        if controls is not None:
            INSTALL.write_new(stage / 'sources/yyos_controls_cgi.c',
                              INSTALL.regular(REPO / 'SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c').read_bytes())
        INSTALL.write_new(stage / 'sources/dropbear-provenance.json', (json.dumps(provenance, indent=2, sort_keys=True) + '\n').encode())
        for name, path in control_sources.items():
            INSTALL.safe_name(name)
            INSTALL.write_new(stage / 'sources/controls' / name, INSTALL.regular(path).read_bytes())
        if controls is not None:
            validate_packaged_controls(stage / 'sources', card / INSTALL.HTTP, libc)
        public = INSTALL.tree(stage)
        version = (REPO / 'SOURCE/version.txt').read_text().strip()
        manifest = {'format': INSTALL.FORMAT, 'stock_sha256': INSTALL.STOCK_SHA, 'credential_free': True,
                    'version': version, 'arm926_smoke': True, 'ssh_optional_default_disabled': True,
                    'libc': libc, 'binaries': binaries, 'project_sources': projects,
                    'files': {name: INSTALL.sha(stage / name) for name in sorted(public)}}
        if controls_proof is not None:
            manifest['controls_provenance'] = controls_proof
        INSTALL.write_new(stage / 'manifest.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
        SSH.NOR.write_sums(stage, public | {'manifest.json'})
        INSTALL.validate_kit(stage, public=True)
        INSTALL.sync_tree(stage)
        INSTALL.output_empty(output)
        if output.exists():
            output.rmdir()
        stage.rename(output)
        INSTALL.sync(output.parent)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--management-kit', type=Path, required=True)
    parser.add_argument('--ssh-kit', type=Path, required=True)
    parser.add_argument('--dropbear-build', type=Path, required=True)
    parser.add_argument('--musl-build', type=Path, required=True)
    parser.add_argument('--controls-build', type=Path, help='matching optional build-controls.py output')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--readelf', default=os.environ.get('READELF', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi-readelf')))
    args = parser.parse_args()
    try:
        output = build(args)
    except (OSError, ValueError, KeyError, UnicodeError, subprocess.SubprocessError) as error:
        parser.exit(1, 'YYOS public packaging failed: ' + str(error) + '\n')
    print('Built separate credential-free YYOS package: ' + str(output))


if __name__ == '__main__':
    main()
