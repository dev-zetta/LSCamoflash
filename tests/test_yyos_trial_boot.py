#!/usr/bin/env python3
"""Synthetic host/ARM fixtures: no real block devices or recovered execution."""
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
WRAPPER = (REPO / 'tools/yyos/trial-boot.sh').read_text()
RECOVERY_PATH = REPO / 'tools/yyos/recover-native-off.sh'
RECOVERY = RECOVERY_PATH.read_text()
RECOVERY_SHA = '9ee6fc266514ce90f96ec2453211d754c7dae2fd51ab5e8b78af19de3c8380fb'
HOST_BB = shutil.which(os.environ.get('HOST_BUSYBOX', 'busybox'))
QEMU = shutil.which(os.environ.get('BACKUP_QEMU', 'qemu-arm')) or str(REPO / '.local/tools/root/usr/bin/qemu-arm')
ARM_BB = os.environ.get('BACKUP_ARM_BUSYBOX', str(REPO / 'SOURCE/build/mmcblk0p2/HACK/bin/busybox'))
OFF = b'[dp]\nsiren_onoff=0\n[rtsp]\nrtsp_password=Synthetic123\nrtsp_on_off=0\n[onvif]\nonvif_password=Synthetic123\nonvif_on_off=0\n'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_one(source, before, after):
    if source.count(before) != 1:
        raise AssertionError(('fixture replacement must match once', before))
    return source.replace(before, after, 1)


def fixture(case, arm=False):
    with tempfile.TemporaryDirectory(prefix='yyos-trial-') as directory:
        root = Path(directory)
        fs, proc, sysfs, dev = [root / n for n in ('rootfs', 'proc', 'sys', 'dev')]
        sd, config, ram = fs / 'mnt/sdcard', fs / 'config', fs / 'tmp'
        for path in (sd, config, ram, proc, sysfs / 'class/mtd/mtd4', dev,
                     fs / 'appfs/bin', fs / 'appfs/lib', fs / 'appfs/script', fs / 'bin'):
            path.mkdir(parents=True, exist_ok=True)
        (proc / 'cpuinfo').write_text('Hardware\t: AK3918AV130\n')
        (proc / 'uptime').symlink_to('/proc/uptime')
        (proc / 'meminfo').write_text('MemTotal: 38112 kB\n')
        mounts = proc / 'mounts'
        mounts.write_text(f'{dev}/mmcblk0p1 {sd} vfat rw 0 0\n{dev}/mtdblock4 {config} jffs2 rw 0 0\n')
        for name in ('mmcblk0p1', 'mtdblock4'):
            (dev / name).write_bytes(b'SYNTHETIC-REGULAR-DEVICE; never read or write')
        for key, value in {'type': 'nor', 'size': '262144', 'erasesize': '4096',
                           'writesize': '256', 'oobsize': '0', 'offset': '7995392'}.items():
            (sysfs / 'class/mtd/mtd4' / key).write_text(value + '\n')
        app, init, stock = [fs / p for p in ('appfs/bin/yy_cam', 'appfs/script/init.sh', 'appfs/script/start.sh')]
        app.write_bytes(b'SYNTHETIC-APPLICATION; never execute')
        init.write_text('# SYNTHETIC-INIT; never execute\n')
        calls, envfile, fds, child, http_calls = [root / p for p in ('calls', 'environment', 'fds', 'child', 'http-calls')]
        readlink = shlex.quote(shutil.which('readlink'))
        stock.write_text('#!/bin/sh\n'
                         + 'printf "start\\n" >> ' + shlex.quote(str(calls)) + '\n'
                         + 'printf "%s\\n%s\\n%s\\n" "$PATH" "$LD_LIBRARY_PATH" "${LD_PRELOAD-unset}" > ' + shlex.quote(str(envfile)) + '\n'
                         + 'for n in 0 1 2; do value=$(' + readlink + ' /proc/$$/fd/$n); printf "%s\\n" "$value" >> ' + shlex.quote(str(fds)) + '; done\n'
                         + '/bin/sh -c ' + shlex.quote('value=$(' + readlink + ' /proc/$$/fd/1); printf "%s\\n" "$value" > ' + shlex.quote(str(child)) + '; echo NEVER-LEAK-CHILD-OUTPUT') + ' &\n'
                         + ('exit 7\n' if case == 'stock-fails' else 'exit 0\n'))
        (fs / 'bin/sh').write_text('#!/bin/sh\nexec ' + shlex.quote(HOST_BB) + ' ash "$@"\n')
        (fs / 'bin/sh').chmod(0o755)
        target = config / 'param.conf'
        initial = OFF.replace(b'_on_off=0', b'_on_off=1') if case == 'recovery-starts' else OFF
        if case == 'missing-flags':
            initial = b'[dp]\nsiren_onoff=0\n'
        target.write_bytes(initial)
        target.chmod(0o640)
        debug = sd / 'yy_debug.ini'
        debug.write_text(f'mode=debug\nstart_sh={sd}/telnetd\n')

        # Only copies of public scripts get fixed fixture path/profile/device
        # substitutions. Production has no runtime fixture option or env gate.
        def adapt(source):
            for key, value in [('PROC', proc), ('SYS', sysfs), ('DEV', dev), ('FS_ROOT', fs)]:
                old = key + '=' + {'PROC': '/proc', 'SYS': '/sys', 'DEV': '/dev', 'FS_ROOT': ''}[key] + '\n'
                source = replace_one(source, old, key + '=' + str(value) + '\n')
            for key, path in [('APP_SHA', app), ('INIT_SHA', init), ('START_SHA', stock)]:
                old = next(line for line in source.splitlines() if line.startswith(key + '='))
                source = replace_one(source, old + '\n', key + '=' + sha(path) + '\n')
            return replace_one(source, '[ -b "$source" ] || continue # FIXTURE_BLOCK_CHECK',
                               '[ -f "$source" ] || continue # FIXTURE_BLOCK_CHECK')

        engine = adapt(RECOVERY)
        source = adapt(WRAPPER)
        prior_files = {}
        if case in ('prior-pid-collision', 'prior-pid-exhausted'):
            # Model a reboot reusing PID5000. This constant identity exists
            # only in fixture copies; ordinary cases verify the real child PID.
            engine = engine.replace('$$', '5000')
            source = replace_one(source, 'wait "$CHILD" || result=$?',
                                 'wait "$CHILD" || result=$?\nCHILD=5000')
            for index in range(32 if case == 'prior-pid-exhausted' else 1):
                prior = sd / f'native-recovery/run-5000-{index}'
                prior.mkdir(parents=True)
                for name, contents in [('status.txt', b'OLD-FAILED-RECOVERY\n'),
                                       ('original-param.conf', b'DIFFERENT-OLD-PRIVATE-CONFIG\n')]:
                    path = prior / name
                    path.write_bytes(contents)
                    prior_files[path] = sha(path)
        mutations = {
            'foreign-owner': 'printf "1\\n" > "$LOCK/owner-pid"',
            'bad-status': 'printf "CONFIG_OFF_STOCK_START_RETURNED\\n" > "$RUN/status.txt"',
            'bad-plan': 'printf "enabled_values=1\\nrtsp_prior=1\\nonvif_prior=0\\n" > "$RUN/plan.txt"',
            'changed-config': 'printf "# raced\\n" >> "$CONFIG"',
            'changed-backup': 'printf "# raced\\n" >> "$RUN/original-param.conf"',
            'bad-metadata': 'printf "extra=value\\n" >> "$RUN/original-metadata.txt"',
            'duplicate-run': '"$BB" cp -a "$RUN" "$BASE/run-$$-31"',
            'late-camera': '"$BB" mkdir "$PROC/123"; printf "yy_cam\\n" > "$PROC/123/comm"',
            'late-cpu': 'printf "Hardware: WRONG_SOC\\n" > "$PROC/cpuinfo"',
            'late-app': 'printf "CHANGED-APP\\n" >> "$FS_ROOT/appfs/bin/yy_cam"',
            'late-start': 'printf "# CHANGED-START\\n" >> "$FS_ROOT/appfs/script/start.sh"',
            'late-marker': ': > "$SD/yy_telnet_start"',
            'late-debug': 'printf "mode=normal\\n" > "$SD/yy_debug.ini"',
            'late-readonly': '"$BB" sed -i "s/jffs2 rw/jffs2 ro/" "$PROC/mounts"',
            'backup-symlink': '"$BB" mv "$RUN/original-param.conf" "$SD/other-copy"; "${BB}" ln -s "$SD/other-copy" "$RUN/original-param.conf"',
        }
        if case in mutations:
            engine = replace_one(engine, 'enabled_values=0) status ALREADY_OFF_HOLD_DEBUG; COMPLETE=1; exit 3;;',
                                 'enabled_values=0) status ALREADY_OFF_HOLD_DEBUG; ' + mutations[case] + '; COMPLETE=1; exit 3;;')
        if case == 'engine-timeout':
            engine = '#!/bin/sh\nexec "$1/busybox" sleep 30\n'
            source = replace_one(source, 'timeout -k 2 350', 'timeout -k 1 1')
        recovery = sd / 'recover-native-off.sh'
        recovery.write_text(engine)
        source = replace_one(source, 'RECOVERY_SHA=' + RECOVERY_SHA, 'RECOVERY_SHA=' + sha(recovery))
        if case == 'companion-hash':
            recovery.write_text(engine + '\n# changed after expected hash\n')
        if case == 'companion-symlink':
            outside = root / 'engine-outside'
            recovery.rename(outside)
            recovery.symlink_to(outside)
        if case == 'trial-lock':
            (ram / 'lscamoflash-yyos-trial-boot.lock').mkdir()
        if case == 'untrusted-sd':
            mounts.write_text(mounts.read_text().replace('vfat rw', 'vfat ro'))
        if case == 'engine-fails':
            (proc / 'cpuinfo').write_text('Hardware: WRONG_SOC\n')
        if case == 'http-optional':
            http = sd / 'LSCamoflash-yyos/start.sh'
            http.parent.mkdir()
            http.write_text('#!/bin/sh\nprintf "http\\n" > ' + shlex.quote(str(http_calls)) + '\nexit 7\n')

        prefix = (shlex.quote(QEMU) + ' -cpu arm926 ' + shlex.quote(ARM_BB)) if arm else shlex.quote(HOST_BB)
        shim = '#!/bin/sh\n'
        shim += 'if [ "$1 $2" = "id -u" ]; then echo 0; exit 0; fi\n'
        shim += 'if [ "$1" = dmesg ]; then echo SYNTHETIC; exit 0; fi\n'
        shim += 'if [ "$1" = chown ]; then exit 0; fi\n'
        shim += f'if [ "$1 $2 $3 $4 $5" = "stat -f -c %t {ram}" ]; then echo 1021994; exit 0; fi\n'
        for path, number, magic in [(sd, os.makedev(179, 1), '4d44'), (config, os.makedev(31, 4), '72b6')]:
            shim += f'if [ "$1 $2 $3 $4" = "stat -c %d {path}" ]; then echo {number}; exit 0; fi\n'
            shim += f'if [ "$1 $2 $3 $4 $5" = "stat -f -c %t {path}" ]; then echo {magic}; exit 0; fi\n'
        for path, pair in [(dev / 'mmcblk0p1', 'b3:1'), (dev / 'mtdblock4', '1f:4')]:
            shim += f'if [ "$1 $2 $3 $4" = "stat -c %t:%T {path}" ]; then echo {pair}; exit 0; fi\n'
        shim += f'if [ "$1" = stat ] && [ "$3" = "%a %u %g %s" ] && [ "$4" = "{target}" ]; then set -- $({prefix} stat -c "%a %s" "{target}"); echo "$1 0 0 $2"; exit 0; fi\n'
        shim += 'exec ' + prefix + ' "$@"\n'
        (sd / 'busybox').write_text(shim)
        (sd / 'busybox').chmod(0o755)
        script = root / 'trial.sh'
        script.write_text(source)
        before_devices = {p.name: p.read_bytes() for p in dev.iterdir()}
        before_mode = stat.S_IMODE(target.stat().st_mode)
        before_file_identity = (target.stat().st_ino, target.stat().st_mtime_ns)
        command = ([QEMU, '-cpu', 'arm926', ARM_BB, 'ash'] if arm else [HOST_BB, 'ash']) + [str(script), str(sd)]
        started = time.monotonic()
        result = subprocess.run(command, capture_output=True, text=True, timeout=35,
                                env={'PATH': '/usr/bin:/bin', 'LD_PRELOAD': ''})
        elapsed = time.monotonic() - started
        runs = list((sd / 'trial-boot').glob('run-*')) if (sd / 'trial-boot').exists() else []
        status_text = (runs[0] / 'status.txt').read_text() if runs else ''
        log = (runs[0] / 'trial-boot.log').read_text() if runs else ''
        success = case in ('already-off', 'missing-flags', 'recovery-starts', 'http-optional', 'prior-pid-collision')
        assert result.returncode == (0 if success else 1), (case, result.returncode, result.stderr, log)
        if success or case == 'stock-fails':
            assert calls.read_text() == 'start\n', (case, 'must launch exactly once')
            assert envfile.read_text().splitlines() == [f'{fs}/appfs/bin:{fs}/bin:{fs}/sbin:{fs}/usr/bin:{fs}/usr/sbin', str(fs / 'appfs/lib'), 'unset']
            assert fds.read_text().splitlines() == ['/dev/null'] * 3
            for _ in range(50):
                if child.exists():
                    break
                time.sleep(0.01)
            assert child.read_text().strip() == '/dev/null'
            assert 'NEVER-LEAK-CHILD' not in log + result.stdout + result.stderr
            if case == 'recovery-starts':
                assert 'RECOVERY_OFF_STOCK_START_RETURNED' in status_text
                assert 'wrapper_stock_launch_attempts=0' in status_text
                assert target.read_bytes() == OFF
            else:
                assert target.read_bytes() == initial
                assert 'wrapper_stock_launch_attempts=1' in status_text
            second = subprocess.run(command, capture_output=True, text=True, timeout=10,
                                    env={'PATH': '/usr/bin:/bin'})
            assert second.returncode == 1 and calls.read_text() == 'start\n'
            assert len(list((sd / 'trial-boot').glob('run-*'))) == 1
        else:
            assert not calls.exists(), (case, 'stock launched on refused fallback')
            expected = initial + b'# raced\n' if case == 'changed-config' else initial
            assert target.read_bytes() == expected
        if case in ('already-off', 'missing-flags', 'http-optional', 'prior-pid-collision'):
            assert 'ALREADY_OFF_STOCK_START_RETURNED' in status_text
            child_pid = next(line.split('=', 1)[1] for line in status_text.splitlines() if line.startswith('recovery_child_pid='))
            assert (ram / 'lscamoflash-yyos-native-recovery.lock/owner-pid').read_text().strip() == child_pid
        for path, expected in prior_files.items():
            assert sha(path) == expected, ('Old recovery evidence changed', path.name)
        if case == 'prior-pid-collision':
            assert (runs[0] / 'recovery-run.txt').read_text().strip().endswith('/run-5000-1')
            assert 'run-5000-0' in (runs[0] / 'prior-recovery-runs.txt').read_text()
        if case == 'http-optional':
            assert http_calls.read_text() == 'http\n'
        if case == 'engine-timeout':
            assert elapsed < 8 and 'HELD:recovery_failed' in status_text
        assert before_devices == {p.name: p.read_bytes() for p in dev.iterdir()}
        assert stat.S_IMODE(target.stat().st_mode) == before_mode
        if case not in ('recovery-starts', 'changed-config'):
            assert (target.stat().st_ino, target.stat().st_mtime_ns) == before_file_identity
        assert not list(config.glob('.param.conf.native-off-*'))
        assert debug.exists()
        assert 'Synthetic123' not in result.stdout + result.stderr


class TrialBootTests(unittest.TestCase):
    def test_recovery_historical_source_unchanged(self):
        self.assertEqual(sha(RECOVERY_PATH), RECOVERY_SHA)


HOST_CASES = ['already-off', 'missing-flags', 'recovery-starts', 'http-optional', 'stock-fails',
              'prior-pid-collision', 'prior-pid-exhausted',
              'companion-hash', 'companion-symlink', 'trial-lock', 'untrusted-sd', 'engine-fails',
              'foreign-owner', 'bad-status', 'bad-plan', 'changed-config', 'changed-backup',
              'bad-metadata', 'duplicate-run', 'late-camera', 'late-cpu', 'late-app', 'late-start',
              'late-marker', 'late-debug', 'late-readonly', 'backup-symlink', 'engine-timeout']
ARM_CASES = ['already-off', 'recovery-starts', 'foreign-owner', 'changed-config', 'late-camera', 'engine-timeout', 'prior-pid-collision']


def add_case(case, arm):
    def test(self):
        if not HOST_BB or (arm and not (Path(QEMU).is_file() and Path(ARM_BB).is_file())):
            self.skipTest('Required BusyBox/QEMU fixture executables unavailable')
        fixture(case, arm)
    setattr(TrialBootTests, 'test_' + ('arm_' if arm else 'host_') + case.replace('-', '_'), test)


for case in HOST_CASES:
    add_case(case, False)
for case in ARM_CASES:
    add_case(case, True)


if __name__ == '__main__':
    unittest.main()
