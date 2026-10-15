#!/usr/bin/env python3
"""Recovery fixtures contain only synthetic regular files; never use a camera."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = (REPO / 'tools/yyos/recover-native-off.sh').read_text()
HOST_BB = shutil.which(os.environ.get('HOST_BUSYBOX', 'busybox'))
QEMU = shutil.which(os.environ.get('BACKUP_QEMU', 'qemu-arm')) or str(REPO / '.local/tools/root/usr/bin/qemu-arm')
ARM_BB = os.environ.get('BACKUP_ARM_BUSYBOX', str(REPO / 'SOURCE/build/mmcblk0p2/HACK/bin/busybox'))
ORIGINAL = (b'# synthetic private fixture\n[dp]\nsiren_onoff=0\n'
            b'[rtsp]\nrtsp_password = SyntheticPass123!#unchanged\nrtsp_on_off \t= 1 ; keep\n'
            b'[onvif]\nonvif_password=SyntheticSecondPass123\nonvif_on_off=1\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(case, arm=False):
    with tempfile.TemporaryDirectory(prefix='yyos-recovery-') as directory:
        root = Path(directory)
        fs, proc, sysfs, dev = (root / name for name in ('rootfs', 'proc', 'sys', 'dev'))
        sd, config = fs / 'mnt/sdcard', fs / 'config'
        for path in (sd, config, proc, sysfs / 'class/mtd/mtd4', dev, fs / 'appfs/bin',
                     fs / 'appfs/script', fs / 'appfs/lib', fs / 'bin', fs / 'tmp'):
            path.mkdir(parents=True, exist_ok=True)
        (proc / 'cpuinfo').write_text('Processor\t: ARM926EJ-S rev5\nHardware\t: AK3918AV130\n')
        (proc / 'uptime').symlink_to('/proc/uptime')
        for name in ('meminfo',):
            (proc / name).write_text('synthetic bounded diagnostic\n')
        (dev / 'mmcblk0p1').write_bytes(b'NOT-A-BLOCK-DEVICE; never read')
        (dev / 'mtdblock4').write_bytes(b'NOT-A-FLASH-DEVICE; never read')
        (proc / 'mounts').write_text(f'{dev}/mmcblk0p1 {sd} vfat rw 0 0\n{dev}/mtdblock4 {config} jffs2 rw 0 0\n')
        for key, value in {'type': 'nor', 'size': '262144', 'erasesize': '4096',
                           'writesize': '256', 'oobsize': '0', 'offset': '7995392'}.items():
            (sysfs / 'class/mtd/mtd4' / key).write_text(value + '\n')
        app = fs / 'appfs/bin/yy_cam'
        app.write_bytes(b'SYNTHETIC-EXACT-PROFILE-APP; never execute')
        init = fs / 'appfs/script/init.sh'
        init.write_text('# synthetic init; never execute\n')
        calls, environment, descriptors, child = (root / name for name in ('stock-calls', 'stock-env', 'stock-fds', 'child-fd'))
        readlink = shutil.which('readlink')
        stock = fs / 'appfs/script/start.sh'
        stock.write_text('#!/bin/sh\nprintf "start\\n" >> ' + shlex.quote(str(calls)) + '\n'
                         + 'printf "%s\\n%s\\n%s\\n" "$PATH" "$LD_LIBRARY_PATH" "${LD_PRELOAD-unset}" > ' + shlex.quote(str(environment)) + '\n'
                         + 'for fd in 0 1 2; do value=$(' + shlex.quote(readlink) + ' "/proc/$$/fd/$fd"); printf "%s\\n" "$value" >> ' + shlex.quote(str(descriptors)) + '; done\n'
                         + '/bin/sh -c ' + shlex.quote('fd=$(' + shlex.quote(readlink) + ' /proc/$$/fd/1); printf "%s\\n" "$fd" > ' + shlex.quote(str(child)) + '; printf "CHILD-DIAGNOSTIC-MUST-NOT-LEAK\\n"') + ' &\n'
                         + ('exit 7\n' if case == 'stock-fails' else 'exit 0\n'))
        (fs / 'bin/sh').write_text('#!/bin/sh\nexec ' + shlex.quote(HOST_BB) + ' ash "$@"\n')
        (fs / 'bin/sh').chmod(0o755)
        target = config / 'param.conf'
        target.write_bytes(ORIGINAL)
        target.chmod(0o640)
        (sd / 'yy_debug.ini').write_text(f'mode=debug\nstart_sh={sd}/telnetd\n')
        source = SOURCE
        for name, value in [('PROC', proc), ('SYS', sysfs), ('DEV', dev), ('FS_ROOT', fs)]:
            original = name + '=' + {'PROC': '/proc', 'SYS': '/sys', 'DEV': '/dev', 'FS_ROOT': ''}[name] + '\n'
            self_count = source.count(original)
            if self_count != 1:
                raise AssertionError((name, self_count))
            source = source.replace(original, name + '=' + str(value) + '\n', 1)
        for name, path in [('APP_SHA', app), ('START_SHA', stock), ('INIT_SHA', init)]:
            value = next(line.split('=', 1)[1] for line in source.splitlines() if line.startswith(name + '='))
            source = source.replace(name + '=' + value, name + '=' + digest(path), 1)
        original_block = '[ -b "$source" ] || continue # FIXTURE_BLOCK_CHECK'
        if source.count(original_block) != 1:
            raise AssertionError('Missing isolated block fixture seam')
        source = source.replace(original_block, '[ -f "$source" ] || continue # FIXTURE_BLOCK_CHECK', 1)
        if case == 'cpu':
            (proc / 'cpuinfo').write_text('Hardware: DIFFERENT_SOC\n')
        if case == 'hash':
            app.write_bytes(b'DIFFERENT-BINARY; never execute')
        if case == 'stock-script-hash':
            stock.write_text(stock.read_text() + '# altered after profile capture\n')
        if case == 'geometry':
            (sysfs / 'class/mtd/mtd4/size').write_text('8192\n')
        if case == 'config-ro':
            (proc / 'mounts').write_text((proc / 'mounts').read_text().replace('jffs2 rw', 'jffs2 ro'))
        if case == 'config-source':
            (proc / 'mounts').write_text((proc / 'mounts').read_text().replace('/mtdblock4 ', '/mtdblock3 '))
        if case == 'stacked':
            (proc / 'mounts').write_text(f'tmpfs {sd} tmpfs rw 0 0\ntmpfs {config} tmpfs rw 0 0\n' + (proc / 'mounts').read_text())
        if case == 'sd-ro':
            (proc / 'mounts').write_text((proc / 'mounts').read_text().replace('vfat rw', 'vfat ro'))
        if case == 'normal-hook':
            (sd / 'yy_telnet_start').touch()
        if case == 'debug-entry':
            (sd / 'yy_debug.ini').write_text(f'mode=normal\nstart_sh={sd}/telnetd\n')
        if case == 'lock-held':
            (fs / 'tmp/lscamoflash-yyos-native-recovery.lock').mkdir()
        if case in ('temp-collision', 'temp-symlink'):
            source = source.replace('TEMP=$CONFIG_ROOT/.param.conf.native-off-$$',
                                    'TEMP=$CONFIG_ROOT/.param.conf.native-off-fixture')
            temporary = config / '.param.conf.native-off-fixture'
            if case == 'temp-collision':
                temporary.write_bytes(b'DO-NOT-REPLACE')
            else:
                temporary.symlink_to(root / 'missing-target')
        if case == 'deadline':
            source = source.replace('mount_checked "$SD" sd || die sd_mount',
                                    'START_UPTIME=$((START_UPTIME - 241))\nmount_checked "$SD" sd || die sd_mount', 1)
        if case == 'hash-timeout':
            source = source.replace('*) "$BB" timeout -k 2 20 "$BB" "$@";;',
                                    '*) "$BB" timeout -k 2 1 "$BB" "$@";;', 1)
        if case in ('running-camera', 'running-exe'):
            process = proc / '123'
            process.mkdir()
            (process / 'comm').write_text('yy_cam\n' if case == 'running-camera' else 'other\n')
            if case == 'running-exe':
                (process / 'exe').symlink_to(app)
        if case == 'symlink':
            outside = root / 'outside-private'
            target.rename(outside)
            target.symlink_to(outside)
        if case == 'root-symlink':
            outside = root / 'outside-config'
            config.rename(outside)
            config.symlink_to(outside, target_is_directory=True)
        if case == 'already-off':
            target.write_bytes(ORIGINAL.replace(b'= 1 ; keep', b'= 0 ; keep').replace(b'onvif_on_off=1', b'onvif_on_off=0'))
        if case == 'absent':
            target.write_bytes(b'[dp]\nsiren_onoff=0\n')
        if case == 'single':
            target.write_bytes(ORIGINAL.replace(b'onvif_on_off=1', b'onvif_on_off=0'))
        if case == 'other-flag-absent':
            target.write_bytes(ORIGINAL.replace(b'onvif_on_off=1\n', b''))
        if case == 'crlf-no-final-newline':
            target.write_bytes(ORIGINAL.replace(b'\n', b'\r\n')[:-2])
        if case == 'duplicate':
            target.write_bytes(ORIGINAL + b'ONVIF_ON_OFF=1\n')
        if case == 'duplicate-section':
            target.write_bytes(ORIGINAL + b'[RTSP]\nother=kept\n')
        if case == 'duplicate-other-key':
            target.write_bytes(ORIGINAL.replace(b'siren_onoff=0\n', b'siren_onoff=0\nSIREN_ONOFF=1\n'))
        if case == 'malformed':
            target.write_bytes(ORIGINAL + b'not an INI assignment\n')
        if case == 'bad-value':
            target.write_bytes(ORIGINAL.replace(b'onvif_on_off=1', b'onvif_on_off=01'))
        if case == 'nul':
            target.write_bytes(ORIGINAL + b'\0')
        if case == 'oversized':
            target.write_bytes(ORIGINAL + b'#' * 65536)
        before = target.read_bytes()
        mode_before = stat.S_IMODE(target.stat().st_mode)
        driver_before = {p.name: p.read_bytes() for p in dev.iterdir()}
        script = root / 'recover.sh'
        script.write_text(source)
        prefix = (shlex.quote(QEMU) + ' -cpu arm926 ' + shlex.quote(ARM_BB)) if arm else shlex.quote(HOST_BB)
        shim = '#!/bin/sh\n'
        shim += 'if [ "$1" = id ] && [ "$2" = -u ]; then echo 0; exit 0; fi\n'
        shim += 'if [ "$1" = dmesg ]; then echo SYNTHETIC-KERNEL; exit 0; fi\n'
        shim += 'if [ "$1" = chown ]; then exit 0; fi\n'
        shim += f'if [ "$1 $2 $3 $4 $5" = "stat -f -c %t {fs}/tmp" ]; then echo 1021994; exit 0; fi\n'
        for path, number, magic in [(sd, os.makedev(179, 1), '4d44'), (config, os.makedev(31, 4), '72b6')]:
            shim += f'if [ "$1 $2 $3 $4" = "stat -c %d {path}" ]; then echo {number}; exit 0; fi\n'
            shim += f'if [ "$1 $2 $3 $4 $5" = "stat -f -c %t {path}" ]; then echo {magic}; exit 0; fi\n'
        for path, number in [(dev / 'mmcblk0p1', 'b3:1'), (dev / 'mtdblock4', '1f:4')]:
            shim += f'if [ "$1 $2 $3 $4" = "stat -c %t:%T {path}" ]; then echo {number}; exit 0; fi\n'
        shim += f'if [ "$1" = stat ] && [ "$3" = "%a %u %g %s" ] && [ "$4" = "{target}" ]; then set -- $({prefix} stat -c "%a %s" "{target}"); echo "$1 0 0 $2"; exit 0; fi\n'
        if case == 'sync-fails':
            shim += 'if [ "$1" = sync ]; then case "$2" in */.param.conf.native-off-*) exit 9;; esac; fi\n'
        if case == 'rename-fails':
            shim += 'if [ "$1" = mv ]; then exit 9; fi\n'
        if case == 'copy-fails':
            shim += 'if [ "$1" = cat ]; then case "$2" in */off-param.conf) exit 9;; esac; fi\n'
        if case == 'hash-timeout':
            shim += f'if [ "$1" = sha256sum ] && [ "$2" = "{app}" ]; then exec /bin/sleep 30; fi\n'
        if case == 'changed-before-rename':
            shim += 'if [ "$1" = cat ]; then case "$2" in */off-param.conf) /bin/printf "# raced\\n" >> ' + shlex.quote(str(target)) + ';; esac; fi\n'
        shim += 'exec ' + prefix + ' "$@"\n'
        (sd / 'busybox').write_text(shim)
        (sd / 'busybox').chmod(0o755)
        command = ([QEMU, '-cpu', 'arm926', ARM_BB, 'ash'] if arm else [HOST_BB, 'ash']) + [str(script), str(sd)]
        started = time.monotonic()
        result = subprocess.run(command, capture_output=True, text=True, timeout=40, env={'PATH': '/usr/bin:/bin', 'LD_PRELOAD': ''})
        duration = time.monotonic() - started
        runs = list((sd / 'native-recovery').glob('run-*')) if (sd / 'native-recovery').exists() else []
        run = runs[0] if runs else None
        log = (run / 'recovery.log').read_text() if run else ''
        status = (run / 'status.txt').read_text() if run else ''
        success = case in ('ok', 'single', 'other-flag-absent', 'stacked', 'crlf-no-final-newline')
        hold = case in ('already-off', 'absent')
        if success:
            expected = before.replace(b'= 1 ; keep', b'= 0 ; keep').replace(b'onvif_on_off=1', b'onvif_on_off=0')
            assert result.returncode == 0, (case, result.returncode, log, result.stderr)
            assert target.read_bytes() == expected
            assert (run / 'original-param.conf').read_bytes() == before
            assert (run / 'off-param.conf').read_bytes() == expected
            assert stat.S_IMODE(target.stat().st_mode) == mode_before
            assert 'config_modified=1' in status and 'stock_launch_attempts=1' in status
            plan = (run / 'plan.txt').read_text()
            assert 'rtsp_prior=1' in plan
            assert 'onvif_prior=' + ('missing_default0' if case == 'other-flag-absent' else '0' if case == 'single' else '1') in plan
            assert calls.read_text() == 'start\n'
            assert environment.read_text().splitlines() == [f'{fs}/appfs/bin:{fs}/bin:{fs}/sbin:{fs}/usr/bin:{fs}/usr/sbin', f'{fs}/appfs/lib', 'unset']
            assert descriptors.read_text().splitlines() == ['/dev/null'] * 3
            for _ in range(50):
                if child.exists(): break
                time.sleep(0.01)
            assert child.read_text().strip() == '/dev/null'
            assert 'CHILD-DIAGNOSTIC' not in log + result.stdout + result.stderr
            second = subprocess.run(command, capture_output=True, text=True, timeout=10,
                                    env={'PATH': '/usr/bin:/bin'})
            assert second.returncode == 1 and calls.read_text() == 'start\n'
            assert len(list((sd / 'native-recovery').glob('run-*'))) == 1
        elif case == 'stock-fails':
            assert result.returncode != 0 and 'config_modified=1' in status
            assert calls.read_text() == 'start\n' and (run / 'stock-start-exit.txt').read_text() == '7\n'
        else:
            assert result.returncode == (3 if hold else 1), (case, result.returncode, log, result.stderr)
            expected = before + b'# raced\n' if case == 'changed-before-rename' else before
            assert target.read_bytes() == expected, (case, 'configuration overwritten')
            assert not calls.exists(), (case, 'stock launched on failure')
            if hold:
                assert 'ALREADY_OFF_HOLD_DEBUG' in status and (run / 'original-param.conf').read_bytes() == before
                assert 'config_modified=0' in status and 'stock_launch_attempts=0' in status
            if case == 'hash-timeout':
                assert duration < 8, ('Timeout did not bound the hung reader', duration)
        assert (sd / 'yy_debug.ini').exists()
        assert driver_before == {p.name: p.read_bytes() for p in dev.iterdir()}
        if case == 'temp-collision':
            assert (config / '.param.conf.native-off-fixture').read_bytes() == b'DO-NOT-REPLACE'
        elif case == 'temp-symlink':
            assert (config / '.param.conf.native-off-fixture').is_symlink()
        else:
            assert not list(config.glob('.param.conf.native-off-*'))
        assert 'SyntheticPass' not in result.stdout + result.stderr


class RecoveryTests(unittest.TestCase):
    pass


HOST_CASES = ['ok', 'single', 'other-flag-absent', 'stacked', 'crlf-no-final-newline', 'already-off', 'absent',
              'cpu', 'hash', 'stock-script-hash', 'geometry', 'config-ro', 'config-source',
              'sd-ro', 'normal-hook', 'debug-entry', 'lock-held', 'running-camera', 'running-exe', 'symlink',
              'root-symlink', 'duplicate', 'duplicate-section', 'duplicate-other-key', 'malformed',
              'bad-value', 'nul', 'oversized', 'sync-fails', 'rename-fails', 'copy-fails',
              'changed-before-rename', 'stock-fails', 'temp-collision', 'temp-symlink', 'deadline', 'hash-timeout']
ARM_CASES = ['ok', 'crlf-no-final-newline', 'already-off', 'running-camera', 'duplicate', 'sync-fails', 'rename-fails', 'hash-timeout']


def add_case(case, arm):
    def test(self):
        if not HOST_BB or (arm and not (Path(QEMU).is_file() and Path(ARM_BB).is_file())):
            self.skipTest('Required BusyBox/QEMU fixture executables unavailable')
        fixture(case, arm)
    setattr(RecoveryTests, 'test_' + ('arm_' if arm else 'host_') + case.replace('-', '_'), test)


for case in HOST_CASES:
    add_case(case, False)
for case in ARM_CASES:
    add_case(case, True)

if __name__ == '__main__':
    unittest.main()
