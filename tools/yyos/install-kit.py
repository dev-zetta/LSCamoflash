#!/usr/bin/env python3
"""Provision and install a separate YYOS kit on an already mounted removable FAT card."""
import argparse
import base64
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

FORMAT = 'lscamoflash-yyos-combined-kit-v1'
STOCK_SHA = 'd76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7'
HTTP = 'LSCamoflash-yyos'
SSH = 'LSCamoflash-yyos-ssh'
ROOT_FILES = {'telnetd', 'busybox', 'dump.sh', 'yyos-http-boot.sh', 'yy_telnet_start', 'SHA256SUMS'}
HTTP_BASE = {'common.sh', 'start.sh', 'stop.sh', 'README.md', 'bin/busybox', 'www/index.html',
             'www/dashboard.js', 'www/dashboard.css', 'www/cgi-bin/status.cgi', 'LICENSE.MIT', 'COPYING.BusyBox'}
HTTP_RECORDINGS = {'bin/yyos-recordings', 'www/cgi-bin/recordings.cgi'}
HTTP_CONTROLS = {'bin/yyos-controls', 'bin/yyos-controls-cgi', 'COPYING.Controls',
                 'controls-provenance.json', 'www/cgi-bin/controls.cgi'}
SSH_BASE = {'common.sh', 'start.sh', 'stop.sh', 'README.md', 'bin/busybox', 'bin/dropbear',
            'LICENSE.MIT', 'COPYING.BusyBox', 'COPYING.Dropbear'}
SITE = {HTTP + '/httpd.conf', HTTP + '/native-control.key', SSH + '/authorized_keys', SSH + '/dropbear_ed25519_host_key', SSH + '/ssh.enabled'}
HOST_SITE = {'provisioning.json', 'owner_ssh_ed25519', 'owner_ssh_ed25519.pub', 'host-key.pub', 'host-key-fingerprint.txt'}
EMPTY_SHA = hashlib.sha256(b'').hexdigest()
FILE_LIMIT = 64 * 1024 * 1024
TREE_LIMIT = 192 * 1024 * 1024


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def safe_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./-]+', name):
        raise ValueError('Unsafe payload filename')
    parts = PurePosixPath(name)
    if parts.is_absolute() or '..' in parts.parts or str(parts) != name:
        raise ValueError('Unsafe payload path')
    return name


def clean(path):
    path = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Symlink files or parent directories are not permitted')
    return path


def regular(path, limit=FILE_LIMIT, empty=True):
    path = clean(path)
    size = path.lstat().st_size
    if not stat.S_ISREG(path.lstat().st_mode) or size > limit or (not empty and size == 0):
        raise ValueError('Expected a bounded regular file: ' + path.name)
    return path


def read_json(path):
    value = json.loads(regular(path, 1024 * 1024, False).read_text())
    if not isinstance(value, dict):
        raise ValueError('Expected an object manifest')
    return value


def sums(root, path, absent_marker=False):
    result = {}
    for line in regular(path, 1024 * 1024, False).read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_./-]+)', line)
        if not match or match[2] in result:
            raise ValueError('Invalid or duplicate checksum entry')
        name = safe_name(match[2])
        if absent_marker and name == 'yy_telnet_start' and not (root / name).exists():
            if match[1] != EMPTY_SHA:
                raise ValueError('Normal boot marker must be empty')
        elif sha(regular(root / name)) != match[1]:
            raise ValueError('Checksum mismatch: ' + name)
        result[name] = match[1]
    if not result or len(result) > 4096:
        raise ValueError('Invalid checksum inventory size')
    return result


def tree(root):
    files = set()
    total = 0
    for path in root.rglob('*'):
        clean(path)
        if path.is_dir():
            continue
        regular(path)
        total += path.stat().st_size
        files.add(path.relative_to(root).as_posix())
        if len(files) > 4096 or total > TREE_LIMIT:
            raise ValueError('Payload exceeds package limits')
    return files


def runtime(root, ssh=False, allow_site=False):
    manifest = read_json(root / 'manifest.json')
    expected_format = 'lscamoflash-yyos-ssh-kit-v1' if ssh else 'lscamoflash-yyos-management-v1'
    if manifest.get('format') != expected_format or manifest.get('stock_sha256') != STOCK_SHA:
        raise ValueError('Wrong YYOS runtime profile or format')
    files = manifest.get('files')
    base = SSH_BASE if ssh else HTTP_BASE
    if not isinstance(files, dict) or not base <= set(files):
        raise ValueError('Incomplete runtime manifest')
    forbidden = {'authorized_keys', 'dropbear_ed25519_host_key', 'ssh.enabled', 'startup.log', 'httpd.conf', 'native-control.key'}
    if set(files) & forbidden:
        raise ValueError('Site credentials and logs cannot enter the public runtime inventory')
    known = set(base)
    if not ssh:
        for group in (HTTP_RECORDINGS, HTTP_CONTROLS):
            included = set(files) & group
            if included and included != group:
                raise ValueError('Incomplete optional runtime group')
            known |= included
    if set(files) != known:
        raise ValueError('Unknown declared runtime file')
    if not ssh and HTTP_CONTROLS <= set(files):
        proof = manifest.get('controls_provenance')
        if not isinstance(proof, dict) or not proof or proof != read_json(root / 'controls-provenance.json'):
            raise ValueError('Controls runtime provenance is missing or mismatched')
    elif 'controls_provenance' in manifest:
        raise ValueError('Controls provenance requires its complete runtime group')
    for name, value in files.items():
        safe_name(name)
        if not re.fullmatch(r'[0-9a-f]{64}', str(value)) or sha(regular(root / name)) != value:
            raise ValueError('Runtime manifest mismatch: ' + name)
    expected = set(files) | {'manifest.json', 'SHA256SUMS'}
    if set(sums(root, root / 'SHA256SUMS')) != expected - {'SHA256SUMS'}:
        raise ValueError('Runtime checksum inventory mismatch')
    private = {'authorized_keys', 'dropbear_ed25519_host_key', 'ssh.enabled', 'startup.log'} if ssh else {'httpd.conf', 'native-control.key', 'startup.log'}
    if tree(root) - expected - (private if allow_site else set()):
        raise ValueError('Unknown or private runtime files')
    return expected


def validate_kit(kit, public=False):
    kit = clean(kit)
    manifest = read_json(kit / 'manifest.json')
    if manifest.get('format') != FORMAT or manifest.get('stock_sha256') != STOCK_SHA or manifest.get('credential_free') is not True:
        raise ValueError('Expected the separate credential-free YYOS package')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Missing public package inventory')
    if set(files) & ({'card/' + name for name in SITE} | HOST_SITE):
        raise ValueError('Site provisioning files cannot enter the public package inventory')
    for name, value in files.items():
        safe_name(name)
        if sha(regular(kit / name)) != value:
            raise ValueError('Package manifest mismatch: ' + name)
    if set(sums(kit, kit / 'SHA256SUMS')) != set(files) | {'manifest.json'}:
        raise ValueError('Package checksum inventory mismatch')
    extras = tree(kit) - set(files) - {'manifest.json', 'SHA256SUMS'}
    allowed = {'card/' + name for name in SITE} | HOST_SITE
    if extras - (set() if public else allowed):
        raise ValueError('Unexpected package files or site credentials')
    card = kit / 'card'
    http = runtime(card / HTTP, allow_site=not public)
    ssh = runtime(card / SSH, ssh=True, allow_site=not public)
    if HTTP_CONTROLS <= http:
        proof = read_json(card / HTTP / 'manifest.json')['controls_provenance']
        if manifest.get('controls_provenance') != proof:
            raise ValueError('Package controls provenance is missing or mismatched')
    elif 'controls_provenance' in manifest:
        raise ValueError('Package controls provenance requires its complete runtime group')
    expected = (ROOT_FILES - {'SHA256SUMS'}) | {HTTP + '/' + name for name in http} | {SSH + '/' + name for name in ssh}
    if set(sums(card, card / 'SHA256SUMS')) != expected:
        raise ValueError('Card public inventory mismatch')
    if set(tree(card)) - expected - {'SHA256SUMS'} - (set() if public else SITE):
        raise ValueError('Unknown card files')
    if regular(card / 'yy_telnet_start').stat().st_size:
        raise ValueError('Normal boot marker must be empty')
    return manifest


def auth_config(data):
    if not 0 < len(data) <= 4096:
        raise ValueError('Invalid web authentication file size')
    try:
        lines = data.decode('ascii').splitlines()
    except UnicodeError:
        raise ValueError('Invalid web authentication encoding') from None
    count = 0
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#') or line == 'I:index.html':
            continue
        if not re.fullmatch(r'/:([A-Za-z0-9_.-]{1,32}):\$1\$[A-Za-z0-9./]{1,8}\$[A-Za-z0-9./]{22}', line):
            raise ValueError('Web authentication must contain exactly one root-path MD5-crypt account')
        count += 1
    if count != 1:
        raise ValueError('Web authentication is mandatory')
    return data


def client_key(data):
    try:
        match = re.fullmatch(rb'ssh-ed25519 ([A-Za-z0-9+/]+={0,2})\n?', data)
        blob = base64.b64decode(match[1], validate=True) if match else b''
    except ValueError:
        blob = b''
    if (len(data) > 1024 or len(blob) != 51 or blob[:19] != b'\0\0\0\x0bssh-ed25519\0\0\0\x20'
            or blob[19:] == bytes(32) or base64.b64encode(blob) != match[1]):
        raise ValueError('Expected one bare, canonical Ed25519 client public key')
    return b'ssh-ed25519 ' + match[1] + b'\n'


def host_key(data):
    if (len(data) != 83 or data[:19] != b'\0\0\0\x0bssh-ed25519\0\0\0\x40'
            or data[19:51] == bytes(32) or data[51:] == bytes(32)):
        raise ValueError('Expected an 83-byte native Dropbear Ed25519 host key')
    return data


def output_empty(output):
    output = clean(output)
    if output.is_mount() or output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be an absent or empty dedicated host directory')


def private_input(path, limit):
    path = regular(path, limit, False)
    info = path.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Private host password/key input must be owned by the current user with mode0600')
    return path


def native_control_key(data):
    if type(data) is not bytes or len(data) != 16 or any(value < 33 or value > 126 for value in data):
        raise ValueError('Native controls require exactly16 printable ASCII key bytes')
    return data


def native_credentials(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Invalid native controls credential schema')
            result[key] = value
        return result
    try:
        value = json.loads(private_input(path, 16384).read_bytes(), object_pairs_hook=unique)
        expected = {'format', 'profile', 'firmware_version', 'app_sha256', 'device_id', 'local_key', 'protocol_version'}
        if (type(value) is not dict or set(value) != expected
                or value['format'] != 'lscamoflash-yyos-native-credentials-v1'
                or value['profile'] != 'lsc-3225722-yyos-14.1.5'
                or value['firmware_version'] != '14.1.5' or value['app_sha256'] != STOCK_SHA
                or type(value['protocol_version']) not in (int, float) or value['protocol_version'] != 3.5
                or type(value['device_id']) is not str or re.fullmatch(r'[A-Za-z0-9]{22}', value['device_id']) is None
                or type(value['local_key']) is not str):
            raise ValueError('Invalid native controls credential schema')
        return native_control_key(value['local_key'].encode('ascii'))
    except (ValueError, UnicodeError, TypeError):
        raise ValueError('Invalid private native controls credentials or permissions') from None


def private_directory(path):
    info = clean(path).stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Private provisioning output requires actual current-user-owned mode0700 host directories; FAT is unsuitable')


def write_host_new(path, data, executable=False):
    path = clean(path)
    missing = []
    directory = path.parent
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    private_directory(directory)
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        private_directory(directory)
    mode = 0o700 if executable else 0o600
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != mode):
            raise ValueError('Private host output permissions were not preserved')
        private_directory(path.parent)
    except BaseException:
        os.close(fd)
        path.unlink()
        raise
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != data:
        raise ValueError('Written-file readback mismatch: ' + path.name)


def sync(path):
    fd = os.open(clean(path), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, data, executable=False):
    path = clean(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700 if executable else 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != data:
        raise ValueError('Written-file readback mismatch: ' + path.name)


def sync_tree(root):
    for directory in sorted({root, *(p.parent for p in root.rglob('*'))}, key=lambda p: len(p.parts), reverse=True):
        sync(directory)


def provision(args):
    kit, output = clean(args.kit), clean(args.output)
    validate_kit(kit, public=True)
    output_empty(output)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', args.username):
        raise ValueError('Invalid web username')
    if args.password_file:
        password = private_input(args.password_file, 4096).read_bytes().removesuffix(b'\n').removesuffix(b'\r')
    else:
        if not sys.stdin.isatty():
            raise ValueError('Supply --password-file or use an interactive terminal for the web password')
        first = getpass.getpass('New web password: ')
        if first != getpass.getpass('Repeat web password: '):
            raise ValueError('Passwords do not match')
        password = first.encode('utf-8')
    if not 8 <= len(password) <= 1024 or any(value < 32 or value == 127 for value in password):
        raise ValueError('Web password must be one line of 8..1024 bytes without controls')
    openssl = shutil.which('openssl')
    if not openssl:
        raise ValueError('Host OpenSSL is required for private web-password hashing')
    result = subprocess.run([openssl, 'passwd', '-1', '-stdin'], input=password + b'\n', capture_output=True, timeout=10)
    if result.returncode:
        raise ValueError('Web-password hashing failed')
    config = auth_config(b'I:index.html\n/:' + args.username.encode('ascii') + b':' + result.stdout.strip() + b'\n')
    if bool(args.client_public_key) != bool(args.host_key) or args.generate_ssh_keys and (args.client_public_key or args.host_key):
        raise ValueError('Supply both SSH keys or choose --generate-ssh-keys')
    client = host = owner_private = None
    if args.generate_ssh_keys:
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            raise ValueError('Install python3-cryptography for optional host-side SSH key generation') from None
        owner = Ed25519PrivateKey.generate()
        client = client_key(owner.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH))
        owner_private = owner.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
        server = Ed25519PrivateKey.generate()
        secret = server.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        public = server.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        host = host_key(b'\0\0\0\x0bssh-ed25519\0\0\0\x40' + secret + public)
    elif args.client_public_key:
        client = client_key(regular(args.client_public_key, 1024, False).read_bytes())
        host = host_key(private_input(args.host_key, 83).read_bytes())
    control_key = None
    if getattr(args, 'native_credentials', None):
        files = read_json(kit / 'card' / HTTP / 'manifest.json')['files']
        if not {'bin/yyos-controls', 'COPYING.Controls'} <= set(files):
            raise ValueError('Native controls credentials require the optional controls payload')
        control_key = native_credentials(args.native_credentials)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.yyos-provision-', dir=output.parent) as temporary:
        private_directory(Path(temporary))
        stage = Path(temporary) / 'kit'
        stage.mkdir(mode=0o700)
        private_directory(stage)
        for name in tree(kit):
            write_host_new(stage / name, (kit / name).read_bytes(), bool((kit / name).stat().st_mode & 0o111))
        write_host_new(stage / 'card' / HTTP / 'httpd.conf', config)
        if control_key is not None:
            write_host_new(stage / 'card' / HTTP / 'native-control.key', control_key)
        if client:
            for name, data in (('authorized_keys', client), ('dropbear_ed25519_host_key', host), ('ssh.enabled', b'enabled\n')):
                write_host_new(stage / 'card' / SSH / name, data)
            blob = b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + host[51:]
            write_host_new(stage / 'host-key.pub', b'ssh-ed25519 ' + base64.b64encode(blob) + b'\n')
            write_host_new(stage / 'host-key-fingerprint.txt', b'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).rstrip(b'=') + b'\n')
        if owner_private:
            write_host_new(stage / 'owner_ssh_ed25519', owner_private)
            write_host_new(stage / 'owner_ssh_ed25519.pub', client)
        write_host_new(stage / 'provisioning.json', (json.dumps({'format': FORMAT + '-private', 'web_provisioned': True,
                  'ssh_provisioned': bool(client), 'native_controls_provisioned': control_key is not None,
                  'owner_client_private_key_outside_card': bool(owner_private)}, indent=2) + '\n').encode())
        validate_kit(stage)
        sync_tree(stage)
        output_empty(output)
        if output.exists():
            output.rmdir()
        stage.rename(output)
        sync(output.parent)
    return {'private_output': str(output), 'web_provisioned': True, 'ssh_provisioned': bool(client),
            'native_controls_provisioned': control_key is not None,
            'owner_private_key': str(output / 'owner_ssh_ed25519') if owner_private else None, 'card_changed': False}


def command_json(command):
    result = subprocess.run(command, capture_output=True, timeout=5)
    if result.returncode or len(result.stdout) > 256 * 1024:
        raise ValueError('Host storage metadata could not be verified')
    return json.loads(result.stdout)


def mounted_card(mount, expected_device=None, expected_uuid=None):
    if sys.platform != 'linux':
        raise ValueError('Installation currently requires a Linux host with findmnt and lsblk')
    mount = clean(mount)
    if not mount.is_dir() or mount == Path('/'):
        raise ValueError('An explicit mounted card directory is required')
    mounts = command_json(['findmnt', '--json', '--mountpoint', str(mount), '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS,UUID,MAJ:MIN']).get('filesystems', [])
    if len(mounts) != 1:
        raise ValueError('Require exactly one visible mount at the explicit path')
    found = mounts[0]
    device = found.get('source', '')
    volume = str(found.get('uuid', '')).upper()
    options = str(found.get('options', '')).split(',')
    if (found.get('target') != str(mount) or found.get('fstype') != 'vfat' or 'rw' not in options or 'ro' in options
            or not re.fullmatch(r'/dev/[A-Za-z0-9_/-]+', device) or not re.fullmatch(r'[0-9A-F]{4}-[0-9A-F]{4}', volume)):
        raise ValueError('Require an exact writable VFAT block-device mount with a FAT UUID')
    if expected_device and os.path.realpath(device) != os.path.realpath(expected_device):
        raise ValueError('Mounted device differs from --device')
    if expected_uuid and volume != expected_uuid.upper():
        raise ValueError('Mounted UUID differs from --uuid')
    info = os.stat(device)
    visible = mount.stat().st_dev
    if not stat.S_ISBLK(info.st_mode) or info.st_rdev != visible or found.get('maj:min') != f'{os.major(visible)}:{os.minor(visible)}':
        raise ValueError('Visible filesystem and block-device identity do not match')
    if os.statvfs(mount).f_flag & os.ST_RDONLY:
        raise ValueError('The visible host filesystem is read-only')
    devices = command_json(['lsblk', '--json', '--paths', '--output', 'PATH,TYPE,RM,RO,FSTYPE,UUID,MAJ:MIN,MOUNTPOINTS']).get('blockdevices', [])
    matches = []
    def visit(nodes, parent=None):
        for node in nodes:
            if node.get('path') == device:
                matches.append((node, parent))
            visit(node.get('children', []), node)
    visit(devices)
    if len(matches) != 1:
        raise ValueError('Mounted device is ambiguous in lsblk')
    node, parent = matches[0]
    if (node.get('type') != 'part' or not parent or parent.get('type') != 'disk'
            or parent.get('rm') not in (1, True, '1') or parent.get('ro') not in (0, False, '0')
            or node.get('ro') not in (0, False, '0') or node.get('fstype') != 'vfat'
            or str(node.get('uuid', '')).upper() != volume or node.get('maj:min') != found.get('maj:min')
            or str(mount) not in (node.get('mountpoints') or [])):
        raise ValueError('Require a writable FAT partition on a removable disk; whole-device FAT is unsupported for this profile')
    return {'device': device, 'uuid': volume, 'st_dev': visible, 'mount': str(mount)}


def mount_unchanged(mount, identity):
    clean(mount)
    if mount.stat().st_dev != identity['st_dev'] or os.statvfs(mount).f_flag & os.ST_RDONLY:
        raise ValueError('Card mount changed or became read-only')


def existing_card(mount, kit):
    for path in mount.iterdir():
        name = path.name
        if (name.startswith(('.yyos-install-', '_ht_', 'fac_')) or name in {'yy_debug.ini', 'yy_debug_coredump',
                'recover-native-off.sh', 'hostapd', 'hack.sh', 'yy_update.bin', 'update.tgz'}
                or name.startswith('yy_') and name not in {'yy_telnet_start'}):
            raise ValueError('Conflicting or unfinished boot input: ' + name)
    if (mount / 'diagnostic-archive').exists():
        clean(mount / 'diagnostic-archive')
        if not (mount / 'diagnostic-archive').is_dir():
            raise ValueError('Diagnostic archive path is not a directory')
    root_present = {name for name in ROOT_FILES if (mount / name).exists() or (mount / name).is_symlink()}
    if not root_present:
        if any((mount / name).exists() or (mount / name).is_symlink() for name in (HTTP, SSH)):
            raise ValueError('Existing runtime without a recognized root hook')
        return {'roots': set(), 'runtimes': set(), 'site': {}, 'logs': {}}
    combined = 'yyos-http-boot.sh' in root_present
    expected_roots = ROOT_FILES if combined else ROOT_FILES - {'yyos-http-boot.sh'}
    if root_present != expected_roots and root_present != expected_roots - {'yy_telnet_start'}:
        raise ValueError('Partial or unrecognized existing root payload')
    card = kit / 'card'
    http_boot = mount / ('yyos-http-boot.sh' if combined else 'dump.sh')
    if sha(regular(http_boot)) != sha(card / 'yyos-http-boot.sh'):
        raise ValueError('Existing HTTP boot wrapper is not recognized')
    if combined and sha(regular(mount / 'dump.sh')) != sha(card / 'dump.sh'):
        raise ValueError('Existing combined boot wrapper is not recognized')
    for name in ('telnetd', 'busybox'):
        if sha(regular(mount / name)) != sha(card / name):
            raise ValueError('Existing native launcher or root BusyBox differs; preserve and review it separately')
    expected = expected_roots - {'SHA256SUMS'}
    runtimes = {HTTP, SSH} if combined else {HTTP}
    site = {}; logs = {}
    for name in runtimes:
        public = runtime(mount / name, ssh=name == SSH, allow_site=True)
        expected |= {name + '/' + path for path in public}
        private = ('authorized_keys', 'dropbear_ed25519_host_key', 'ssh.enabled') if name == SSH else ('httpd.conf', 'native-control.key')
        for relative in private:
            path = mount / name / relative
            if path.exists() or path.is_symlink():
                site[name + '/' + relative] = regular(path, 4096).read_bytes()
        log = mount / name / 'startup.log'
        if log.exists() or log.is_symlink():
            logs[name + '/startup.log'] = regular(log, 65536).read_bytes()
    if set(sums(mount, mount / 'SHA256SUMS', absent_marker=True)) != expected:
        raise ValueError('Existing root checksum inventory is not recognized')
    return {'roots': root_present, 'runtimes': runtimes, 'site': site, 'logs': logs}


def site_files(kit, old, replace_web=False):
    result = {}
    for name in SITE:
        path = kit / 'card' / name
        if path.exists() or path.is_symlink():
            result[name] = regular(path, 4096).read_bytes()
    if not replace_web and HTTP + '/httpd.conf' in old['site']:
        result[HTTP + '/httpd.conf'] = old['site'][HTTP + '/httpd.conf']
    if HTTP + '/native-control.key' in old['site']:
        result[HTTP + '/native-control.key'] = old['site'][HTTP + '/native-control.key']
    if HTTP + '/native-control.key' in result:
        native_control_key(result[HTTP + '/native-control.key'])
    if HTTP + '/httpd.conf' not in result:
        raise ValueError('Provision a private web password before the first installation')
    auth_config(result[HTTP + '/httpd.conf'])
    # Existing SSH keys and its enabled/disabled state are kept during upgrades.
    preserve_ssh = any(SSH + '/' + name in old['site'] for name in ('authorized_keys', 'dropbear_ed25519_host_key', 'ssh.enabled'))
    if preserve_ssh:
        for name in (SSH + '/authorized_keys', SSH + '/dropbear_ed25519_host_key', SSH + '/ssh.enabled'):
            if name in old['site']:
                result[name] = old['site'][name]
            else:
                result.pop(name, None)
    auth = result.get(SSH + '/authorized_keys'); host = result.get(SSH + '/dropbear_ed25519_host_key')
    if bool(auth) != bool(host):
        raise ValueError('SSH requires both the owner public key and host key')
    if auth:
        client_key(auth); host_key(host)
    if SSH + '/ssh.enabled' in result and (not auth or result[SSH + '/ssh.enabled'] != b'enabled\n'):
        raise ValueError('Invalid SSH enable marker or missing SSH keys')
    return result


def install(args, perform=True):
    kit, mount = clean(args.kit), clean(args.mount)
    validate_kit(kit)
    identity = mounted_card(mount, args.device, args.uuid)
    old = existing_card(mount, kit)
    private = site_files(kit, old, args.replace_web_auth)
    public = tree(kit / 'card') - SITE
    required = sum((kit / 'card' / name).stat().st_size for name in public) + sum(map(len, private.values())) + 1024 * 1024
    if shutil.disk_usage(mount).free < required:
        raise ValueError('Insufficient free card space for a complete staged copy')
    plan = {'device': identity['device'], 'uuid': identity['uuid'], 'mount': str(mount), 'profile': '3225722 / V14.1.5',
            'public_files': len(public), 'upgrade': bool(old['roots']), 'web_auth': 'existing-preserved' if not args.replace_web_auth and HTTP + '/httpd.conf' in old['site'] else 'provisioned',
            'ssh_enabled': SSH + '/ssh.enabled' in private, 'formatting': False, 'firmware_or_camera_config_written': False}
    plan['native_controls_key'] = ('existing-preserved' if HTTP + '/native-control.key' in old['site'] else
                                   'provisioned' if HTTP + '/native-control.key' in private else 'absent')
    if not perform:
        return {**plan, 'installed': False, 'plan_only': True}
    root_fd = os.open(mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Repeat preflight after obtaining the host-only lock, before any write.
        if mounted_card(mount, args.device, args.uuid) != identity or existing_card(mount, kit) != old:
            raise ValueError('Card changed during preflight')
        token = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:12]
        archive = mount / 'diagnostic-archive' / ('yyos-install-' + token)
        stage = mount / ('.yyos-install-stage-' + token)
        disabled = mount / ('.yyos-install-disabled-' + token)
        marker = mount / 'yy_telnet_start'
        armed = False
        try:
            mount_unchanged(mount, identity)
            if marker.exists():
                marker.rename(disabled)
                sync(mount)
            archive.mkdir(parents=True, mode=0o700)
            sync(archive.parent); sync(mount)
            if disabled.exists():
                disabled.rename(archive / 'yy_telnet_start')
                sync(archive); sync(mount)
            stage.mkdir(mode=0o700)
            for name in sorted(public):
                source = regular(kit / 'card' / name)
                write_new(stage / name, source.read_bytes(), bool(source.stat().st_mode & 0o111))
            for name, data in {**old['logs'], **private}.items():
                write_new(stage / name, data)
            sync_tree(stage)
            sums(stage, stage / 'SHA256SUMS')
            for name, data in private.items():
                if (stage / name).read_bytes() != data:
                    raise ValueError('Private staged-file readback failed')
            mount_unchanged(mount, identity)
            for name in sorted(old['roots'] - {'yy_telnet_start'}):
                (mount / name).rename(archive / name)
            for name in sorted(old['runtimes']):
                (mount / name).rename(archive / name)
            sync(archive); sync(mount)
            for name in sorted((ROOT_FILES - {'yy_telnet_start'}) | {HTTP, SSH}):
                if (mount / name).exists() or (mount / name).is_symlink():
                    raise ValueError('New conflicting card input before commit')
                (stage / name).rename(mount / name)
            sync(mount)
            sums(mount, mount / 'SHA256SUMS', absent_marker=True)
            for name, data in {**old['logs'], **private}.items():
                if regular(mount / name).read_bytes() != data:
                    raise ValueError('Final private/log readback failed')
            if mounted_card(mount, args.device, args.uuid) != identity:
                raise ValueError('Card identity changed before marker activation')
            (stage / 'yy_telnet_start').rename(disabled)
            stage.rmdir()
            sync(mount)
            disabled.rename(marker)
            armed = True
            sync(mount)
            return {**plan, 'installed': True, 'archive': str(archive.relative_to(mount)), 'normal_marker_enabled_last': True}
        except BaseException:
            if armed and marker.exists():
                marker.rename(archive / 'incomplete-normal-marker')
                sync(archive); sync(mount)
            raise
    finally:
        os.close(root_fd)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    private = commands.add_parser('provision', help='create a separate private host kit; no card access')
    private.add_argument('--kit', type=Path, required=True)
    private.add_argument('--output', type=Path, required=True)
    private.add_argument('--password-file', type=Path, help='private password line; otherwise prompt without echo')
    private.add_argument('--username', default='admin')
    private.add_argument('--client-public-key', type=Path)
    private.add_argument('--host-key', type=Path)
    private.add_argument('--generate-ssh-keys', action='store_true', help='optional python3-cryptography; client private key stays outside card/')
    private.add_argument('--native-credentials', type=Path,
                         help='optional private exact-profile Tuya credentials JSON for controls; never copied wholesale')
    for name in ('plan', 'install'):
        command = commands.add_parser(name, help='validate only' if name == 'plan' else 'write the already mounted removable FAT card')
        command.add_argument('--kit', type=Path, required=True)
        command.add_argument('--mount', type=Path, required=True)
        command.add_argument('--device', help='optional exact expected block device')
        command.add_argument('--uuid', help='optional exact expected FAT UUID')
        command.add_argument('--replace-web-auth', action='store_true', help='explicitly use provisioned web authentication instead of preserving existing authentication')
    args = parser.parse_args()
    try:
        result = provision(args) if args.command == 'provision' else install(args, perform=args.command == 'install')
    except (OSError, ValueError, KeyError, UnicodeError, subprocess.SubprocessError) as error:
        parser.exit(1, 'YYOS ' + args.command + ' refused or failed: ' + str(error) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
