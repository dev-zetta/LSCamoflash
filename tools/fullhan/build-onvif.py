#!/usr/bin/env python3
"""Build an isolated static read-only Fullhan ONVIF server; never contact a device."""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('backup_builder', REPO / 'tools/firmware-backup/build-kit.py')
ELF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ELF)


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing regular build input: ' + path.name)
    return path


def run(command, **kwargs):
    subprocess.run([str(arg) for arg in command], check=True, **kwargs)


def build(args):
    output = args.output.absolute()
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError('Output cannot use symlinks')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be absent or empty')
    package = args.source.absolute()
    gsoap = package / 'gsoap-2.8/gsoap'
    generated_input = package / 'build/generated'
    compiler = ELF.executable(args.cxx)
    readelf = ELF.executable(args.readelf)
    for name in ('onvif.h', 'version.h'):
        regular(generated_input / name)
    regular(gsoap / 'src/soapcpp2')
    regular(REPO / 'SOURCE/src/fullhan/onvif-readonly.patch')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.fullhan-onvif-', dir=output.parent) as temporary:
        work = Path(temporary)
        shutil.copytree(package / 'src', work / 'src')
        for path in (work / 'src').iterdir():
            if path.suffix in ('.h', '.c', '.cpp'):
                path.write_text(path.read_text())
        shutil.copyfile(REPO / 'SOURCE/src/fullhan/onvif-readonly.patch', work / 'readonly.patch')
        run(['patch', '-p1', '-i', work / 'readonly.patch'], cwd=work)
        generated = work / 'generated'
        generated.mkdir()
        header = (generated_input / 'onvif.h').read_text()
        (generated / 'onvif.h').write_text(header + '\n#import "wsse.h"\n')
        shutil.copyfile(generated_input / 'version.h', generated / 'version.h')
        run([gsoap / 'src/soapcpp2', '-c++11', '-j', '-L', '-x', '-S', '-d', generated,
             '-I' + str(gsoap) + ':' + str(gsoap / 'import'), generated / 'onvif.h'])
        sources = [work / 'src' / name for name in ('daemon.c', 'onvif_srvd.cpp', 'eth_dev_param.cpp',
                   'ServiceContext.cpp', 'ServiceDevice.cpp', 'ServiceMedia.cpp', 'ServicePTZ.cpp')]
        sources += [generated / name for name in ('soapC.cpp', 'soapDeviceBindingService.cpp',
                    'soapMediaBindingService.cpp', 'soapPTZBindingService.cpp')]
        sources += [gsoap / name for name in ('custom/duration.c', 'stdsoap2.cpp', 'dom.cpp',
                    'plugin/wsseapi.c', 'plugin/mecevp.c', 'plugin/smdevp.c', 'plugin/wsaapi.c', 'plugin/httpda.c')]
        flags = ['-std=c++11', '-Os', '-DNDEBUG', '-DWITH_OPENSSL', '-DWITH_DOM',
                 '-DDAEMON_NAME="onvif_srvd"', '-DDAEMON_PID_FILE_NAME="onvif_srvd.pid"',
                 '-DDAEMON_LOG_FILE_NAME="onvif_srvd.log"', '-DDAEMON_NO_CHDIR=1', '-DDAEMON_NO_CLOSE_STDIO=1']
        if not args.host:
            flags += ['-march=armv5te', '-mfloat-abi=soft']
        for directory in (work / 'src', generated, gsoap, gsoap / 'custom', gsoap / 'plugin',
                          gsoap / 'import', args.openssl / 'include'):
            flags += ['-I' + str(directory)]
        objects = [work / ('object-' + str(index) + '.o') for index in range(len(sources))]
        def compile_one(pair):
            source, obj = pair
            run([compiler, *flags, '-x', 'c++', '-c', source, '-o', obj])
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            list(pool.map(compile_one, zip(sources, objects)))
        stage = work / 'stage'
        (stage / 'bin').mkdir(parents=True)
        binary = stage / 'bin/onvif_srvd'
        libraries = ['-lssl', '-lcrypto', '-lz', '-lpthread', '-ldl']
        run([compiler, '-static', '-s', *objects, '-L' + str(args.openssl / 'lib'), *libraries, '-o', binary])
        metadata = {'format': 'lscamoflash-fullhan-onvif-v1', 'authentication': ['WSSE UsernameToken', 'HTTP Digest'],
                    'pre_auth_operations': ['GetSystemDateAndTime'],
                    'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'arm1176_smoke': False}
        metadata['patch_sha256'] = ELF.digest(REPO / 'SOURCE/src/fullhan/onvif-readonly.patch')
        metadata['source_archives'] = {name: ELF.digest(regular(REPO / 'SOURCE/download' / name)) for name in
            ('onvif_srvd-2.0.tar.gz', 'openssl-3.0.12.tar.gz', 'zlib-1.3.1.tar.gz',
             'armv5-eabi--uclibc--stable-2020.08-1.tar.bz2')}
        metadata['binding_input_sha256'] = ELF.digest(generated_input / 'onvif.h')
        # onvif_srvd bundles gSOAP 2.8.92 independently of the main recipe's
        # gsoap archive. Record the exact consumed code and static libraries.
        inputs = {('onvif/src/' + path.name): ELF.digest(path) for path in (package / 'src').iterdir()
                  if path.suffix in ('.c', '.cpp', '.h')}
        inputs.update({('gsoap/' + str(path.relative_to(gsoap))): ELF.digest(path)
                       for path in gsoap.rglob('*') if path.is_file() and path.suffix in ('.c', '.cpp', '.h')})
        inputs['gsoap/host-soapcpp2'] = ELF.digest(gsoap / 'src/soapcpp2')
        inputs['onvif/SDK/gsoap_2.8.92.zip'] = ELF.digest(regular(package / 'SDK/gsoap_2.8.92.zip'))
        for name in ('libssl.a', 'libcrypto.a', 'libz.a'):
            library = args.openssl / 'lib' / name
            if library.is_file():
                inputs['static-libraries/' + name] = ELF.digest(library)
        metadata['build_inputs_sha256'] = inputs
        metadata['compiler'] = subprocess.run([str(compiler), '--version'], check=True, capture_output=True,
                                              text=True, timeout=5).stdout.splitlines()[0]
        if not args.host:
            metadata['elf'] = ELF.validate_arm_elf(binary, readelf)
        if args.qemu:
            smoke = subprocess.run([str(ELF.executable(args.qemu)), '-cpu', 'arm1176', str(binary), '--version'],
                                   capture_output=True, text=True, timeout=10)
            # Upstream --version uses _exit(), so stdout can remain buffered.
            if smoke.returncode:
                raise ValueError('Static ONVIF ARM1176 smoke failed: ' + str(smoke.returncode) + ' ' + smoke.stdout[:256] + smoke.stderr[:256])
            metadata['arm1176_smoke'] = True
        notices = ['This standalone Fullhan ONVIF build includes modified onvif_srvd (MIT), gSOAP (GPLv2+ with OpenSSL exception), OpenSSL, zlib and statically linked GCC/libstdc++/uClibc runtimes from the declared Bootlin toolchain. The project MIT license does not replace these component licenses. See the release source bundle and SOURCE/3RD_PARTY_LICENSES.md for corresponding source and toolchain legal-info references.\n']
        for path in (package / 'LICENSE', package / 'gsoap-2.8/GPLv2_license.txt', package / 'gsoap-2.8/LICENSE.txt',
                     REPO / 'SOURCE/packages/openssl-3.0.12/LICENSE.txt', REPO / 'SOURCE/packages/zlib-1.3.1/LICENSE'):
            regular(path)
            notices += ['\n--- ' + path.name + ' ---\n', path.read_text(errors='replace')]
        # Preserve the plugin's explicit OpenSSL linking exception as well.
        notices += ['\n--- gSOAP authentication plugin license and OpenSSL exception ---\n',
                    '\n'.join((gsoap / 'plugin/httpda.c').read_text().splitlines()[:50]) + '\n']
        (stage / 'COPYING.ONVIF').write_text(''.join(notices))
        (stage / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
        stage.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'SOURCE/fullhan-onvif')
    parser.add_argument('--source', type=Path, default=REPO / 'SOURCE/packages/onvif_srvd-2.0')
    parser.add_argument('--openssl', type=Path, default=REPO / 'SOURCE/staging/tmp/sd/HACK')
    parser.add_argument('--cxx', default=os.environ.get('CXX', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-g++')))
    parser.add_argument('--readelf', default=os.environ.get('READELF', str(REPO / 'SOURCE/toolchain/uclibc/bin/arm-linux-readelf')))
    parser.add_argument('--qemu', default=os.environ.get('QEMU_ARM'))
    parser.add_argument('--jobs', type=int, default=min(os.cpu_count() or 1, 4))
    parser.add_argument('--host', action='store_true', help='host-only synthetic SOAP fixture build')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error('--jobs must be between 1 and 32')
    try:
        output = build(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Fullhan ONVIF build failed: ' + str(error) + '\n')
    print('Built isolated read-only ONVIF payload: ' + str(output))


if __name__ == '__main__':
    main()
