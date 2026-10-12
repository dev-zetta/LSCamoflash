"""Exercise system-info JSON using fixture counters and mock block devices only."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK/var/www/cgi-bin/sysinfo.cgi"


def shell():
    return [str((ROOT / part).resolve()) if "/" in part and not part.startswith("-")
            else part for part in shlex.split(os.environ.get("CAMOFLASH_RUNTIME_SHELL", "sh"))]


def device(minor, size, *, block=True):
    return {"minor": minor, "size": size, "block": block}


class SysinfoTests(unittest.TestCase):
    def run_fixture(self, *, mounts="", devices=None, visible=None, used=None,
                    metrics=None, fdisk=None, blockdev_failure=False):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            counters = {
                "mounts": mounts,
                "meminfo": "MemTotal: 65536 kB\nMemFree: 12000 kB\nMemAvailable: 16000 kB\n"
                           "Buffers: 1000 kB\nCached: 2000 kB\nSReclaimable: 3000 kB\nShmem: 4000 kB\n",
                "cpuinfo": "processor : 0\nProcessor : ARM926EJ-S rev 5 (v5l)\n",
                "uptime": "90061.25 12.0\n", "loadavg": "0.15 1.25 2.50 1/12 1\n",
                "stat": "cpu 100 0 100 800\n",
                "stat_after": "cpu 120 0 110 870\n",
            }
            counters.update(metrics or {})
            for name, contents in counters.items():
                (path / name).write_text(contents)
            fixture = {"devices": devices or {}, "visible": visible or {},
                       "used": used or {}, "fdisk": fdisk or {},
                       "blockdev_failure": blockdev_failure}
            (path / "fixture.json").write_text(json.dumps(fixture))
            (path / "common.cgi").write_text(
                'send_header() { printf "Content-Type: %s\\r\\n\\r\\n" "$1"; }\n')
            # Shell functions override target BusyBox's standalone applets too.
            # Every block-device lookup and /proc path is a fixture; nothing is mounted.
            mock = path / "mock.py"
            mock.write_text('''import json, os, pathlib, sys
p = pathlib.Path(os.environ["SYSINFO_FIXTURE"])
f = json.loads((p / "fixture.json").read_text())
name, *args = sys.argv[1:]
with (p / "calls").open("a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "sleep":
    (p / "stat").write_text((p / "stat_after").read_text())
elif name == "stat":
    fmt, target = args[1:]
    if fmt == "%D":
        value = f["visible"].get(target)
        if value is None: sys.exit(1)
        print(value)
    else:
        dev = f["devices"].get(target)
        if dev is None: sys.exit(1)
        if fmt == "%F": print("block special file" if dev["block"] else "regular file")
        elif fmt == "%t:%T": print("b3:" + format(dev["minor"], "x"))
        else: sys.exit(2)
elif name == "blockdev":
    if f["blockdev_failure"]: sys.exit(1)
    dev = f["devices"].get(args[1])
    if dev is None: sys.exit(1)
    print(dev["size"])
elif name == "fdisk":
    value = f["fdisk"].get(args[1])
    if value is None: sys.exit(1)
    print(f"Disk {args[1]}: 1 GB, {value} bytes")
elif name == "df":
    value = f["used"].get(args[1])
    if value is None: sys.exit(1)
    print("Filesystem 1024-blocks Used Available Capacity Mounted on")
    print(f"/dev/fixture 10000000 {value} 100 1% {args[1]}")
else: sys.exit(2)
''')
            source = SCRIPT.read_text()
            for name in ("mounts", "meminfo", "cpuinfo", "uptime", "loadavg", "stat"):
                source = source.replace("/proc/" + name, str(path / name))
            (path / "sysinfo.cgi").write_text(source)
            stubs = "\n".join(
                f'{name}() {{ {shlex.quote(sys.executable)} {shlex.quote(str(mock))} {name} "$@"; }}'
                for name in ("stat", "blockdev", "fdisk", "df", "sleep"))
            env = dict(os.environ, SYSINFO_FIXTURE=temporary, sd_path="/tmp/sd", sys_mnt="/mnt")
            result = subprocess.run([*shell(), "-c", stubs + "\n. ./sysinfo.cgi"],
                                    cwd=path, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            body = json.loads(result.stdout.split("\n\n", 1)[1])
            calls = [json.loads(line) for line in (path / "calls").read_text().splitlines()]
            return body, calls

    def test_whole_fat_card_with_covered_tmpfs(self):
        body, _ = self.run_fixture(
            mounts="tmpfs /mnt tmpfs rw 0 0\n/dev/mmcblk0 /mnt vfat rw 0 0\n",
            devices={"/dev/mmcblk0": device(0, 8 * 1024**3)},
            visible={"/mnt": "b300"}, used={"/mnt": 12345})
        self.assertEqual(body["sdcard"], {
            "size": 8 * 1024**3, "used": 12345 * 1024, "size_gb": "8.0 GiB",
            "partition1": {"size": 8 * 1024**3, "used": 12345 * 1024},
            "partition2": {"size": 0, "used": 0}})

    def test_first_partition_only_leaves_second_slot_zero(self):
        body, _ = self.run_fixture(
            mounts="/dev/mmcblk0p1 /tmp/sd vfat rw 0 0\n",
            devices={"/dev/mmcblk0": device(0, 4 * 1024**3),
                     "/dev/mmcblk0p1": device(1, 4 * 1024**3 - 1048576)},
            visible={"/tmp/sd": "b301"}, used={"/tmp/sd": 20})
        self.assertEqual(body["sdcard"]["partition2"], {"size": 0, "used": 0})
        self.assertEqual(body["sdcard"]["partition1"]["used"], 20 * 1024)
        self.assertEqual(body["sdcard"]["size"], 4 * 1024**3)

    def test_two_partitions_sum_used_without_mounting_boot_partition(self):
        body, calls = self.run_fixture(
            mounts="/dev/mmcblk0p1 /mnt vfat rw 0 0\n/dev/mmcblk0p2 /tmp/sd vfat rw 0 0\n",
            devices={"/dev/mmcblk0": device(0, 8 * 1024**3),
                     "/dev/mmcblk0p1": device(1, 1024**3),
                     "/dev/mmcblk0p2": device(2, 7 * 1024**3 - 1048576)},
            visible={"/mnt": "b301", "/tmp/sd": "b302"},
            used={"/mnt": 300, "/tmp/sd": 400})
        self.assertEqual(body["sdcard"]["used"], 700 * 1024)
        self.assertEqual(body["sdcard"]["partition1"]["size"], 1024**3)
        self.assertEqual(body["sdcard"]["partition2"]["used"], 400 * 1024)
        self.assertTrue(all(call[0] in {"stat", "blockdev", "fdisk", "df", "sleep"} for call in calls))

    def test_visible_device_identity_wins_over_mount_row_order(self):
        for rows in (("/dev/mmcblk0p1 /mnt vfat rw 0 0\n/dev/mmcblk0p2 /mnt vfat rw 0 0\n"),
                     ("/dev/mmcblk0p2 /mnt vfat rw 0 0\n/dev/mmcblk0p1 /mnt vfat rw 0 0\n")):
            with self.subTest(rows=rows):
                body, _ = self.run_fixture(
                    mounts=rows,
                    devices={"/dev/mmcblk0": device(0, 1000000),
                             "/dev/mmcblk0p1": device(1, 100000),
                             "/dev/mmcblk0p2": device(2, 800000)},
                    visible={"/mnt": "b302"}, used={"/mnt": 30})
                self.assertEqual(body["sdcard"]["partition1"]["used"], 0)
                self.assertEqual(body["sdcard"]["partition2"]["used"], 30 * 1024)

    def test_duplicate_bind_mounts_are_counted_once(self):
        body, calls = self.run_fixture(
            mounts="/dev/mmcblk0 /mnt vfat rw 0 0\n/dev/mmcblk0 /tmp/sd vfat rw 0 0\n",
            devices={"/dev/mmcblk0": device(0, 1000000)},
            visible={"/mnt": "b300", "/tmp/sd": "b300"}, used={"/mnt": 40, "/tmp/sd": 40})
        self.assertEqual(body["sdcard"]["used"], 40 * 1024)
        self.assertEqual(sum(call[0] == "df" for call in calls), 1)

    def test_unmounted_boot_partition_has_size_but_no_used_space(self):
        body, _ = self.run_fixture(
            mounts="/dev/mmcblk0p2 /tmp/sd vfat rw 0 0\n",
            devices={"/dev/mmcblk0": device(0, 1000000),
                     "/dev/mmcblk0p1": device(1, 100000), "/dev/mmcblk0p2": device(2, 800000)},
            visible={"/tmp/sd": "b302"}, used={"/tmp/sd": 20})
        self.assertEqual(body["sdcard"]["partition1"], {"size": 100000, "used": 0})

    def test_non_mmc_wrong_filesystem_and_wrong_identity_report_zero(self):
        for row, dev, number in (("/dev/sda /mnt vfat rw 0 0\n", "/dev/sda", "800"),
                                 ("/dev/mmcblk0 /mnt ext4 rw 0 0\n", "/dev/mmcblk0", "b300"),
                                 ("/dev/mmcblk0 /mnt vfat rw 0 0\n", "/dev/mmcblk0", "1")):
            with self.subTest(row=row):
                body, calls = self.run_fixture(mounts=row, devices={dev: device(0, 1000000)},
                                               visible={"/mnt": number})
                self.assertEqual(body["sdcard"]["size"], 0)
                self.assertEqual(body["sdcard"]["used"], 0)
                self.assertFalse(any(call[0] == "blockdev" for call in calls))

    def test_regular_file_named_as_device_is_rejected(self):
        body, _ = self.run_fixture(mounts="/dev/mmcblk0 /mnt vfat rw 0 0\n",
                                   devices={"/dev/mmcblk0": device(0, 1000000, block=False)},
                                   visible={"/mnt": "b300"})
        self.assertEqual(body["sdcard"]["size"], 0)

    def test_fdisk_fallback_and_nonzero_mmc_index(self):
        body, _ = self.run_fixture(
            mounts="/dev/mmcblk1p1 /tmp/sd vfat rw 0 0\n",
            devices={"/dev/mmcblk1": device(8, 0), "/dev/mmcblk1p1": device(9, 0)},
            visible={"/tmp/sd": "b309"}, used={"/tmp/sd": 2}, blockdev_failure=True,
            fdisk={"/dev/mmcblk1": 1000000, "/dev/mmcblk1p1": 900000})
        self.assertEqual(body["sdcard"]["size"], 1000000)
        self.assertEqual(body["sdcard"]["partition1"]["size"], 900000)

    def test_kernel_counters_and_arm_processor_name(self):
        body, _ = self.run_fixture()
        self.assertEqual(body["cpu"], {"model": "ARM926EJ-S rev 5 (v5l)", "cores": 1, "usage_percent": 30})
        self.assertEqual(body["memory"], {
            "total_kB": 65536, "free_kB": 12000, "available_kB": 16000,
            "available_reported": True, "buffers_kB": 1000, "cached_kB": 2000,
            "reclaimable_kB": 3000, "shared_kB": 4000})
        self.assertEqual(body["uptime"]["seconds"], 90061)
        self.assertEqual(body["load"], {"min1": .15, "min5": 1.25, "min15": 2.5})

    def test_missing_malformed_or_huge_counters_remain_json_numbers(self):
        body, _ = self.run_fixture(metrics={
            "meminfo": "MemTotal: bad kB\nMemFree: -1 kB\nMemAvailable: 99999999999999999 kB\n",
            "cpuinfo": "", "uptime": "", "loadavg": "NaN -2 infinity\n",
            "stat": "cpu bad 0 1 2\n", "stat_after": "cpu 1 0 0 1\n"})
        self.assertEqual(body["memory"], {
            "total_kB": 0, "free_kB": 0, "available_kB": 0,
            "available_reported": False, "buffers_kB": 0, "cached_kB": 0,
            "reclaimable_kB": 0, "shared_kB": 0})
        self.assertEqual(body["load"], {"min1": 0, "min5": 0, "min15": 0})
        self.assertEqual(body["cpu"]["usage_percent"], 0)
        self.assertEqual(body["uptime"]["seconds"], 0)

    def test_cpu_model_json_escaping(self):
        body, _ = self.run_fixture(metrics={"cpuinfo": 'processor : 0\nmodel name : ARM "fixture" \\ chip\tname\n'})
        self.assertEqual(body["cpu"]["model"], 'ARM "fixture" \\ chipname')

    def test_missing_available_counter_differs_from_real_zero(self):
        for suffix, reported in (("", False), ("MemAvailable: 0 kB\n", True)):
            with self.subTest(reported=reported):
                body, _ = self.run_fixture(metrics={
                    "meminfo": "MemTotal: 65536 kB\nMemFree: 4096 kB\n" + suffix})
                self.assertEqual(body["memory"]["available_kB"], 0)
                self.assertEqual(body["memory"]["available_reported"], reported)

    def test_invalid_cache_counters_remain_numeric_zero(self):
        body, _ = self.run_fixture(metrics={
            "meminfo": "MemTotal: 65536 kB\nMemAvailable: 16000 kB\n"
                       "Buffers: -1 kB\nCached: NaN kB\nSReclaimable: bad kB\n"
                       "Shmem: 99999999999999999 kB\n"})
        for name in ("buffers_kB", "cached_kB", "reclaimable_kB", "shared_kB"):
            self.assertEqual(body["memory"][name], 0)


if __name__ == "__main__":
    unittest.main()
