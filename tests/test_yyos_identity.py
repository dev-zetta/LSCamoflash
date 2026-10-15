"""Identity collection uses synthetic proc/sys/filesystems, never camera devices."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "tools/firmware-backup/collect-yyos-identity.sh").read_text()
HOST_BB = shutil.which(os.environ.get("HOST_BUSYBOX", "busybox"))
ARM_BB = os.environ.get("BACKUP_ARM_BUSYBOX")
QEMU = os.environ.get("BACKUP_QEMU")


def fixture(case, arm):
    with tempfile.TemporaryDirectory(prefix="yyos-identity-") as temporary:
        base = Path(temporary)
        proc, sys, dev, fs = (base / name for name in ("proc", "sys", "dev", "rootfs"))
        sd = base / "mnt/sdcard"
        for directory in (proc, sys / "class/mtd", dev, fs / "appfs/script", fs / "appfs/bin",
                          fs / "etc/init.d", fs / "config", sd):
            directory.mkdir(parents=True)
        (proc / "uptime").symlink_to("/proc/uptime")
        for name, value in {"cpuinfo": "Processor: ARM926EJ-S\nHardware: AK3918AV130_B\n",
                            "version": "Linux version 4.4.302 fixture\n",
                            "meminfo": "MemTotal: 65536 kB\nMemFree: 20000 kB\n",
                            "mtd": 'dev: size erasesize name\nmtd0: 00040000 00001000 "uboot"\n'}.items():
            (proc / name).write_text(value)
        mmc = dev / "mmcblk0p1"
        mmc.write_bytes(b"NOT-A-REAL-BLOCK-DEVICE")
        (dev / "mtd0").write_bytes(b"FLASH-MUST-NOT-BE-READ-OR-WRITTEN")
        row = f"{mmc} {sd} vfat rw,noatime 0 0\n"
        (proc / "mounts").write_text(row)
        node = sys / "class/mtd/mtd0"
        node.mkdir()
        for name, value in {"type": "nor", "name": "uboot", "size": 262144, "erasesize": 4096,
                            "writesize": 256, "oobsize": 0, "dev": "90:0", "offset": 0}.items():
            (node / name).write_text(str(value) + "\n")
        executable = fs / "appfs/bin/yy_cam"
        executable.write_bytes(b"FAKE-ELF-NEVER-EXECUTED\0")
        start = fs / "appfs/script/start.sh"
        start.write_text("#!/bin/sh\n# STOCK-STARTUP-FIXTURE\nexit 99\n")
        root_init = fs / "init.sh"
        root_init.write_text("#!/bin/sh\n# ROOT-INIT-FIXTURE\nexit 98\n")
        (fs / "etc/init.d/rcS").symlink_to(start)
        (fs / "config/param.conf").write_text("PRIVATE_CONFIG_MUST_NOT_BE_READ\n")
        process = proc / "123"
        process.mkdir()
        (process / "comm").write_text("yy_cam\n")
        (process / "maps").write_text("00010000-00020000 r-xp /appfs/bin/yy_cam\n")
        (process / "exe").symlink_to(executable)
        (process / "environ").write_bytes(b"PRIVATE_ENV_MUST_NOT_BE_READ\0")
        (process / "cmdline").write_bytes(b"PRIVATE_ARGV_MUST_NOT_BE_READ\0")
        unrelated = proc / "124"
        unrelated.mkdir()
        (unrelated / "comm").write_text("other_application\n")
        (unrelated / "maps").write_text("UNRELATED_PROCESS_PRIVATE_DATA\n")

        source = SOURCE
        for name, value in {"PROC": proc, "SYS": sys, "DEV": dev, "FS_ROOT": fs,
                            "SD_PARENT": sd.parent, "SD_MOUNT": sd}.items():
            old = {"PROC": "/proc", "SYS": "/sys", "DEV": "/dev", "FS_ROOT": "/",
                   "SD_PARENT": "/mnt", "SD_MOUNT": "/mnt/sdcard"}[name]
            assert source.count(f"{name}={old}\n") == 1
            source = source.replace(f"{name}={old}\n", f"{name}={shlex.quote(str(value))}\n", 1)
        guard = '[ -b "$source" ] && [ ! -L "$source" ] || continue # FIXTURE_BLOCK_CHECK'
        assert source.count(guard) == 1
        source = source.replace(guard, guard.replace('-b "$source"', '-f "$source"'), 1)
        prior_runs = {}
        if case in ("collision", "collision-exhausted"):
            source = source.replace("run_prefix=$BASE/run-$START_SECONDS-$$", "run_prefix=$BASE/run-fixture")
            for number in range(16 if case == "collision-exhausted" else 1):
                prior = sd / "yyos-identity" / ("run-fixture" + (f"-{number}" if number else ""))
                prior.mkdir(parents=True)
                (prior / "status.txt").write_text("PRIOR_SUCCESS_MUST_SURVIVE\n")
                prior_runs[prior.name] = (prior / "status.txt").read_bytes()
        if case == "stacked-tmpfs":
            (proc / "mounts").write_text(f"tmpfs {sd} tmpfs rw 0 0\n" + row)
        if case == "read-only":
            (proc / "mounts").write_text(row.replace("rw,noatime", "ro,noatime"))
        if case == "duplicate":
            (proc / "mounts").write_text(row + row)
        if case == "stacked-read-only":
            (proc / "mounts").write_text(row + row.replace("rw,noatime", "ro,noatime"))
        if case == "wrong-source":
            (proc / "mounts").write_text(row.replace("mmcblk0p1", "mtd0"))
        if case == "nand-metadata":
            (node / "type").write_text("nand\n")
            (node / "oobsize").write_text("64\n")
        if case == "no-app":
            (process / "comm").write_text("some_other_process\n")
        if case == "oversize":
            (process / "maps").write_bytes(b"M" * 300000)
            start.write_bytes(b"S" * 200000)
        if case == "output-symlink":
            (sd / "yyos-identity").symlink_to(fs, target_is_directory=True)
        if case == "stale-lock":
            (sd / ".yyos-identity.lock").mkdir()
            (sd / ".yyos-identity.lock/owner").write_text("unrelated-owner\n")
        if case == "deadline":
            source = source.replace("TOTAL_BUDGET_SECONDS=60", "TOTAL_BUDGET_SECONDS=5")
        if case == "optional-timeout":
            source = source.replace("MAX_COMMAND_SECONDS=3", "MAX_COMMAND_SECONDS=1")

        real = ([str(Path(QEMU).resolve()), "-cpu", "arm926", str(Path(ARM_BB).resolve())]
                if arm else [str(HOST_BB)])
        dispatch = sd / "busybox"
        uid = "1000" if case == "non-root" else "0"
        magic = "ef53" if case == "wrong-filesystem" else "4d44"
        visible = os.makedev(179, 2 if case == "wrong-device" else 1)
        behavior = ""
        if case in ("maps-race", "optional-timeout"):
            action = "exit 7" if case == "maps-race" else "exec /bin/sleep 10"
            behavior += f'if [ "$1" = head ] && [ "${{4-}}" = "{process}/maps" ]; then {action}; fi\n'
        if case == "required-read-failure":
            behavior += f'if [ "$1" = head ] && [ "${{4-}}" = "{proc}/cpuinfo" ]; then exit 7; fi\n'
        if case == "sync-failure":
            behavior += 'if [ "$1" = sync ]; then exit 7; fi\n'
        if case == "hash-race":
            behavior += f'if [ "$1" = sha256sum ] && [ "${{2-}}" = "{process}/exe" ]; then printf partial; exit 7; fi\n'
        # Every actual read is checked: unexpected configuration, argv, environment,
        # MTD input or executable invocation can never fall through silently.
        dispatch.write_text(
            '#!/bin/sh\n'
            f'for arg do case "$arg" in "{dev}"/mtd*|"{fs}"/config/*|*/environ|*/cmdline) echo forbidden >> "{base}/forbidden-operation"; exit 97;; esac; done\n'
            f'case "$1" in *yy_cam|*start.sh) echo forbidden >> "{base}/forbidden-operation"; exit 98;; esac\n'
            f'if [ "$1" = sleep ]; then [ "${{2-}}" = 2 ] || exit 96; echo 2 >> "{base}/sampling-pauses"; exit 0; fi\n'
            f'if [ "$1" = id ] && [ "${{2-}}" = -u ]; then echo {uid}; exit 0; fi\n'
            f'if [ "$1" = stat ] && [ "${{2-}}" = -f ] && [ "${{5-}}" = "{sd}" ]; then echo {magic}; exit 0; fi\n'
            f'if [ "$1" = stat ] && [ "${{3-}}" = %d ] && [ "${{4-}}" = "{sd}" ]; then echo {visible}; exit 0; fi\n'
            f'if [ "$1" = stat ] && [ "${{3-}}" = %t:%T ] && [ "${{4-}}" = "{mmc}" ]; then echo b3:1; exit 0; fi\n'
            + behavior + 'exec ' + shlex.join(real) + ' "$@"\n')
        dispatch.chmod(0o755)
        if case == "busybox-symlink":
            actual = sd / "real-busybox"
            dispatch.rename(actual)
            dispatch.symlink_to(actual)
        script = base / "collect.sh"
        script.write_text(source)
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for root in (fs, dev)
                  for p in root.rglob("*") if p.is_file() and not p.is_symlink()}
        started = time.monotonic()
        result = subprocess.run([*real, "sh", str(script), str(sd if case != "wrong-argument" else sd.parent)],
                                capture_output=True, text=True, timeout=35)
        elapsed = time.monotonic() - started
        assert not (base / "forbidden-operation").exists(), "Collector attempted a forbidden read or execution"
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for root in (fs, dev)
                 for p in root.rglob("*") if p.is_file() and not p.is_symlink()}
        assert before == after, "Stock fixture files changed"
        for name, contents in prior_runs.items():
            assert (sd / "yyos-identity" / name / "status.txt").read_bytes() == contents
        runs = [] if case == "output-symlink" else [p for p in (sd / "yyos-identity").glob("run-*") if p.name not in prior_runs]
        success = case in {"complete", "stacked-tmpfs", "nand-metadata", "no-app", "oversize", "collision",
                           "maps-race", "optional-timeout", "hash-race"}
        assert (result.returncode == 0) == success, (case, result.returncode, result.stdout, result.stderr,
                                                     [(p.name, (p / "status.txt").read_text()) for p in runs])
        assert "PRIVATE_" not in result.stdout + result.stderr
        assert len(runs) == (1 if success or case in {"required-read-failure", "sync-failure"} else 0)
        if case == "stale-lock":
            assert (sd / ".yyos-identity.lock/owner").read_text() == "unrelated-owner\n"
        else:
            assert not (sd / ".yyos-identity.lock").exists()
        if success:
            run = runs[0]
            assert (run / "status.txt").read_text().startswith("IDENTITY_COLLECTION_COMPLETE\nexit_code=0\n")
            entries = (run / "SHA256SUMS").read_text().splitlines()
            names = set()
            for entry in entries:
                digest, name = entry.split("  ", 1)
                names.add(name)
                assert hashlib.sha256((run / name).read_bytes()).hexdigest() == digest
            assert names == {p.name for p in run.iterdir() if p.name != "SHA256SUMS"}
            combined = b"\n".join(p.read_bytes() for p in run.iterdir())
            for forbidden in (b"PRIVATE_CONFIG", b"PRIVATE_ENV", b"PRIVATE_ARGV", b"UNRELATED_PROCESS", b"FLASH-MUST-NOT"):
                assert forbidden not in combined
            assert all(p.stat().st_size <= 262144 for p in run.iterdir())
            assert (run / "mtd0-writesize.txt").read_text() == "256\n"
            assert (base / "sampling-pauses").read_text() == "2\n"
            assert (run / "startup-6-source-sha256.txt").read_text().startswith(hashlib.sha256(start.read_bytes()).hexdigest())
            assert (run / "startup-8-source-sha256.txt").read_text().startswith(hashlib.sha256(root_init.read_bytes()).hexdigest())
            assert (run / "yy_cam-candidate-1-sha256.txt").read_text().startswith(hashlib.sha256(executable.read_bytes()).hexdigest())
            if case == "nand-metadata":
                assert (run / "mtd0-type.txt").read_text() == "nand\n"
            if case == "no-app":
                assert not list(run.glob("yy_cam-123-*"))
            else:
                assert (run / "yy_cam-123-exe.txt").read_text().strip() == str(executable)
                if case == "hash-race":
                    assert not (run / "yy_cam-123-sha256.txt").exists()
                else:
                    assert (run / "yy_cam-123-sha256.txt").read_text().startswith(hashlib.sha256(executable.read_bytes()).hexdigest())
            if case in ("maps-race", "optional-timeout"):
                assert not (run / "yy_cam-123-maps.txt").exists()
                assert "yy_cam-123-maps.txt\tread-failed" in (run / "capture.tsv").read_text()
            if case == "oversize":
                assert (run / "yy_cam-123-maps.txt").stat().st_size == 262144
                assert "possibly-truncated" in (run / "capture.tsv").read_text()
            if case == "collision":
                assert run.name == "run-fixture-1"
            if case == "optional-timeout":
                assert elapsed < 10, elapsed
        elif runs:
            assert (runs[0] / "status.txt").read_text().startswith("FAILED\nexit_code=")


CASES = ("complete", "wrong-argument", "non-root", "wrong-filesystem", "wrong-device", "wrong-source",
         "read-only", "duplicate", "stacked-read-only", "stacked-tmpfs", "busybox-symlink", "output-symlink",
         "stale-lock", "collision", "collision-exhausted", "maps-race", "optional-timeout", "hash-race",
         "no-app", "oversize", "nand-metadata", "required-read-failure", "sync-failure", "deadline")


class IdentityTests(unittest.TestCase):
    pass


def add_case(case, arm):
    def test(self):
        if arm and not (ARM_BB and QEMU):
            self.skipTest("Set BACKUP_ARM_BUSYBOX and BACKUP_QEMU for ARM926 fixtures")
        if not arm and not HOST_BB:
            self.skipTest("Host BusyBox is required")
        fixture(case, arm)
    setattr(IdentityTests, "test_" + ("arm_" if arm else "host_") + case.replace("-", "_"), test)


for case in CASES:
    add_case(case, False)
    add_case(case, True)


if __name__ == "__main__":
    unittest.main()
