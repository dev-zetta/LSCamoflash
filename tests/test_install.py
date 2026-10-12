"""Offline installer regression tests. No test opens or modifies a real disk."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "SOURCE/src/sdcard/install.sh"
MIB = 1024 * 1024
GIB = 1024 * MIB

# All privileged operations go through this stub. Only cp touches fixture files.
STUB = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ["TEST_ROOT"])
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
state_path = root / "state.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {"mounts": {}, "counts": {}}
state["counts"][name] = state["counts"].get(name, 0) + 1
count = state["counts"][name]
def save():
    state_path.write_text(json.dumps(state))
save()
if name == os.environ.get("FAIL_TOOL") and (os.environ.get("FAIL_ALWAYS") or count == int(os.environ.get("FAIL_NUMBER", "1"))):
    sys.exit(23)
disk = "/dev/" + os.environ.get("TEST_DISK", "sdz")
part = disk + ("p" if disk[-1].isdigit() else "")
if name == "id":
    print("0")
elif name == "lsblk":
    if "NAME,RM,TYPE,MODEL,SIZE" in args:
        print("sda 0 disk INTERNAL 1T\n" + disk[5:] + " 1 disk TEST 16G")
    elif "KNAME,TYPE,RM,RO" in args:
        print(os.environ.get("TEST_INFO", disk[5:] + " disk 1 0"))
    else:
        print(os.environ.get("TEST_CHILDREN", disk + " disk\n" + part + "1 part vfat\n" + part + "2 part vfat"))
elif name == "blockdev":
    print(os.environ.get("TEST_SIZE", str(16 * 1024 ** 3)))
elif name == "sfdisk":
    (root / "layout.txt").write_text(sys.stdin.read())
elif name == "findmnt":
    if os.environ.get("TEST_PREMOUNT") and not state.get("unmounted"):
        sys.exit(0)
    sys.exit(1)
elif name == "mountpoint":
    sys.exit(0 if args[-1] in state["mounts"] else 1)
elif name == "mount":
    source, target = args[-2:]
    assert source in (part + "1", part + "2"), source
    assert pathlib.Path(target).is_relative_to(root), target
    assert pathlib.Path(target).parent.stat().st_mode & 0o077 == 0, "Backup directory is not private"
    state["mounts"][target] = {"source": source, "readonly": "ro" in args}
    if "ro" in args:
        fixtures = root / "old" / source.rsplit("/", 1)[-1]
        if fixtures.exists():
            shutil.copytree(fixtures, target, dirs_exist_ok=True)
    save()
elif name == "umount":
    target = args[-1]
    mounted = state["mounts"].pop(target, None)
    if mounted:
        if not mounted["readonly"]:
            output = root / "result" / mounted["source"].rsplit("/", 1)[-1]
            shutil.copytree(target, output, dirs_exist_ok=True)
        for entry in pathlib.Path(target).iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    else:
        assert target in (disk, part + "1", part + "2"), target
        state["unmounted"] = True
    save()
elif name == "cp":
    for argument in args:
        if argument.startswith("/"):
            assert pathlib.Path(argument).is_relative_to(root), argument
    os.execv("/bin/cp", ["cp", *args])
elif name in ("wipefs", "partprobe", "mkfs.vfat"):
    assert args[-1] in (disk, part + "1", part + "2"), args
elif name not in ("udevadm", "sync"):
    raise AssertionError(name)
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lscamoflash installer ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root / "payload with spaces"
        self.payload.mkdir()
        shutil.copyfile(INSTALLER, self.payload / "install.sh")
        for name, content in {
            "mmcblk0p1/hostapd": "hostapd",
            "mmcblk0p1/.hidden": "hidden",
            "mmcblk0p2/HACK/etc/hack_custom.conf": "payload config",
            "mmcblk0p2/HACK/etc/passwd": "legacy passwd",
        }.items():
            file = self.payload / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool in ("id", "lsblk", "blockdev", "findmnt", "mountpoint", "umount", "wipefs", "sfdisk", "partprobe", "udevadm", "mkfs.vfat", "mount", "cp", "sync"):
            file = self.bin / tool
            file.write_text(STUB)
            file.chmod(0o755)
        self.tmpdir = self.root / "temporary mounts"
        self.tmpdir.mkdir()
        self.env = {**os.environ, "PATH": str(self.bin) + ":/usr/sbin:/usr/bin:/sbin:/bin", "TEST_ROOT": str(self.root), "TMPDIR": str(self.tmpdir)}

    def run_installer(self, disk="sdz", *, options=(), env=None, confirmation=None):
        variables = {**self.env, **(env or {})}
        # The sole block-device predicate is replaced in the sourced test driver.
        # Production main still checks actual block devices and requires root.
        driver = r'''source "$1"
is_block_device() {
    local dev="/dev/${TEST_DISK:-sdz}" prefix
    prefix="$dev"
    [[ ! "$dev" =~ [0-9]$ ]] || prefix="${dev}p"
    [[ "$1" == "$dev" || "$1" == "${prefix}1" || "$1" == "${prefix}2" ]]
}
command() {
    if [[ "${1:-}" == -v && "${2:-}" == "${TEST_MISSING_TOOL:-}" ]]; then
        return 1
    fi
    builtin command "$@"
}
shift
main "$@"
'''
        return subprocess.run(
            ["bash", "-c", driver, "test-installer", str(self.payload / "install.sh"), *options],
            input=disk + "\n" + (disk if confirmation is None else confirmation) + "\n",
            cwd=self.root, env=variables, text=True, capture_output=True, timeout=15,
        )

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assert_no_writes(self):
        self.assertFalse({"wipefs", "sfdisk", "mkfs.vfat", "mount", "cp"} & {call[0] for call in self.calls()})

    def test_success_from_other_directory_includes_hidden_files_and_full_gib(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("abgeschlossen", result.stdout)
        self.assertNotIn("INTERNAL", result.stdout)
        self.assertEqual((self.root / "result/sdz1/.hidden").read_text(), "hidden")
        self.assertEqual((self.root / "result/sdz1/passwd").read_text(), "legacy passwd")
        self.assertEqual((self.root / "result/sdz2/HACK/etc/hack_custom.conf").read_text(), "payload config")
        self.assertIn("start=1MiB, size=15359MiB", (self.root / "layout.txt").read_text())
        self.assertIn("size=1024MiB", (self.root / "layout.txt").read_text())
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_numbered_kernel_device_uses_p_separator(self):
        result = self.run_installer("mmcblk7", env={"TEST_DISK": "mmcblk7"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[-1] for call in self.calls() if call[0] == "mkfs.vfat"], ["/dev/mmcblk7p1", "/dev/mmcblk7p2"])

    def test_rejects_paths_globs_options_and_multiple_names(self):
        for disk in ("/dev/sdz", "../sdz", "sdz*", "-sdz", "sdz sda", ""):
            with self.subTest(disk=disk):
                result = self.run_installer(disk)
                self.assertNotEqual(result.returncode, 0)
        self.assert_no_writes()

    def test_rejects_internal_partition_readonly_and_ambiguous_targets(self):
        for info in ("sdz disk 0 0", "sdz part 1 0", "sdz disk 1 1", "sdz disk 1 0\nsda disk 0 0", "sda disk 1 0", "sdz disk 1 0 extra"):
            with self.subTest(info=info):
                result = self.run_installer(env={"TEST_INFO": info})
                self.assertNotEqual(result.returncode, 0)
        self.assert_no_writes()

    def test_rejects_swap_and_layered_devices(self):
        for children in ("/dev/sdz disk\n/dev/sdz1 part swap", "/dev/sdz disk\n/dev/dm-0 crypt ext4"):
            with self.subTest(children=children):
                result = self.run_installer(env={"TEST_CHILDREN": children})
                self.assertNotEqual(result.returncode, 0)
        self.assert_no_writes()

    def test_confirmation_must_match(self):
        result = self.run_installer(confirmation="sda")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_writes()

    def test_missing_payload_aborts_before_target_access(self):
        shutil.rmtree(self.payload / "mmcblk0p2")
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_writes()

    def test_missing_required_tool_aborts_before_target_access(self):
        for tool in ("mkfs.vfat", "sfdisk", "udevadm"):
            with self.subTest(tool=tool):
                result = self.run_installer(env={"TEST_MISSING_TOOL": tool})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Programm fehlt: " + tool, result.stderr)
        self.assertEqual([call[0] for call in self.calls()], ["id", "id", "id"])
        self.assert_no_writes()

    def test_invalid_sizes_abort_before_erasing(self):
        for size in (str(GIB), "", "not-a-number", "99999999999999999999"):
            with self.subTest(size=size):
                result = self.run_installer(env={"TEST_SIZE": size})
                self.assertNotEqual(result.returncode, 0)
        self.assert_no_writes()

    def test_unmount_failure_prevents_erasing(self):
        result = self.run_installer(env={"TEST_PREMOUNT": "1", "FAIL_TOOL": "umount"})
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_writes()

    def test_partitioning_failure_prevents_formatting(self):
        result = self.run_installer(env={"FAIL_TOOL": "sfdisk"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("mkfs.vfat", [call[0] for call in self.calls()])
        self.assertNotIn("abgeschlossen", result.stdout)
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_wipe_failure_prevents_partitioning(self):
        result = self.run_installer(env={"FAIL_TOOL": "wipefs"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("sfdisk", [call[0] for call in self.calls()])
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_kernel_reread_failure_prevents_formatting(self):
        result = self.run_installer(env={"FAIL_TOOL": "partprobe"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("mkfs.vfat", [call[0] for call in self.calls()])

    def test_formatting_failure_prevents_mount_and_copy(self):
        result = self.run_installer(env={"FAIL_TOOL": "mkfs.vfat"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("mount", [call[0] for call in self.calls()])
        self.assertNotIn("cp", [call[0] for call in self.calls()])

    def test_second_mount_failure_cleans_first_mount(self):
        result = self.run_installer(env={"FAIL_TOOL": "mount", "FAIL_NUMBER": "2"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads((self.root / "state.json").read_text())["mounts"], {})
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        self.assertNotIn("abgeschlossen", result.stdout)

    def test_copy_failure_cleans_both_mounts_without_success(self):
        result = self.run_installer(env={"FAIL_TOOL": "cp"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("abgeschlossen", result.stdout)
        self.assertEqual(json.loads((self.root / "state.json").read_text())["mounts"], {})
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_final_unmount_failure_reports_failure_and_retries_cleanup(self):
        result = self.run_installer(env={"FAIL_TOOL": "umount"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("abgeschlossen", result.stdout)
        self.assertEqual(json.loads((self.root / "state.json").read_text())["mounts"], {})
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_persistent_cleanup_failure_keeps_mounted_contents_intact(self):
        result = self.run_installer(env={"FAIL_TOOL": "umount", "FAIL_ALWAYS": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("abgeschlossen", result.stdout)
        state = json.loads((self.root / "state.json").read_text())
        self.assertEqual(len(state["mounts"]), 2)
        working = next(self.tmpdir.iterdir())
        self.assertEqual((working / "partition1/hostapd").read_text(), "hostapd")
        self.assertEqual((working / "partition2/HACK/etc/hack_custom.conf").read_text(), "payload config")

    def test_sd_configuration_is_readonly_preserved_and_never_saved_to_payload(self):
        old = self.root / "old/sdz2"
        for name, content in {
            "HACK/etc/hack_custom.conf": "old settings",
            "HACK/etc/config/passwd": "old passwd",
            "HACK/etc/config/shadow": "old shadow",
            "HACK/var/spool/cron/crontabs/root": "old cron",
        }.items():
            file = old / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        (self.payload / "hack_custom.conf").write_text("local override")
        result = self.run_installer(options=("-u",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "result/sdz2/HACK/etc/hack_custom.conf").read_text(), "old settings")
        self.assertEqual((self.root / "result/sdz2/HACK/etc/config/passwd").read_text(), "old passwd")
        self.assertEqual((self.root / "result/sdz1/shadow").read_text(), "old shadow")
        self.assertEqual((self.root / "result/sdz2/HACK/var/spool/cron/crontabs/root").read_text(), "old cron")
        self.assertEqual((self.payload / "hack_custom.conf").read_text(), "local override")
        self.assertFalse((self.payload / "passwd").exists())
        reads = [call for call in self.calls() if call[0] == "mount" and "ro" in call]
        self.assertEqual(len(reads), 2)

    def test_failed_backup_read_aborts_before_erasing(self):
        result = self.run_installer(options=("-u",), env={"FAIL_TOOL": "mount"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse({"wipefs", "sfdisk", "mkfs.vfat"} & {call[0] for call in self.calls()})
        self.assertEqual(list(self.tmpdir.iterdir()), [])


@unittest.skipUnless(shutil.which("sfdisk"), "sfdisk is unavailable")
class PartitionLayoutTests(unittest.TestCase):
    def test_actual_sfdisk_table_on_regular_sparse_image(self):
        # Exercise the real parser using a regular file, never a loop or disk device.
        for size in (16008609792, 32 * GIB):
            with self.subTest(size=size), tempfile.TemporaryDirectory(prefix="lscamoflash layout ") as directory:
                image = Path(directory) / "card.img"
                with image.open("wb") as file:
                    file.truncate(size)
                layout = subprocess.run(["bash", "-c", 'source "$1"; partition_layout "$2"', "layout-test", str(INSTALLER), str(size)], text=True, capture_output=True, check=True).stdout
                subprocess.run(["sfdisk", "--wipe", "always", "--wipe-partitions", "always", str(image)], input=layout, text=True, capture_output=True, check=True, timeout=15)
                table = json.loads(subprocess.run(["sfdisk", "--json", str(image)], text=True, capture_output=True, check=True).stdout)["partitiontable"]
                first, second = table["partitions"]
                sector = table["sectorsize"]
                self.assertEqual(first["start"] * sector, MIB)
                self.assertGreaterEqual(second["size"] * sector, GIB)
                self.assertEqual(first["start"] + first["size"], second["start"])
                self.assertLessEqual((second["start"] + second["size"]) * sector, size)
                self.assertEqual(first["type"], "c")
                self.assertEqual(second["type"], "c")


if __name__ == "__main__":
    unittest.main()
