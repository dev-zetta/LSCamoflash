"""Hermetic runtime regressions; never execute camera init or real mounts."""

import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SBIN = ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK/sbin"
INIT = (SBIN / "init.sh").read_text()
CHECKSUMS = SBIN.parent / "etc/anyka_checksums.conf"
CHECKSUM = "0123456789abcdef0123456789abcdef"
SI_L25502_MD5 = "7c2a124cdd607ebef63fb66d063b6a87"
SI_L25502_SHA256 = "d710cfe53a9e0098e4271db4fff2fc485e38acdaf78d965accaf2e516980534d"
RUNTIME_SHELL = shlex.split(os.environ.get("CAMOFLASH_RUNTIME_SHELL", "/bin/sh"))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="camoflash-runtime-")
        self.addCleanup(self.temp.cleanup)
        # Exercise quoting without putting the executable command variables in
        # paths with spaces (those intentionally contain a command + applet).
        self.base = Path(self.temp.name) / "camera files"
        self.hack = self.base / "HACK"
        self.paths = {
            "hack": self.hack,
            "sd_path": self.base,
            "sd_bin": self.hack / "bin",
            "sd_sbin": self.hack / "sbin",
            "sd_lib": self.hack / "lib",
            "sd_patch": self.hack / "usr/patch",
            "sd_etc": self.hack / "etc",
            "sd_config": self.hack / "etc/config",
            "sys_temp": self.base / "tmp",
            "sys_bin": self.base / "firmware/bin",
            "sys_usr_bin": self.base / "firmware/usr/bin",
            "sys_usr_lib": self.base / "firmware/usr/lib",
            "sys_usr_local": self.base / "firmware/usr/local",
            "sys_config": self.base / "firmware/etc/config",
        }
        for path in self.paths.values():
            path.mkdir(parents=True, exist_ok=True)
        self.env = os.environ.copy()
        self.env.update({key: str(value) for key, value in self.paths.items()})
        self.env.update({
            "anyka_md5": CHECKSUM,
            "setup_lock_file": str(self.paths["sys_temp"] / "setup.lock"),
            "cp": "cp", "mv": "mv", "rm": "rm", "sed": "sed",
            "find": "find", "head": "head", "md5sum": "md5sum", "sha256sum": "sha256sum",
            "awk": "awk", "touch": "touch", "grep": "grep", "cat": "cat",
            "mount": "true", "busybox_hack": str(self.paths["sd_bin"] / "busybox"),
        })
        self.write_executable(self.paths["sd_bin"] / "busybox",
                              '#!/bin/sh\nif [ "$1" = md5sum ]; then\n'
                              '  [ -z "$test_md5" ] || { printf "%s  %s\\n" "$test_md5" "$2"; exit 0; }\n'
                              '  shift\nexec md5sum "$@"\nfi\n'
                              'if [ "$1" = sha256sum ]; then\n'
                              '  printf "%s  %s\\n" "$test_sha256" "$2"\n'
                              '  exit "${test_sha256_status:-0}"\nfi\n'
                              '[ "$1" = sh ] || exit 90\nshift\nexec ' + shlex.join(RUNTIME_SHELL) + ' "$@"\n')
        shutil.copy2(self.paths["sd_bin"] / "busybox", self.paths["sys_bin"] / "busybox")
        for name in ("anyka_ipc_wrapper.sh", "anyka_rtsp.sh"):
            shutil.copyfile(SBIN / name, self.paths["sd_sbin"] / name)
        self.sleep = Path(self.temp.name) / "sleep"
        self.write_executable(self.sleep, '#!/bin/sh\nprintf "%s\\n" "$1" >> "$sys_temp/sleeps"\n'
                                        '[ ! -f "$sys_temp/remove_startlock" ] || '
                                        'rm -f "$sys_temp/_ak39_startlock.ini"\nexit 0\n')
        self.config = self.hack / "etc/hack.conf"
        self.config.write_text("".join(
            f"export {key}={shlex.quote(str(value))}\n" for key, value in self.paths.items()
        ) + 'export local_rtsp_only=""\nexport FORCE_STATE_LED_OFF=""\n')
        (self.hack / "etc/commands.conf").write_text(
            f"export sleep={shlex.quote(str(self.sleep))}\n"
            "export rm=rm\nexport touch=touch\nexport md5sum=md5sum\nexport awk=awk\nexport pidof=false\nexport kill=true\n"
        )
        self.stock = self.paths["sd_bin"] / "anyka_ipc"
        self.binary(self.stock, "stock")
        self.hardware = self.paths["sys_config"] / "_ht_hw_settings.ini"
        self.hardware.write_text("[config]\ntilt_total_steps = 1234\nmain_width = 2304\n")

    @staticmethod
    def write_executable(path, source):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        path.chmod(0o755)

    def binary(self, path, label, status=0):
        self.write_executable(path, f'''#!/bin/sh
printf '%s\\n' '{label}' > "$sys_temp/launched"
printf '%s\\n' "$LD_LIBRARY_PATH" > "$sys_temp/library"
[ ! -f "$sys_temp/_ak39_factory.ini" ] || touch "$sys_temp/factory_at_launch"
[ ! -f "$sys_temp/_ht_ap_mode.conf" ] || touch "$sys_temp/ap_at_launch"
exit {status}
''')

    def custom(self, text):
        (self.hack / "etc/hack_custom.conf").write_text(text)

    def wrapper(self, *args):
        return subprocess.run([*RUNTIME_SHELL, str(SBIN / "anyka_ipc_wrapper.sh"), *args],
                              env=self.env, capture_output=True, text=True, timeout=3)

    def snippet(self, start, end, prefix="", suffix=""):
        # Only selected blocks whose filesystem paths and commands are all
        # redirected above are run. Full init.sh would mutate the host.
        begin = INIT.index("\n", INIT.index(start)) + 1
        block = INIT[begin:INIT.index(end, begin)]
        return subprocess.run([*RUNTIME_SHELL, "-c", prefix + block + suffix], env=self.env,
                              capture_output=True, text=True, timeout=3)

    def profile(self, checksum, sha256=SI_L25502_SHA256, sha256_status=0, checksums=CHECKSUMS):
        shutil.copyfile(self.stock, self.paths["sys_usr_bin"] / "anyka_ipc")
        sha_command = Path(self.temp.name) / "profile-sha256"
        self.write_executable(sha_command,
                              '#!/bin/sh\nprintf "%s  %s\\n" "$test_sha256" "$1"\n'
                              'exit "$test_sha256_status"\n')
        self.env.update(anyka_md5=checksum, sha256sum=str(sha_command),
                        test_sha256=sha256, test_sha256_status=str(sha256_status),
                        anyka_checksums_conf=str(checksums))
        fields = ("device_var", "device_model", "device_article", "device_firmware", "device_bundle",
                  "device_soc", "device_cpu", "device_sensor", "device_has_motors", "device_motor_count",
                  "device_has_ptz", "device_width", "device_height", "device_supported",
                  "device_stock_binary_only", "use_ipc_autopatcher", "local_rtsp_only",
                  "device_rtsp_available", "device_rtsp_main_port", "device_rtsp_main_path",
                  "device_rtsp_sub_port", "device_rtsp_sub_path", "device_rtsp_main_width",
                  "device_rtsp_main_height", "device_rtsp_sub_width", "device_rtsp_sub_height",
                  "device_rtsp_main_codec", "device_rtsp_sub_codec")
        output = "".join(f'printf "profile {field}=%s\\n" "${field}"\n' for field in fields)
        load_begin = INIT.index("\n", INIT.index("# Load anyka checksums")) + 1
        load_checksums = INIT[load_begin:INIT.index("# Repair Mode", load_begin)]
        result = self.snippet("# Check, on which device we are on", 'echo "Device hostname is:',
                              load_checksums, output)
        profile = dict(line.removeprefix("profile ").split("=", 1)
                       for line in result.stdout.splitlines() if line.startswith("profile "))
        return result, profile

    def launched(self):
        return (self.paths["sys_temp"] / "launched").read_text().strip()

    def test_init_network_accepts_completed_modes_and_replaces_stale_status(self):
        marker = self.paths["sys_temp"] / "network.mode"
        self.env.update(network_file=str(marker), sleep=str(self.sleep), kill="true")
        for mode in ("tuya", "dhcp", "manual"):
            with self.subTest(mode=mode):
                marker.write_text("failed\n")
                self.write_executable(self.paths["sd_sbin"] / "network.sh",
                                      f'#!/bin/sh\nprintf "%s\\n" "{mode}" > "$network_file"\n')
                result = self.snippet("# Initialize network", "# Breakout file", suffix='echo setup-reached\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("setup-reached", result.stdout)
                self.assertEqual(marker.read_text(), mode + "\n")

    def test_init_network_failure_stops_before_service_setup(self):
        marker = self.paths["sys_temp"] / "network.mode"
        self.env.update(network_file=str(marker), sleep=str(self.sleep), kill="true")
        self.write_executable(self.paths["sd_sbin"] / "network.sh",
                              '#!/bin/sh\nprintf "failed\\n" > "$network_file"\nexit 1\n')
        result = self.snippet("# Initialize network", "# Breakout file", suffix='echo setup-reached\n')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Network initialization failed", result.stdout)
        self.assertNotIn("setup-reached", result.stdout)

    def test_init_network_missing_completion_is_bounded(self):
        self.env.update(network_file=str(self.paths["sys_temp"] / "network.mode"),
                        sleep=str(self.sleep), kill="true")
        self.write_executable(self.paths["sd_sbin"] / "network.sh", '#!/bin/sh\nexit 1\n')
        result = self.snippet("# Initialize network", "# Breakout file", suffix='echo setup-reached\n')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Network initialization timed out", result.stdout)
        self.assertNotIn("setup-reached", result.stdout)
        self.assertEqual((self.paths["sys_temp"] / "sleeps").read_text().splitlines(), ["1"] * 90)

    def test_local_factory_uses_stock_with_patches_installed_and_propagates_exit(self):
        self.binary(self.paths["sd_bin"] / "anyka_ipc_patched", "dynamic")
        self.binary(self.paths["sd_patch"] / CHECKSUM / "bin/anyka_ipc_patched", "static")
        self.binary(self.stock, "stock", 17)
        self.custom('export local_rtsp_only="1"\n')
        result = self.wrapper(CHECKSUM)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(self.launched(), "stock")
        self.assertTrue((self.paths["sys_temp"] / "factory_at_launch").exists())
        self.assertFalse((self.paths["sys_temp"] / "_ak39_startlock.ini").exists())
        self.assertFalse((self.paths["sys_temp"] / "sleeps").exists())
        self.assertEqual(self.hardware.read_text(), "[config]\ntilt_total_steps = 1234\nmain_width = 2304\n")
        self.assertEqual((self.paths["sys_temp"] / "anyka_ipc_wrapper.cmd").read_text().strip(), str(self.stock))

    def test_normal_binary_priority_and_library_paths(self):
        dynamic = self.paths["sd_bin"] / "anyka_ipc_patched"
        static_patched = self.paths["sd_patch"] / CHECKSUM / "bin/anyka_ipc_patched"
        static_stock = self.paths["sd_patch"] / CHECKSUM / "bin/anyka_ipc"
        for path, label in ((dynamic, "dynamic"), (static_patched, "static patched"), (static_stock, "static stock")):
            self.binary(path, label)
        for path, label, lib in ((dynamic, "dynamic", self.paths["sd_lib"]),
                                 (static_patched, "static patched", static_patched.parent.parent / "lib"),
                                 (static_stock, "static stock", static_stock.parent.parent / "lib"),
                                 (self.stock, "stock", self.paths["sd_lib"])):
            with self.subTest(label=label):
                result = self.wrapper(CHECKSUM)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.launched(), label)
                self.assertEqual((self.paths["sys_temp"] / "library").read_text().strip(), f"/lib:/usr/lib:{lib}")
                self.assertFalse((self.paths["sys_temp"] / "factory_at_launch").exists())
                path.unlink()

    def test_force_factory_option_is_honored(self):
        for path, label, flag in (
                (self.paths["sd_bin"] / "anyka_ipc_patched", "dynamic", "PATCHED"),
                (self.paths["sd_patch"] / CHECKSUM / "bin/anyka_ipc_patched", "static patched", "STATIC_PATCHED"),
                (self.paths["sd_patch"] / CHECKSUM / "bin/anyka_ipc", "static stock", "STATIC"),
                (self.stock, "stock", "ORIGIN")):
            with self.subTest(flag=flag):
                self.binary(path, label)
                self.custom(f'export FORCE_AK39_FACTORY_ON_{flag}="1"\n')
                result = self.wrapper(CHECKSUM)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.launched(), label)
                self.assertTrue((self.paths["sys_temp"] / "factory_at_launch").exists())
                (self.paths["sys_temp"] / "factory_at_launch").unlink()
                (self.paths["sys_temp"] / "_ak39_factory.ini").unlink()
                path.unlink()

    def test_optional_custom_config_and_computed_checksum(self):
        checksum = hashlib.md5(self.stock.read_bytes()).hexdigest()
        self.binary(self.paths["sd_patch"] / checksum / "bin/anyka_ipc", "static stock")
        result = self.wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launched(), "static stock")

    def test_setup_and_manual_ipc_locks_prevent_factory_start(self):
        self.custom('export local_rtsp_only="1"\n')
        for name in ("setup.lock", "anyka_ipc.lock"):
            lock = self.paths["sys_temp"] / name
            lock.touch()
            with self.subTest(lock=name):
                result = self.wrapper(CHECKSUM)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse((self.paths["sys_temp"] / "launched").exists())
                self.assertFalse((self.paths["sys_temp"] / "_ak39_factory.ini").exists())
            lock.unlink()

    def test_service_startlock_waits_then_releases(self):
        self.custom('export local_rtsp_only="1"\n')
        (self.paths["sys_temp"] / "_ak39_startlock.ini").touch()
        (self.paths["sys_temp"] / "remove_startlock").touch()
        result = self.wrapper(CHECKSUM)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launched(), "stock")
        self.assertEqual((self.paths["sys_temp"] / "sleeps").read_text(), "3\n")

    def test_missing_stock_does_not_start_patch_in_local_mode(self):
        self.stock.unlink()
        self.binary(self.paths["sd_bin"] / "anyka_ipc_patched", "dynamic")
        self.custom('export local_rtsp_only="1"\n')
        result = self.wrapper(CHECKSUM)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.paths["sys_temp"] / "launched").exists())
        self.assertFalse((self.paths["sys_temp"] / "_ak39_factory.ini").exists())

    def test_factory_marker_failure_prevents_stock_start(self):
        self.custom('export local_rtsp_only="1"\n')
        with (self.hack / "etc/commands.conf").open("a") as config:
            config.write("export touch=false\n")
        result = self.wrapper(CHECKSUM)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.paths["sys_temp"] / "launched").exists())

    def test_disabling_local_or_forced_factory_mode_clears_owned_marker(self):
        for setting in ("local_rtsp_only", "FORCE_AK39_FACTORY_ON_ORIGIN"):
            with self.subTest(setting=setting):
                self.custom(f'export {setting}="1"\n')
                result = self.wrapper(CHECKSUM)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((self.paths["sys_temp"] / "anyka_factory.owned").exists())
                self.custom(f'export {setting}=""\n')
                (self.paths["sys_temp"] / "factory_at_launch").unlink()
                result = self.wrapper(CHECKSUM)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((self.paths["sys_temp"] / "_ak39_factory.ini").exists())
                self.assertFalse((self.paths["sys_temp"] / "anyka_factory.owned").exists())
                self.assertFalse((self.paths["sys_temp"] / "factory_at_launch").exists())

    def test_external_factory_marker_is_preserved_across_mode_changes(self):
        (self.paths["sys_temp"] / "_ak39_factory.ini").touch()
        for value in ("1", ""):
            with self.subTest(local_rtsp_only=value):
                self.custom(f'export local_rtsp_only="{value}"\n')
                result = self.wrapper(CHECKSUM)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((self.paths["sys_temp"] / "_ak39_factory.ini").exists())
                self.assertFalse((self.paths["sys_temp"] / "anyka_factory.owned").exists())

    def test_generated_bootstrap_runs_with_optional_custom_config(self):
        result = self.snippet("# Construct a small bootstrap;", "# Prepare anyka ipc wrapper and configuration")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(["/bin/sh", str(self.paths["sys_temp"] / "anyka_ipc_wrapper.sh")],
                                env=self.env, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launched(), "stock")

    def test_factory_service_options_handle_spacing_and_preserve_other_settings(self):
        config = self.paths["sd_config"] / "anyka_cfg.ini"
        config.write_text("[global]\nrtsp=0 ; enabled for factory\n  onvif\t=\t0\n# rtsp = 0\nother = 42\nrtsp = 01\nonvif = 0foo\n")
        result = self.snippet("# Prepare and mount factory_cfg.ini", "# Check, whether a backup of tuya dbs exists")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config.read_text(), "[global]\nrtsp = 1 ; enabled for factory\nonvif = 1\n# rtsp = 0\nother = 42\nrtsp = 01\nonvif = 0foo\n")
        self.assertEqual((self.paths["sys_config"] / "anyka_cfg.ini").read_text(), config.read_text())

    def test_firmware_change_invalidates_cached_dynamic_patch(self):
        current = self.paths["sys_usr_bin"] / "anyka_ipc"
        current.write_bytes(b"new firmware")
        patched = self.paths["sd_bin"] / "anyka_ipc_patched"
        self.binary(patched, "old patch")
        result = self.snippet("# Check, whether anyka_ipc exists", "# Check, whether anyka_ipc_patched exists",
                              INIT.split("# Compare function", 1)[1].split("# Create paths on sd", 1)[0])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stock.read_bytes(), current.read_bytes())
        self.assertFalse(patched.exists())

    def test_unchanged_firmware_keeps_cached_patch(self):
        current = self.paths["sys_usr_bin"] / "anyka_ipc"
        shutil.copyfile(self.stock, current)
        patched = self.paths["sd_bin"] / "anyka_ipc_patched"
        self.binary(patched, "current patch")
        result = self.snippet("# Check, whether anyka_ipc exists", "# Check, whether anyka_ipc_patched exists",
                              INIT.split("# Compare function", 1)[1].split("# Create paths on sd", 1)[0])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(patched.exists())

    def test_active_hardware_settings_are_preserved(self):
        factory = self.paths["sys_usr_local"] / "_ht_hw_settings.ini"
        factory.write_text("tilt_total_steps = 2200\n")
        result = self.snippet("# Prepare anyka ipc wrapper and configuration", 'echo -n "Enabling anyka_ipc_wrapper..."')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.paths["sys_temp"] / "_ht_hw_settings.ini").read_text(), self.hardware.read_text())

    def test_si_l25502_exact_profile_keeps_stock_and_separates_motors_from_cli(self):
        self.env.update(use_ipc_autopatcher="1", local_rtsp_only="")
        result, profile = self.profile(SI_L25502_MD5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(profile, {
            "device_var": "indoor_ptz_3007325_5_6_2863_125",
            "device_model": "Smart PTZ Camera SI L25502", "device_article": "3007325.5",
            "device_firmware": "6.2863.125.1348", "device_bundle": "HT_IPC286KS3_GMN_TUYA_AK3918EV330",
            "device_soc": "AK3918EV330", "device_cpu": "ARM926 (ARMv5)", "device_sensor": "SC3332",
            "device_has_motors": "1", "device_motor_count": "2", "device_has_ptz": "0",
            "device_width": "2304", "device_height": "1296", "device_supported": "1",
            "device_stock_binary_only": "1", "use_ipc_autopatcher": "0", "local_rtsp_only": "",
            "device_rtsp_available": "0", "device_rtsp_main_port": "554", "device_rtsp_main_path": "/main_ch",
            "device_rtsp_sub_port": "554", "device_rtsp_sub_path": "/sub_ch", "device_rtsp_main_width": "",
            "device_rtsp_main_height": "", "device_rtsp_sub_width": "", "device_rtsp_sub_height": "",
            "device_rtsp_main_codec": "H264", "device_rtsp_sub_codec": "H264",
        })
        self.assertEqual(self.hardware.read_text(), "[config]\ntilt_total_steps = 1234\nmain_width = 2304\n")
        checksums = CHECKSUMS.read_text()
        self.assertIn(f"indoor_ptz_3007325_5_6_2863_125_originl={SI_L25502_MD5}\n", checksums)
        self.assertIn(f"indoor_ptz_3007325_5_6_2863_125_sha256={SI_L25502_SHA256}\n", checksums)
        self.assertNotIn("indoor_ptz_3007325_5_6_2863_125_patched=", checksums)

    def test_si_l25502_explicit_local_profile_publishes_stock_mode_two_stream_parameters(self):
        self.env["local_rtsp_only"] = "1"
        result, profile = self.profile(SI_L25502_MD5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(profile["device_rtsp_available"], "1")
        self.assertEqual(profile["device_rtsp_main_port"], "88")
        self.assertEqual(profile["device_rtsp_main_path"], "/videoMain")
        self.assertEqual(profile["device_rtsp_sub_port"], "89")
        self.assertEqual(profile["device_rtsp_sub_path"], "/videoSub")
        self.assertEqual(profile["device_rtsp_main_width"], "2304")
        self.assertEqual(profile["device_rtsp_main_height"], "1296")
        self.assertEqual(profile["device_rtsp_sub_width"], "640")
        self.assertEqual(profile["device_rtsp_sub_height"], "360")
        self.assertEqual(profile["device_rtsp_main_codec"], "H265")
        self.assertEqual(profile["device_rtsp_sub_codec"], "H264")
        self.assertEqual((profile["device_width"], profile["device_height"]), ("2304", "1296"))

    def test_si_l25502_profile_rejects_sha256_mismatch_or_unavailable_hash(self):
        for digest in ("0" * 64, ""):
            with self.subTest(sha256=digest):
                result, profile = self.profile(SI_L25502_MD5, digest)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("SHA256 does not match", result.stdout)
                self.assertEqual(profile, {})
        result, profile = self.profile(SI_L25502_MD5, SI_L25502_SHA256, sha256_status=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Cannot hash", result.stdout)
        self.assertEqual(profile, {})

    def test_si_l25502_wrapper_uses_stock_despite_all_replacement_types(self):
        for path, label in ((self.paths["sd_bin"] / "anyka_ipc_patched", "dynamic"),
                            (self.paths["sd_patch"] / SI_L25502_MD5 / "bin/anyka_ipc_patched", "static patched"),
                            (self.paths["sd_patch"] / SI_L25502_MD5 / "bin/anyka_ipc", "static stock")):
            self.binary(path, label)
        self.env.update(test_md5=SI_L25502_MD5, test_sha256=SI_L25502_SHA256)
        for local in ("", "1"):
            with self.subTest(local_rtsp_only=local):
                self.custom(f'export local_rtsp_only="{local}"\n')
                result = self.wrapper(SI_L25502_MD5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.launched(), "stock")
                self.assertEqual((self.paths["sys_temp"] / "library").read_text().strip(),
                                 f"/lib:/usr/lib:{self.paths['sd_lib']}")
                self.assertFalse((self.paths["sys_temp"] / "factory_at_launch").exists())
                self.assertEqual((self.paths["sys_temp"] / "ap_at_launch").exists(), local == "1")

    def test_si_l25502_wrapper_rechecks_stock_hash_before_launch(self):
        self.custom('export local_rtsp_only="1"\n')
        self.env["test_md5"] = SI_L25502_MD5
        self.binary(self.paths["sd_bin"] / "anyka_ipc_patched", "dynamic")
        for digest, status in (("0" * 64, 0), ("", 1), (SI_L25502_SHA256, 1)):
            with self.subTest(sha256=digest, status=status):
                self.env.update(test_sha256=digest, test_sha256_status=str(status))
                result = self.wrapper(SI_L25502_MD5)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse((self.paths["sys_temp"] / "launched").exists())
                self.assertFalse((self.paths["sys_temp"] / "_ak39_factory.ini").exists())
                self.assertFalse((self.paths["sys_temp"] / "_ht_ap_mode.conf").exists())

    def test_si_l25502_profile_works_with_preserved_pre_profile_checksum_config(self):
        legacy = self.paths["sd_etc"] / "old-checksums.conf"
        legacy.write_text("ipc_xc_c323_originl=fd726ad2e0b6b5c2f1a1c41d350a5d0a\n")
        result, profile = self.profile(SI_L25502_MD5, checksums=legacy)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(profile["device_article"], "3007325.5")
        self.assertEqual(profile["device_stock_binary_only"], "1")
        self.assertEqual(legacy.read_text(), "ipc_xc_c323_originl=fd726ad2e0b6b5c2f1a1c41d350a5d0a\n")

    def test_si_l25502_owned_ap_marker_is_removed_when_local_mode_is_disabled(self):
        self.env.update(test_md5=SI_L25502_MD5, test_sha256=SI_L25502_SHA256)
        self.custom('export local_rtsp_only="1"\n')
        result = self.wrapper(SI_L25502_MD5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.paths["sys_temp"] / "anyka_rtsp_ap.owned").exists())
        self.assertTrue((self.paths["sys_temp"] / "ap_at_launch").exists())
        (self.paths["sys_temp"] / "ap_at_launch").unlink()
        self.custom('export local_rtsp_only=""\n')
        result = self.wrapper(SI_L25502_MD5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.paths["sys_temp"] / "_ht_ap_mode.conf").exists())
        self.assertFalse((self.paths["sys_temp"] / "anyka_rtsp_ap.owned").exists())
        self.assertFalse((self.paths["sys_temp"] / "ap_at_launch").exists())

    def test_si_l25502_external_ap_marker_is_preserved_across_mode_changes(self):
        self.env.update(test_md5=SI_L25502_MD5, test_sha256=SI_L25502_SHA256)
        marker = self.paths["sys_temp"] / "_ht_ap_mode.conf"
        marker.write_text("external marker\n")
        for local in ("1", ""):
            with self.subTest(local_rtsp_only=local):
                self.custom(f'export local_rtsp_only="{local}"\n')
                result = self.wrapper(SI_L25502_MD5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(marker.read_text(), "external marker\n")
                self.assertFalse((self.paths["sys_temp"] / "anyka_rtsp_ap.owned").exists())

    def test_si_l25502_clears_owned_legacy_manufacturing_marker_but_rejects_unowned_one(self):
        self.env.update(test_md5=SI_L25502_MD5, test_sha256=SI_L25502_SHA256)
        self.custom('export local_rtsp_only="1"\n')
        marker = self.paths["sys_temp"] / "_ak39_factory.ini"
        owner = self.paths["sys_temp"] / "anyka_factory.owned"
        marker.touch()
        result = self.wrapper(SI_L25502_MD5)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Conflicting AK39", result.stderr)
        self.assertTrue(marker.exists())
        self.assertFalse((self.paths["sys_temp"] / "launched").exists())
        owner.touch()
        result = self.wrapper(SI_L25502_MD5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(owner.exists())
        self.assertTrue((self.paths["sys_temp"] / "ap_at_launch").exists())
        self.assertFalse((self.paths["sys_temp"] / "factory_at_launch").exists())

    def test_si_l25502_rejects_manufacturing_force_options_and_wrong_md5_labels(self):
        self.env.update(test_md5=SI_L25502_MD5, test_sha256=SI_L25502_SHA256)
        for flag in ("ORIGIN", "PATCHED", "STATIC_PATCHED", "STATIC"):
            with self.subTest(flag=flag):
                self.custom(f'export FORCE_AK39_FACTORY_ON_{flag}="1"\n')
                result = self.wrapper(SI_L25502_MD5)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("manufacturing mode is unsupported", result.stderr)
                self.assertFalse((self.paths["sys_temp"] / "launched").exists())
                self.assertFalse((self.paths["sys_temp"] / "_ak39_factory.ini").exists())
        self.custom('export local_rtsp_only="1"\n')
        result = self.wrapper(CHECKSUM)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("MD5 does not match", result.stderr)
        self.assertFalse((self.paths["sys_temp"] / "launched").exists())

    def test_si_l25502_rtsp_entry_cannot_bypass_mode_or_binary_checks(self):
        self.env.update(test_md5=SI_L25502_MD5, test_sha256=SI_L25502_SHA256, local_rtsp_only="1")
        ap = self.paths["sys_temp"] / "_ht_ap_mode.conf"
        factory = self.paths["sys_temp"] / "_ak39_factory.ini"
        cases = (("missing AP", False, False, SI_L25502_MD5, SI_L25502_SHA256),
                 ("factory conflict", True, True, SI_L25502_MD5, SI_L25502_SHA256),
                 ("wrong MD5 label", True, False, CHECKSUM, SI_L25502_SHA256),
                 ("wrong SHA", True, False, SI_L25502_MD5, "0" * 64))
        for label, has_ap, has_factory, checksum, sha in cases:
            with self.subTest(case=label):
                ap.unlink(missing_ok=True)
                factory.unlink(missing_ok=True)
                if has_ap:
                    ap.touch()
                if has_factory:
                    factory.touch()
                self.env["test_sha256"] = sha
                result = subprocess.run([*RUNTIME_SHELL, str(SBIN / "anyka_rtsp.sh"), checksum],
                                        env=self.env, capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse((self.paths["sys_temp"] / "launched").exists())

    def test_other_checksum_does_not_select_si_l25502_or_inherit_its_flags(self):
        self.env.update(device_stock_binary_only="1", device_motor_count="2", device_article="3007325.5",
                        use_ipc_autopatcher="1")
        result, profile = self.profile("fd726ad2e0b6b5c2f1a1c41d350a5d0a")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(profile["device_var"], "ipc_xc_c323")
        self.assertEqual(profile["device_has_ptz"], "1")
        self.assertEqual(profile["device_has_motors"], "1")
        self.assertEqual(profile["device_motor_count"], "")
        self.assertEqual(profile["device_article"], "")
        self.assertEqual(profile["device_stock_binary_only"], "0")
        self.assertEqual(profile["use_ipc_autopatcher"], "1")
        result, profile = self.profile(CHECKSUM)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(profile["device_supported"], "0")
        self.assertEqual(profile["device_var"], "")
        self.assertEqual(profile["device_stock_binary_only"], "0")

    def test_stock_only_profile_invalidates_cached_patch_even_with_unchanged_stock(self):
        current = self.paths["sys_usr_bin"] / "anyka_ipc"
        shutil.copyfile(self.stock, current)
        patched = self.paths["sd_bin"] / "anyka_ipc_patched"
        self.binary(patched, "old patch")
        self.env["device_stock_binary_only"] = "1"
        original = self.stock.read_bytes()
        result = self.snippet("# Check, whether anyka_ipc exists", "# Check, whether anyka_ipc_patched exists",
                              INIT.split("# Compare function", 1)[1].split("# Create paths on sd", 1)[0])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stock.read_bytes(), original)
        self.assertFalse(patched.exists())

    def test_stock_only_profile_does_not_run_autopatcher_even_when_enabled(self):
        self.env.update(device_stock_binary_only="1", local_rtsp_only="", use_ipc_autopatcher="1")
        digest = hashlib.md5(self.stock.read_bytes()).hexdigest()
        (self.paths["sd_patch"] / f"{digest}.ips.gz").touch()
        self.write_executable(self.paths["sd_sbin"] / "apply_ips_patch.sh",
                              '#!/bin/sh\ntouch "$sys_temp/patcher_invoked"\nexit 99\n')
        original = self.stock.read_bytes()
        result = self.snippet("# Check, whether anyka_ipc_patched exists", "# Check, whether ssl exists")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.paths["sys_temp"] / "patcher_invoked").exists())
        self.assertFalse((self.paths["sys_temp"] / "setup.lock").exists())
        self.assertEqual(self.stock.read_bytes(), original)

    def test_optional_legacy_library_is_preserved_when_firmware_does_not_ship_it(self):
        cached = self.paths["sd_lib"] / "libavssdkbeta.so"
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    cached.write_bytes(b"existing library")
                result = self.snippet("# Check, whether libavssdkbeta.so exists", "# Prepare and mount factory_cfg.ini")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(cached.exists(), existing)
                if existing:
                    self.assertEqual(cached.read_bytes(), b"existing library")

    def test_legacy_library_copy_and_update_use_current_firmware_library(self):
        current = self.paths["sys_usr_lib"] / "libavssdkbeta.so"
        cached = self.paths["sd_lib"] / "libavssdkbeta.so"
        for content in (b"stock library", b"updated library"):
            with self.subTest(content=content):
                current.write_bytes(content)
                result = self.snippet("# Check, whether libavssdkbeta.so exists", "# Prepare and mount factory_cfg.ini",
                                      INIT.split("# Compare function", 1)[1].split("# Create paths on sd", 1)[0])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(cached.read_bytes(), content)

    def test_local_mode_does_not_invoke_autopatcher(self):
        self.env.update(local_rtsp_only="1", use_ipc_autopatcher="1")
        self.write_executable(self.paths["sd_sbin"] / "apply_ips_patch.sh",
                              '#!/bin/sh\ntouch "$sys_temp/patcher_invoked"\nexit 99\n')
        result = self.snippet("# Check, whether anyka_ipc_patched exists", "# Check, whether ssl exists")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.paths["sys_temp"] / "patcher_invoked").exists())
        self.assertFalse((self.paths["sys_temp"] / "setup.lock").exists())

    def test_stock_only_software_schema_and_bytes_are_preserved(self):
        stock = self.paths["sys_config"] / "_ht_sw_settings.ini"
        cached = self.paths["sd_config"] / "_ht_sw_settings.ini"
        template = self.paths["sd_config"] / "_ht_sw_config.tmpl"
        original = b'; vendor formatting\r\n[config]\r\nbool_paired = 1\r\n:vendor_key = 7\r\n'
        stock.write_bytes(original)
        template.write_text('bool_has_config_wifi = 1\nint_unrelated_model_setting = 10\n')
        self.env["device_stock_binary_only"] = "1"
        for prior_copy in (None, b'[config]\nbool_has_config_wifi = 0\n'):
            with self.subTest(existing_cache=prior_copy is not None):
                if prior_copy is None:
                    cached.unlink(missing_ok=True)
                else:
                    cached.write_bytes(prior_copy)
                result = self.snippet("# Check, whether _ht_sw_settings.ini exists", "# Check, whether libavssdkbeta.so exists")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(stock.read_bytes(), original)
                self.assertEqual(cached.read_bytes(), original)
                self.assertNotIn(b'bool_has_config_wifi', stock.read_bytes())

    def test_failed_patch_keeps_stock_and_does_not_record_checksum_or_reboot(self):
        digest = hashlib.md5(self.stock.read_bytes()).hexdigest()
        (self.paths["sd_patch"] / f"{digest}.ips.gz").touch()
        checksums = self.hack / "etc/anyka_checksums.conf"
        checksums.write_text("example_patched=unchanged\n")
        self.env.update(local_rtsp_only="", use_ipc_autopatcher="1", device_var="example")
        self.write_executable(self.paths["sd_sbin"] / "apply_ips_patch.sh",
                              '#!/bin/sh\necho incomplete > "$3"\nexit 42\n')
        result = self.snippet("# Check, whether anyka_ipc_patched exists", "# Check, whether ssl exists")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Binary patch failed", result.stdout)
        self.assertFalse((self.paths["sd_bin"] / "anyka_ipc_patched").exists())
        self.assertFalse((self.paths["sys_temp"] / "setup.lock").exists())
        self.assertEqual(checksums.read_text(), "example_patched=unchanged\n")
        self.assertTrue(self.stock.exists())

    def test_successful_patch_records_checksum_and_requests_reboot(self):
        digest = hashlib.md5(self.stock.read_bytes()).hexdigest()
        (self.paths["sd_patch"] / f"{digest}.ips.gz").touch()
        checksums = self.hack / "etc/anyka_checksums.conf"
        checksums.write_text("example_patched=old\n")
        self.env.update(local_rtsp_only="", use_ipc_autopatcher="1", device_var="example")
        self.write_executable(self.paths["sd_sbin"] / "apply_ips_patch.sh",
                              '#!/bin/sh\necho complete > "$3"\nexit 0\n')
        result = self.snippet("# Check, whether anyka_ipc_patched exists", "# Check, whether ssl exists")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.paths["sys_temp"] / "setup.lock").exists())
        digest = hashlib.md5((self.paths["sd_bin"] / "anyka_ipc_patched").read_bytes()).hexdigest()
        self.assertEqual(checksums.read_text(), f"example_patched={digest}\n")

    def test_existing_camera_processes_stop_before_factory_start(self):
        self.custom('export local_rtsp_only="1"\n')
        pidof = Path(self.temp.name) / "pidof"
        kill = Path(self.temp.name) / "kill"
        self.write_executable(pidof, '#!/bin/sh\nprintf "777777 %s\\n" "$PPID"\n')
        self.write_executable(kill, '#!/bin/sh\nprintf "%s %s\\n" "$1" "$2" >> "$sys_temp/kills"\n'
                                    '[ ! -f "$sys_temp/launched" ]\n')
        with (self.hack / "etc/commands.conf").open("a") as config:
            config.write(f"export pidof={shlex.quote(str(pidof))}\nexport kill={shlex.quote(str(kill))}\n")
        result = self.wrapper(CHECKSUM)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.paths["sys_temp"] / "kills").read_text(), "-KILL 777777\n")
        self.assertEqual(self.launched(), "stock")

    @unittest.skipUnless(shutil.which("busybox"), "BusyBox unavailable")
    def test_factory_start_and_config_with_busybox_ash(self):
        self.custom('export local_rtsp_only="1"\n')
        result = subprocess.run([shutil.which("busybox"), "sh", str(SBIN / "anyka_ipc_wrapper.sh"), CHECKSUM],
                                env=self.env, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launched(), "stock")
        config = self.paths["sd_config"] / "anyka_cfg.ini"
        config.write_text("rtsp=0\nonvif = 0 # factory\nrtsp = 01\n")
        self.env["sed"] = f"{shutil.which('busybox')} sed"
        result = self.snippet("# Prepare and mount factory_cfg.ini", "# Check, whether a backup of tuya dbs exists")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config.read_text(), "rtsp = 1\nonvif = 1 # factory\nrtsp = 01\n")


if __name__ == "__main__":
    unittest.main()
