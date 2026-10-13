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
    EXACT_MD5 = "7c2a124cdd607ebef63fb66d063b6a87"

    def run_network_setup(self, completed_after=0, *, factory=False, override=True,
                          checksum=EXACT_MD5, paired=None, supplicant=True,
                          use_dhcp=True):
        source = (HACK / "sbin/network.sh").read_text()
        # Run the real configuration and startup path. Only omit the perpetual
        # monitor; every privileged/external network command is a fixture stub.
        startup = source.rsplit('\nif [ "$network_mode" != "tuya" ]; then', 1)[0] + "\nwait\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            hack = path / "HACK"
            for directory in (hack / "etc", hack / "bin", hack / "sbin", path / "stock/bin",
                              path / "stock/sbin", path / "ram", path / "log", path / "config",
                              path / "commands"):
                directory.mkdir(parents=True, exist_ok=True)
            events = path / "events"
            mount_targets = path / "mount-targets"
            cli = path / "stock/bin/wpa_cli"
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
            wpa = path / "stock/bin/wpa_supplicant"
            wpa.write_text('''#!/bin/sh
printf 'supplicant' >> "$TEST_EVENTS"
for arg do printf ' <%s>' "$arg" >> "$TEST_EVENTS"; done
printf '\\n' >> "$TEST_EVENTS"
echo FIXTURE_PRIVATE_WPA_OUTPUT
''')
            sleep = path / "commands/sleep"
            sleep.write_text('#!/bin/sh\necho sleep >> "$TEST_EVENTS"\n')
            dhcp = path / "commands/udhcpc"
            dhcp.write_text('''#!/bin/sh
printf 'dhcp' >> "$TEST_EVENTS"
for arg do printf ' <%s>' "$arg" >> "$TEST_EVENTS"; done
printf '\\n' >> "$TEST_EVENTS"
''')
            mount = path / "commands/mount"
            mount.write_text('''#!/bin/sh
[ "$#" = 3 ] && [ "$1" = --bind ] && [ "$2" = "$TEST_EXIT_SH" ] && [ -f "$3" ] || exit 81
echo mount >> "$TEST_EVENTS"
printf '%s\\n' "$3" >> "$TEST_MOUNT_TARGETS"
''')
            pgrep = path / "commands/pgrep"
            pgrep.write_text('#!/bin/sh\nexit 1\n')
            for command in (cli, wpa, sleep, dhcp, mount, pgrep):
                command.chmod(0o755)
            if not supplicant:
                wpa.unlink()
            # The override branch enumerates stock scripts before binding them;
            # these are only ordinary fixture files and mount itself is stubbed.
            (path / "stock/sbin/station_connect.sh").touch()
            (path / "stock/sbin/wifi_fixture.sh").touch()
            exit_script = hack / "sbin/exit.sh"
            exit_script.write_text("#!/bin/sh\nexit 0\n")
            paired_path = path / "ram/wpa_supplicant.conf"
            if paired is not None:
                paired_path.write_text(paired)
            settings = {
                "sd_path": tmp, "sd_bin": str(hack / "bin"), "sd_sbin": str(hack / "sbin"),
                "sd_log": str(path / "log"), "sys_bin": str(path / "stock/bin"),
                "sys_usr_bin": str(path / "stock/bin"), "sys_usr_sbin": str(path / "stock/sbin"),
                "sys_temp": str(path / "ram"), "sys_config": str(path / "config"),
                "network_file": str(path / "ram/network.init"), "system_hostname": "test.camera",
                "wifi_config_override": "1" if override else "0", "wifi_driver": "fixture-driver",
                "wifi_ssid": "fixture-network", "wifi_psk": "fixture-password",
                "wifi_scan_ssid": "1", "wifi_key_mgmt": "WPA-PSK", "wifi_pairwise": "CCMP",
                "wifi_group": "CCMP", "wifi_use_dhcp": "1" if use_dhcp else "0",
                "wifi_ip_address": "" if use_dhcp else "192.0.2.20", "wifi_netmask": "255.255.255.0",
                "local_rtsp_only": "1" if factory else "0", "anyka_md5": checksum,
            }
            conf = hack / "etc/hack.conf"
            conf.write_text("".join(f"{key}={shlex.quote(value)}\n" for key, value in settings.items()))
            commands = {"cat": "cat", "grep": "grep", "cp": "cp", "mv": "mv", "kill": "true",
                        "sleep": str(sleep), "udhcpc": str(dhcp), "ifconfig": "true",
                        "route": "true", "cut": "cut"}
            (hack / "etc/commands.conf").write_text(
                "".join(f"{key}={shlex.quote(value)}\n" for key, value in commands.items()))
            env = dict(os.environ, TEST_COUNT=str(path / "count"),
                       TEST_EVENTS=str(events), TEST_COMPLETED_AFTER=str(completed_after),
                       TEST_MOUNT=str(mount), TEST_PGREP=str(pgrep), TEST_EXIT_SH=str(exit_script),
                       TEST_MOUNT_TARGETS=str(mount_targets),
                       hack=str(hack), hack_conf=str(conf), hack_custom_conf="",
                       PATH=str(path / "commands") + os.pathsep + os.environ["PATH"])
            # Standalone BusyBox ash can re-exec its applets before PATH lookup
            # when ARM binfmt is enabled. Functions always select our harmless
            # fixtures, including on CI hosts where that re-exec succeeds.
            startup = ('mount() { "$TEST_MOUNT" "$@"; }\n'
                       'pgrep() { "$TEST_PGREP" "$@"; }\n') + startup
            result = subprocess.run([*runtime_shell("sh"), "-c", startup], env=env,
                                    capture_output=True, text=True, timeout=10)
            marker = (path / "ram/network.init").read_text().strip()
            return {
                "result": result, "marker": marker,
                "events": events.read_text().splitlines() if events.exists() else [],
                "mount_targets": [str(Path(target).relative_to(path))
                                  for target in mount_targets.read_text().splitlines()]
                                 if mount_targets.exists() else [],
                "paired": paired_path.read_text() if paired_path.exists() else None,
                "custom": (path / "ram/wpa_custom.conf").exists(),
                "copied": (hack / "bin/wifi_sup").exists(),
                "wpa_log": (path / "log/wpa_supplicant.log").read_text()
                           if (path / "log/wpa_supplicant.log").exists() else None,
            }

    def assert_ready(self, setup, mode="dhcp"):
        self.assertEqual(setup["result"].returncode, 0, setup["result"].stderr)
        self.assertEqual(setup["marker"], mode)

    def test_dhcp_waits_for_delayed_association(self):
        setup = self.run_network_setup(7)
        self.assert_ready(setup)
        events = setup["events"]
        self.assertEqual(events.count("sleep"), 7)
        self.assertLess(events.index("poll 8"), next(i for i, event in enumerate(events)
                                                   if event.startswith("dhcp")))

    def test_ready_link_starts_dhcp_without_sleep(self):
        setup = self.run_network_setup()
        self.assert_ready(setup)
        self.assertNotIn("sleep", setup["events"])
        self.assertEqual(sum(event.startswith("dhcp") for event in setup["events"]), 1)

    def test_legacy_override_timeout_is_bounded(self):
        setup = self.run_network_setup(-1)
        self.assert_ready(setup)
        self.assertEqual(setup["events"].count("sleep"), 30)
        self.assertTrue(any(event.startswith("dhcp") for event in setup["events"]))

    def test_normal_tuya_leaves_network_to_stock(self):
        setup = self.run_network_setup(override=False)
        self.assert_ready(setup, "tuya")
        self.assertEqual(setup["events"], [])
        self.assertFalse(setup["custom"])

    def test_older_factory_firmware_keeps_legacy_path(self):
        setup = self.run_network_setup(factory=True, override=False, checksum="older")
        self.assert_ready(setup, "tuya")
        self.assertEqual(setup["events"], [])

    def test_factory_without_ram_config_requires_override(self):
        for config in (None, ""):
            with self.subTest(config=config):
                setup = self.run_network_setup(factory=True, override=False, paired=config)
                self.assertEqual(setup["result"].returncode, 1)
                self.assertEqual(setup["marker"], "failed")
                self.assertIn("requires wifi_config_override=1", setup["result"].stderr)
                self.assertEqual(setup["events"], [])

    def test_factory_reuses_ram_config_without_copying_or_logging_it(self):
        config = "FIXTURE_PAIRED_CREDENTIALS\n"
        setup = self.run_network_setup(3, factory=True, override=False, paired=config,
                                       use_dhcp=False)
        self.assert_ready(setup)
        self.assertEqual(setup["paired"], config)
        self.assertFalse(setup["custom"])
        self.assertFalse(setup["copied"])
        self.assertIsNone(setup["wpa_log"])
        self.assertNotIn("mount", setup["events"])
        self.assertEqual(setup["events"].count("sleep"), 3)
        invocation = next(event for event in setup["events"] if event.startswith("supplicant"))
        self.assertIn("<-Dnl80211>", invocation)
        self.assertIn("/ram/wpa_supplicant.conf>", invocation)
        dhcp = next(event for event in setup["events"] if event.startswith("dhcp"))
        self.assertIn("--script=", dhcp)
        self.assertIn("/HACK/sbin/udhcpc-hook.sh>", dhcp)
        self.assertNotIn("FIXTURE_PRIVATE", setup["result"].stdout + setup["result"].stderr)
        self.assertNotIn(config.strip(), setup["result"].stdout + setup["result"].stderr)

    def test_factory_missing_stock_tool_fails(self):
        setup = self.run_network_setup(factory=True, override=False, paired="fixture\n",
                                       supplicant=False)
        self.assertEqual(setup["result"].returncode, 1)
        self.assertEqual(setup["marker"], "failed")
        self.assertIn("requires the stock WPA", setup["result"].stderr)
        self.assertEqual(setup["events"], [])

    def test_factory_association_failure_prevents_dhcp(self):
        for override in (False, True):
            with self.subTest(override=override):
                setup = self.run_network_setup(-1, factory=True, override=override, paired="fixture\n")
                self.assertEqual(setup["result"].returncode, 1)
                self.assertEqual(setup["marker"], "failed")
                self.assertEqual(setup["events"].count("sleep"), 30)
                self.assertFalse(any(event.startswith("dhcp") for event in setup["events"]))
                self.assertIn("association failed", setup["result"].stderr)

    def test_explicit_override_takes_priority_over_paired_ram_file(self):
        setup = self.run_network_setup(factory=True, paired="fixture paired config\n")
        self.assert_ready(setup)
        self.assertTrue(setup["custom"])
        self.assertTrue(setup["copied"])
        self.assertIn("mount", setup["events"])
        self.assertCountEqual(setup["mount_targets"], [
            "stock/sbin/station_connect.sh", "stock/sbin/wifi_fixture.sh",
            "stock/bin/wpa_supplicant", "stock/bin/wpa_cli",
        ])
        invocation = next(event for event in setup["events"] if event.startswith("supplicant"))
        self.assertIn("<-Dfixture-driver>", invocation)
        self.assertIn("/ram/wpa_custom.conf>", invocation)
        self.assertNotIn("/ram/wpa_supplicant.conf>", invocation)

    def test_explicit_static_override_is_preserved(self):
        setup = self.run_network_setup(use_dhcp=False)
        self.assert_ready(setup, "manual")
        self.assertFalse(any(event.startswith("dhcp") for event in setup["events"]))


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
