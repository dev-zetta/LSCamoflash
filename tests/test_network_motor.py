"""Run changed shell blocks with fake network and motor commands only."""
import json
import os
import shlex
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HACK = ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK"


def runtime_shell(default):
    # CGI tests run in a temporary web root; resolve repo-relative emulators and
    # BusyBox paths before changing the subprocess working directory.
    return [str((ROOT / part).resolve()) if "/" in part and not part.startswith("-")
            else part for part in shlex.split(os.environ.get("CAMOFLASH_RUNTIME_SHELL", default))]


class NetworkTests(unittest.TestCase):
    def run_network_setup(self, completed_after):
        source = (HACK / "sbin/network.sh").read_text()
        # Execute the real association wait and DHCP branch without the host
        # mounts, process termination, config writes or monitoring loop.
        block = source.split("\t# Setup network\n", 1)[1]
        block = block.split('\telse\n        network_mode="manual"', 1)[0] + "\nfi\nwait\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            events = path / "events"
            cli = path / "wpa_cli"
            cli.write_text('''#!/bin/sh
count=$(cat "$TEST_COUNT" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > "$TEST_COUNT"
echo "poll $count" >> "$TEST_EVENTS"
if [ "$TEST_COMPLETED_AFTER" -ge 0 ] && [ "$count" -gt "$TEST_COMPLETED_AFTER" ]; then
    echo wpa_state=COMPLETED
else
    echo wpa_state=ASSOCIATING
fi
''')
            sleep = path / "sleep"
            sleep.write_text('#!/bin/sh\necho sleep >> "$TEST_EVENTS"\n')
            dhcp = path / "udhcpc"
            dhcp.write_text('#!/bin/sh\necho dhcp >> "$TEST_EVENTS"\n')
            for command in (cli, sleep, dhcp):
                command.chmod(0o755)
            env = dict(os.environ, TEST_COUNT=str(path / "count"),
                       TEST_EVENTS=str(events), TEST_COMPLETED_AFTER=str(completed_after),
                       wpa_supplicant="true", wpa_cli=str(cli), grep="grep",
                       sleep=str(sleep), sd_log=tmp, wifi_use_dhcp="1",
                       ifconfig="true", udhcpc=str(dhcp), cut="cut",
                       system_hostname="test.camera", sd_sbin=tmp)
            result = subprocess.run([*runtime_shell("sh"), "-c", block], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            return events.read_text().splitlines()

    def test_dhcp_waits_for_delayed_association(self):
        events = self.run_network_setup(7)
        self.assertEqual(events[-2:], ["poll 8", "dhcp"])
        self.assertEqual(events.count("sleep"), 7)

    def test_ready_link_starts_dhcp_without_sleep(self):
        self.assertEqual(self.run_network_setup(0), ["poll 1", "dhcp"])

    def test_association_timeout_is_bounded(self):
        events = self.run_network_setup(-1)
        self.assertEqual(events.count("sleep"), 30)
        self.assertEqual(events[-1], "dhcp")


class MotorTests(unittest.TestCase):
    def run_motor(self, exit_code, query="dir=left&dist=10"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            ptz = path / "ptz.sh"
            ptz.write_text(f'#!/bin/sh\necho "motor diagnostic"\necho "error diagnostic" >&2\nexit {exit_code}\n')
            ptz.chmod(0o755)
            # Keep production query/header/JSON functions; bypass only device
            # configuration and authentication, which require the camera DB.
            common = (HACK / "var/www/cgi-bin/common.cgi").read_text()
            functions = common.split("parse_keyval() {", 1)[1].split("SESSIONID=", 1)[0]
            (path / "common.cgi").write_text("parse_keyval() {" + functions)
            script = HACK / "var/www/cgi-bin/motor.cgi"
            env = dict(os.environ, QUERY_STRING=query, sd_sbin=tmp, device_has_ptz="1")
            result = subprocess.run([*runtime_shell("bash"), str(script)], cwd=path, env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("diagnostic", result.stdout)
            self.assertEqual(result.stderr, "")
            body = result.stdout.split("\n\n", 1)[1]
            return json.loads(body)

    def test_success_is_valid_json(self):
        self.assertEqual(self.run_motor(0)["did_ptz"], "1")

    def test_unsupported_camera_is_valid_json(self):
        self.assertEqual(self.run_motor(3)["did_ptz"], "0")

    def test_capabilities_query_does_not_move_camera(self):
        self.assertEqual(self.run_motor(99, ""), {"has_ptz": "1"})


if __name__ == "__main__":
    unittest.main()
