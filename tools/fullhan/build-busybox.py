#!/usr/bin/env python3
"""Build isolated Fullhan BusyBox with CGI Range forwarding; never contact a device."""
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
SPEC = importlib.util.spec_from_file_location('nor_builder', REPO / 'tools/firmware-backup/build-kit.py')
ELF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ELF)


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing regular build input: ' + path.name)
    return path


def output_guard(output):
    if any(path.is_symlink() for path in (output, *output.parents)) or output.is_mount():
        raise ValueError('Output must not be a symlink or mountpoint')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be absent or empty; existing files are never replaced')


def extract_source(archive_path, destination, name):
    total = 0
    with tarfile.open(archive_path, 'r:bz2') as archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            if (relative.is_absolute() or not relative.parts or relative.parts[0] != name
                    or '..' in relative.parts or not (member.isdir() or member.isfile())):
                raise ValueError('Unsafe BusyBox source archive member')
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            if member.size < 0 or total > 256 * 1024 * 1024 or target.exists():
                raise ValueError('Oversized or duplicate BusyBox source member')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    return destination / name


def config_value(config, name, value):
    line = name + '=' + value
    pattern = r'^(?:' + re.escape(name) + r'=.*|# ' + re.escape(name) + r' is not set)$'
    if re.search(pattern, config, re.M):
        return re.sub(pattern, lambda _: line, config, flags=re.M)
    return config + '\n' + line + '\n'


def build(args):
    output = args.output.absolute()
    output_guard(output)
    recipe = (REPO / 'SOURCE/Makefile').read_text()
    match = re.search(r'^BUSYBOX\s*:?=\s*(busybox-[A-Za-z0-9._+-]+)\s*$', recipe, re.M)
    if not match:
        raise ValueError('Missing declared BusyBox version')
    name = match[1]
    archive = regular(REPO / 'SOURCE/download' / (name + '.tar.bz2'))
    base = regular(REPO / 'SOURCE/src/patches' / name / 'uclibc-config')
    patch = regular(REPO / 'SOURCE/src/fullhan/busybox-http-range.patch')
    cc = ELF.executable(args.cc)
    readelf = ELF.executable(args.readelf)
    hostcc = ELF.executable(args.hostcc)
    qemu = ELF.executable(args.qemu) if args.qemu else None
    if not str(cc).endswith('gcc'):
        raise ValueError('ARM compiler must have a gcc cross-tool prefix')
    prefix = str(cc)[:-3]
    sysroot = subprocess.run([str(cc), '-print-sysroot'], check=True, capture_output=True,
                             text=True, timeout=5).stdout.strip()
    if not sysroot or not Path(sysroot).is_dir() or any(c in sysroot + prefix for c in '\n\r"'):
        raise ValueError('Compiler did not provide a usable sysroot')
    config = base.read_text()
    for key, value in (
            ('CONFIG_CROSS_COMPILER_PREFIX', json.dumps(prefix)),
            ('CONFIG_SYSROOT', json.dumps(str(Path(sysroot).resolve()))),
            ('CONFIG_EXTRA_CFLAGS', '"-march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -marm"'),
            ('CONFIG_STATIC', 'y'), ('CONFIG_PIE', 'n')):
        config = config_value(config, key, value)
    for setting in ('CONFIG_FEATURE_HTTPD_RANGES=y', 'CONFIG_FEATURE_HTTPD_CGI=y',
                    'CONFIG_FEATURE_HTTPD_BASIC_AUTH=y', 'CONFIG_FEATURE_HTTPD_AUTH_MD5=y'):
        if setting not in config.splitlines():
            raise ValueError('Base configuration lacks required HTTP features')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.fullhan-busybox-', dir=output.parent) as temporary:
        work = Path(temporary)
        source = extract_source(archive, work, name)
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)],
                       cwd=source, check=True, capture_output=True, timeout=10)
        (source / '.config').write_text(config)
        env = dict(os.environ, LC_ALL='C', PATH=str(cc.parent) + os.pathsep + os.defpath)
        for key in ('CC', 'CXX', 'CPP', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS', 'AR', 'LD', 'CROSS_COMPILE'):
            env.pop(key, None)
        with (work / 'build.log').open('wb') as log:
            try:
                subprocess.run(['make', 'oldconfig', 'HOSTCC=' + str(hostcc), 'CROSS_COMPILE=' + prefix],
                               cwd=source, env=env, stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=120)
                subprocess.run(['make', '-j' + str(args.jobs), 'HOSTCC=' + str(hostcc),
                                'CROSS_COMPILE=' + prefix], cwd=source, env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=600)
            except subprocess.SubprocessError:
                log.flush()
                raise ValueError('Isolated BusyBox compilation failed:\n' +
                                 (work / 'build.log').read_text(errors='replace')[-6000:]) from None
        stage = work / 'stage'
        (stage / 'bin').mkdir(parents=True)
        binary = stage / 'bin/busybox'
        shutil.copyfile(regular(source / 'busybox'), binary)
        binary.chmod(0o755)
        metadata = {'format': 'lscamoflash-fullhan-busybox-v1', 'sha256': ELF.digest(binary),
                    'cgi_range_header': True, 'source_archive': {'name': archive.name, 'sha256': ELF.digest(archive)},
                    'base_config_sha256': ELF.digest(base), 'patch_sha256': ELF.digest(patch),
                    'effective_config_sha256': ELF.digest(source / '.config'),
                    'elf': ELF.validate_arm_elf(binary, readelf), 'arm1176_smoke': False}
        metadata['compiler'] = subprocess.run([str(cc), '--version'], check=True, capture_output=True,
                                              text=True, timeout=5).stdout.splitlines()[0]
        if qemu:
            smoke = subprocess.run([str(qemu), '-cpu', 'arm1176', str(binary), 'echo', 'fullhan-busybox-ok'],
                                   check=True, capture_output=True, text=True, timeout=5)
            auth = subprocess.run([str(qemu), '-cpu', 'arm1176', str(binary), 'httpd', '-m', ''],
                                  check=True, capture_output=True, text=True, timeout=5)
            if smoke.stdout.strip() != 'fullhan-busybox-ok' or not re.fullmatch(r'\$1\$[A-Za-z0-9./]{1,8}\$[A-Za-z0-9./]{22}', auth.stdout.strip()):
                raise ValueError('ARM1176 BusyBox/authentication smoke failed')
            metadata['arm1176_smoke'] = True
        shutil.copyfile(source / '.config', stage / '.config')
        shutil.copyfile(regular(source / 'LICENSE'), stage / 'COPYING.BusyBox')
        (stage / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
        names = ('bin/busybox', '.config', 'COPYING.BusyBox', 'manifest.json')
        (stage / 'SHA256SUMS').write_text(''.join(ELF.digest(stage / item) + '  ' + item + '\n' for item in names))
        output_guard(output)
        stage.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'SOURCE/fullhan-busybox')
    parser.add_argument('--cc', default=os.environ.get('CC', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-gcc')))
    parser.add_argument('--hostcc', default='cc')
    parser.add_argument('--readelf', default=os.environ.get('READELF', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-readelf')))
    parser.add_argument('--qemu', default=os.environ.get('QEMU_ARM'))
    parser.add_argument('--jobs', type=int, choices=range(1, 33), default=min(os.cpu_count() or 1, 4))
    args = parser.parse_args()
    try:
        output = build(args)
    except (OSError, ValueError, UnicodeError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Fullhan BusyBox build failed: ' + str(error) + '\n')
    print('Built isolated Fullhan BusyBox: ' + str(output))


if __name__ == '__main__':
    main()
