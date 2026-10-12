"""Post-init observations use synthetic proc/sys/network tools only."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK/sbin/boot_diagnostics.sh"


def shell():
    return [str((ROOT / item).resolve()) if "/" in item and not item.startswith("-")
            else item for item in shlex.split(os.environ.get("CAMOFLASH_RUNTIME_SHELL", "sh"))]


class BootDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.hack = self.base / "HACK"
        self.logs = self.hack / "var/log"
        self.logs.mkdir(parents=True)
        (self.hack / "bin").mkdir()
        (self.hack / "bin/busybox").write_text("fixture only\n")
        (self.hack / "bin/busybox").chmod(0o755)
        self.proc = self.base / "proc"
        self.proc.mkdir()
        (self.proc / "uptime").write_text("123.45 321.00\n")
        (self.proc / "mounts").write_text(
            "tmpfs /mnt tmpfs rw,relatime 0 0\n"
            "/dev/mmcblk0 /mnt vfat rw,uid=0 0 0\n"
            "/dev/mmcblk0 /tmp/sd vfat rw,uid=0 0 0\n"
            "tmpfs /usr/bin/anyka_ipc tmpfs rw 0 0\n"
            "PRIVATE_SOURCE /private/location tmpfs rw,password=PRIVATE_PASSWORD 0 0\n")
        self.tmp = self.base / "tmp"
        self.tmp.mkdir()
        (self.tmp / "services.run").touch()
        (self.tmp / "_ht_get_log.conf").write_text("PRIVATE_MARKER_CONTENT\n")
        self.sys = self.base / "sys"
        (self.sys / "class/net/wlan0").mkdir(parents=True)
        (self.sys / "class/net/wlan0/operstate").write_text("up\n")
        self.wpa = self.base / "wpa_cli"
        self.wpa.write_text("fixture only\n")
        self.wpa.chmod(0o755)
        (self.base / "wpa-output").write_text(
            "bssid=aa:bb:cc:dd:ee:ff\nssid=PRIVATE_WIFI\npassword=PRIVATE_PASSWORD\n"
            "wpa_state=COMPLETED\nip_address=192.0.2.8\nkey_mgmt=WPA2-PSK\n"
            "id=private-device-id\nuuid=PRIVATE_UUID\n")
        (self.base / "ifconfig-output").write_text(
            "wlan0 Link encap:Ethernet HWaddr AA:BB:CC:DD:EE:FF\n"
            "          inet addr:192.0.2.8 Bcast:192.0.2.255 Mask:255.255.255.0\n"
            "          inet6 addr: fe80::aabb:ccff:fedd:eeff/64 Scope:Link\n"
            "          UP BROADCAST RUNNING MULTICAST MTU:1500 Metric:1\n"
            "          RX packets:4 errors:0 dropped:0 overruns:0 frame:0\n"
            "          TX packets:3 errors:0 dropped:0 overruns:0 carrier:0\n"
            "SSID=PRIVATE_WIFI\n")
        (self.base / "route-output").write_text(
            "Kernel IP routing table\nDestination Gateway Genmask Flags Metric Ref Use Iface\n"
            "0.0.0.0 192.0.2.1 0.0.0.0 UG 0 0 0 wlan0\n"
            "private-name private-router 0.0.0.0 UG 0 0 0 wlan0\n")
        self.process(20, "anyka_ipc", 10)
        self.process(21, "daemon", 10)
        self.process(22, "wpa_supplicant", 20)
        self.process(23, "udhcpc", 20)
        self.process(24, "anyka_ipc_patch", 20)
        self.process(25, "PRIVATE_PROCESS", 20)

    def process(self, pid, name, ppid):
        path = self.proc / str(pid)
        path.mkdir()
        (path / "comm").write_text(name + "\n")
        (path / "status").write_text(f"Name:\t{name}\nPid:\t{pid}\nPPid:\t{ppid}\nSecret:\tPRIVATE_STATUS\n")
        (path / "cmdline").write_bytes(b"PRIVATE_ARGV\0PRIVATE_PASSWORD\0")

    def run_helper(self):
        text = SCRIPT.read_text().replace("proc_root=/proc", "proc_root=" + shlex.quote(str(self.proc)))
        text = text.replace("sys_root=/sys", "sys_root=" + shlex.quote(str(self.sys)))
        text = text.replace("tmp_root=/tmp", "tmp_root=" + shlex.quote(str(self.tmp)))
        text = text.replace("wpa_cli=/usr/bin/wpa_cli", "wpa_cli=" + shlex.quote(str(self.wpa)))
        # Reject every unexpected command. No test can fall through to a real
        # interface, socket, vendor binary, sleep or timeout process.
        stub = r'''tool() {
    case "$1" in
        sleep) printf '%s\n' "$2" >> "$FIXTURE/sleeps" ;;
        timeout)
            printf '%s\n' "$*" >> "$FIXTURE/timeouts"
            case "$6" in
                ifconfig) [ "$7" = wlan0 ] || exit 90; command cat "$FIXTURE/ifconfig-output" ;;
                route) [ "$7" = -n ] || exit 91; command cat "$FIXTURE/route-output" ;;
                -iwlan0) [ "$7" = status ] || exit 92; [ "$LD_LIBRARY_PATH" = /lib:/usr/lib ] || exit 95; command cat "$FIXTURE/wpa-output" ;;
                *) exit 93 ;;
            esac ;;
        awk|mv) command "$@" ;;
        *) exit 94 ;;
    esac
}'''
        self.assertEqual(text.count('tool() { "$busybox_hack" "$@"; }'), 1)
        text = text.replace('tool() { "$busybox_hack" "$@"; }', stub)
        copied = self.base / "diagnostics.sh"
        copied.write_text(text)
        result = subprocess.run([*shell(), str(copied), str(self.hack)],
                                env=dict(os.environ, FIXTURE=str(self.base), LD_LIBRARY_PATH="/fixture-untrusted-libs"),
                                text=True, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result, (self.logs / "handoff.log").read_text() if (self.logs / "handoff.log").is_file() else ""

    def test_five_samples_are_read_only_and_redacted(self):
        result, output = self.run_helper()
        self.assertEqual(result.stdout, "")
        for elapsed in [0, 5, 15, 30, 60]:
            self.assertIn(f"sample nominal_seconds={elapsed} uptime=123.45", output)
        self.assertEqual((self.base / "sleeps").read_text().splitlines(), ["5", "10", "15", "30"])
        self.assertEqual(output.count("comm=anyka_ipc\n"), 5)
        self.assertIn("comm=anyka_ipc_patch", output)
        self.assertIn("wlan0 operstate=up", output)
        self.assertIn("inet addr:192.0.2.8", output)
        self.assertIn("0.0.0.0 192.0.2.1", output)
        self.assertIn("wpa_state=COMPLETED", output)
        self.assertIn("key_mgmt=WPA2-PSK", output)
        self.assertIn("marker name=services.run exists=1", output)
        self.assertIn("marker name=setup.lock exists=0", output)
        self.assertIn("marker name=_ht_get_log.conf exists=1", output)
        self.assertIn("mount source=tmpfs target=/mnt type=tmpfs access=rw", output)
        self.assertIn("mount source=/dev/mmcblk0 target=/mnt type=vfat access=rw", output)
        self.assertIn("mount source=tmpfs target=/usr/bin/anyka_ipc", output)
        for secret in ["PRIVATE", "AA:BB", "aa:bb", "fe80", "bssid", "ssid=", "uuid", "private-name"]:
            self.assertNotIn(secret, output)
        self.assertNotIn("password=", output)
        self.assertEqual(len((self.base / "timeouts").read_text().splitlines()), 15)

    def test_regular_log_rotates_and_old_previous_is_replaced(self):
        (self.logs / "handoff.log").write_text("first capture\n")
        (self.logs / "handoff.previous.log").write_text("older capture\n")
        self.run_helper()
        self.assertEqual((self.logs / "handoff.previous.log").read_text(), "first capture\n")

    def test_symlink_output_is_rejected_without_touching_target(self):
        target = self.base / "private-target"
        target.write_text("preserve\n")
        (self.logs / "handoff.log").symlink_to(target)
        self.run_helper()
        self.assertEqual(target.read_text(), "preserve\n")
        self.assertFalse((self.base / "timeouts").exists())

    def test_symlink_previous_is_rejected_without_touching_current(self):
        (self.logs / "handoff.log").write_text("current\n")
        (self.logs / "handoff.previous.log").symlink_to(self.base / "missing")
        self.run_helper()
        self.assertEqual((self.logs / "handoff.log").read_text(), "current\n")

    def test_fifo_output_is_rejected_promptly(self):
        os.mkfifo(self.logs / "handoff.log")
        self.run_helper()
        self.assertFalse((self.base / "timeouts").exists())

    def test_missing_process_network_files_soft_fail(self):
        shutil.rmtree(self.proc)
        self.proc.mkdir()
        shutil.rmtree(self.sys)
        self.wpa.unlink()
        _, output = self.run_helper()
        self.assertIn("uptime=unavailable", output)
        self.assertIn("wlan0 operstate=unavailable", output)
        self.assertIn("wpa_status=unavailable", output)
        self.assertIn("handoff samples complete", output)

    def test_wpa_filter_rejects_invalid_or_duplicate_values(self):
        (self.base / "wpa-output").write_text(
            "wpa_state=COMPLETED=PRIVATE_EXTRA\nip_address=192.0.2.8=PRIVATE_EXTRA\n"
            "key_mgmt=WPA2-PSK=PRIVATE_EXTRA\n"
            "wpa_state=COMPLETED\nwpa_state=PRIVATE_DUPLICATE\n"
            "ip_address=PRIVATE_ADDRESS\nkey_mgmt=PRIVATE WITH SPACES\n"
            "ssid=PRIVATE_WIFI\n")
        _, output = self.run_helper()
        self.assertEqual(output.count("wpa_state=COMPLETED"), 5)
        self.assertNotIn("PRIVATE", output)
        self.assertNotIn("ip_address=", output)
        self.assertNotIn("key_mgmt=", output)


if __name__ == "__main__":
    unittest.main()
