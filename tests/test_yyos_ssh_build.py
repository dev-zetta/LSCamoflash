"""Offline SSH-kit packaging controls: no camera, card or network access."""
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('yyos_ssh_builder_tests', REPO / 'tools/yyos/build-ssh-kit.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
PUBLIC = b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(range(1, 33))
HOST = b'\0\0\0\x0bssh-ed25519\0\0\0\x40' + bytes(range(1, 65))


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yyos-ssh-build-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.source = self.repo / 'SOURCE/src/yyos-ssh'
        self.source.mkdir(parents=True)
        for name in B.RUNTIME_FILES:
            (self.source / name).write_text('#!/bin/sh\nexit 0\n' if name.endswith('.sh') else 'Fixture runtime\n')
        (self.repo / 'tools/yyos').mkdir(parents=True)
        (self.repo / 'tools/yyos/boot.sh').write_text('#!/bin/sh\nexit 0\n')
        (self.repo / 'LICENSE').write_text('Fixture project license\n')
        self.binary = self.root / 'dropbearmulti'
        self.binary.write_bytes(b'Fixture ELF, validated separately in ARM smoke')
        self.bb = self.root / 'busybox'
        self.bb.write_bytes(b'Fixture BusyBox ELF')
        self.client = self.root / 'client.pub'
        self.client.write_bytes(b'ssh-ed25519 ' + base64.b64encode(PUBLIC) + b'\n')
        self.host = self.root / 'host'
        self.host.write_bytes(HOST)
        self.archive = self.root / 'dropbear.tar.bz2'
        with tarfile.open(self.archive, 'w:bz2') as archive:
            for name in ('LICENSE', 'libtomcrypt/LICENSE', 'libtommath/LICENSE',
                         'src/mlkem768.c', 'src/libcrux_mlkem768_sha3.h', 'src/sntrup761.c',
                         'src/ed25519.c', 'src/sshpty.c', 'src/atomicio.c'):
                data = b'Fixture component license\n' if 'LICENSE' in name else b'/* OpenBSD */\n/* MIT License: Copyright Fixture. Permission is hereby granted. */\nint fixture;\n'
                member = tarfile.TarInfo('dropbear-2026.94/' + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        options = {key: 0 for key in ('DROPBEAR_SVR_PASSWORD_AUTH', 'DROPBEAR_SVR_PAM_AUTH',
                    'DROPBEAR_SVR_LOCALTCPFWD', 'DROPBEAR_SVR_REMOTETCPFWD', 'DROPBEAR_SVR_LOCALSTREAMFWD',
                    'DROPBEAR_SVR_REMOTESTREAMFWD', 'DROPBEAR_X11FWD', 'DROPBEAR_SVR_AGENTFWD', 'DROPBEAR_SFTPSERVER')}
        options.update(DROPBEAR_SVR_PUBKEY_AUTH=1, DROPBEAR_ED25519=1)
        text = ''.join(f'#define {key} {value}\n' for key, value in options.items())
        self.report = self.root / 'provenance.json'
        self.metadata = {'version': '2026.94', 'binary_sha256': B.NOR.digest(self.binary),
                         'source_archive_sha256': B.NOR.digest(self.archive), 'localoptions': text,
                         'localoptions_sha256': hashlib.sha256(text.encode()).hexdigest(),
                         'configure_flags': ['--enable-static', '--disable-syslog', '--disable-shadow']}
        self.report.write_text(json.dumps(self.metadata))
        self.args = SimpleNamespace(output=self.root / 'output', dropbear=self.binary, busybox=self.bb,
                                    client_public_key=self.client, host_key=self.host, dropbear_source=self.archive,
                                    dropbear_provenance=self.report, readelf='/bin/true', qemu=None)
        for target, value in ((patch.object(B, 'REPO', self.repo), None),
                              (patch.object(B, 'SOURCE', self.source), None),
                              (patch.object(B, 'SOURCE_SHA', B.NOR.digest(self.archive)), None),
                              (patch.object(B.BACKUP, 'busybox_sources', return_value=(b'Fixture GPLv2', {})), None),
                              (patch.object(B.NOR, 'validate_arm_elf', side_effect=lambda path, reader: {'sha256': B.NOR.digest(path), 'static': True}), None)):
            target.start()
            self.addCleanup(target.stop)

    def test_inventory_checksums_and_private_exclusions(self):
        output = B.build(self.args)
        runtime = output / 'card/LSCamoflash-yyos-ssh'
        files = {path.relative_to(runtime).as_posix() for path in runtime.rglob('*') if path.is_file()}
        self.assertEqual(files, set(B.PUBLIC_FILES) | set(B.PRIVATE_FILES) | {'SHA256SUMS'})
        for root in (output, runtime):
            for line in (root / 'SHA256SUMS').read_text().splitlines():
                value, name = line.split('  ', 1)
                self.assertEqual(value, B.NOR.digest(root / name))
                self.assertNotIn(Path(name).name, B.PRIVATE_FILES)
        self.assertEqual((runtime / 'ssh.enabled').read_bytes(), b'enabled\n')
        self.assertEqual((runtime / 'dropbear_ed25519_host_key').stat().st_mode & 0o777, 0o600)
        self.assertEqual((output / 'boot/normal-http-boot.sh').read_bytes(), (self.repo / 'tools/yyos/boot.sh').read_bytes())
        self.assertIn(b'MIT License', (runtime / 'COPYING.Dropbear').read_bytes())
        self.assertFalse(any((output / name).exists() for name in ('yy_debug.ini', 'telnetd', 'yy_telnet_start')))

    def test_nonempty_output_preserved(self):
        self.args.output.mkdir()
        sentinel = self.args.output / 'keep'
        sentinel.write_bytes(b'preserve')
        with self.assertRaises(ValueError):
            B.build(self.args)
        self.assertEqual(sentinel.read_bytes(), b'preserve')

    def test_symlink_output_and_input_refused(self):
        self.args.output.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            B.build(self.args)
        self.args.output.unlink()
        alias = self.root / 'alias.pub'
        alias.symlink_to(self.client)
        with self.assertRaises(ValueError):
            B.public_key(alias)

    def test_public_key_requires_single_bare_canonical_wire_key(self):
        valid = self.client.read_bytes()
        invalid = [b'command="sh" ' + valid, valid.rstrip() + b' owner\n', valid + valid,
                   b'ssh-ed25519 !!!\n', b'ssh-ed25519 ' + base64.b64encode(PUBLIC[:-1]) + b'\n']
        for data in invalid:
            self.client.write_bytes(data)
            with self.subTest(case=len(data)), self.assertRaises(ValueError):
                B.public_key(self.client)

    def test_host_key_requires_exact_dropbear_type_and_length(self):
        for data in (HOST[:-1], HOST + b'\0', b'-----BEGIN OPENSSH PRIVATE KEY-----', HOST[:19] + bytes(64)):
            self.host.write_bytes(data)
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                B.host_key(self.host)

    def test_source_archive_and_binary_provenance_binding(self):
        self.archive.write_bytes(b'wrong source')
        with self.assertRaises(ValueError):
            B.source_license(self.archive)
        self.metadata['binary_sha256'] = '0' * 64
        self.report.write_text(json.dumps(self.metadata))
        with self.assertRaises(ValueError):
            B.provenance(self.report, self.binary)

    def test_password_capable_build_and_private_host_paths_refused(self):
        self.metadata['localoptions'] = self.metadata['localoptions'].replace('PASSWORD_AUTH 0', 'PASSWORD_AUTH 1')
        self.metadata['localoptions_sha256'] = hashlib.sha256(self.metadata['localoptions'].encode()).hexdigest()
        self.report.write_text(json.dumps(self.metadata))
        with self.assertRaises(ValueError):
            B.provenance(self.report, self.binary)
        self.metadata['localoptions'] = self.metadata['localoptions'].replace('PASSWORD_AUTH 1', 'PASSWORD_AUTH 0')
        self.metadata['localoptions_sha256'] = hashlib.sha256(self.metadata['localoptions'].encode()).hexdigest()
        self.metadata['cflags'] = '-I/home/private/source'
        self.report.write_text(json.dumps(self.metadata))
        with self.assertRaises(ValueError):
            B.provenance(self.report, self.binary)

    def test_boot_executes_http_child_before_detached_ssh(self):
        busybox = shutil.which('busybox')
        if not busybox:
            self.fail('Host BusyBox is required for the bounded boot-composition fixture')
        card = self.root / 'card'
        ssh = card / 'LSCamoflash-yyos-ssh'
        (ssh / 'bin').mkdir(parents=True)
        shutil.copyfile(busybox, card / 'busybox')
        (card / 'busybox').chmod(0o700)
        trace = self.root / 'trace'
        http = card / 'yyos-http-boot.sh'
        http.write_text(f'#!/bin/sh\nprintf "http\\n" >> "{trace}"\nexit 17\n')
        (ssh / 'start.sh').write_text(f'#!/bin/sh\nprintf "ssh\\n" >> "{trace}"\n')
        B.NOR.write_sums(ssh, ('start.sh',))
        script = self.root / 'boot.sh'
        script.write_bytes(B.boot_wrapper(B.NOR.digest(http)).replace(b'/mnt/sdcard', str(card).encode()))
        result = subprocess.run(['/bin/sh', str(script), str(card)], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 17)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (not trace.exists() or trace.read_text() != 'http\nssh\n'):
            time.sleep(0.02)
        self.assertEqual(trace.read_text(), 'http\nssh\n')

    def test_missing_optional_ssh_does_not_block_http(self):
        busybox = shutil.which('busybox')
        self.assertIsNotNone(busybox, 'Host BusyBox is required for the boot-composition fixture')
        card = self.root / 'card'
        card.mkdir()
        shutil.copyfile(busybox, card / 'busybox')
        (card / 'busybox').chmod(0o700)
        trace = self.root / 'trace'
        http = card / 'yyos-http-boot.sh'
        http.write_text(f'#!/bin/sh\nprintf "http\\n" >> "{trace}"\nexit 0\n')
        script = self.root / 'boot.sh'
        script.write_bytes(B.boot_wrapper(B.NOR.digest(http)).replace(b'/mnt/sdcard', str(card).encode()))
        result = subprocess.run(['/bin/sh', str(script), str(card)], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(trace.read_text(), 'http\n')


if __name__ == '__main__':
    unittest.main()
