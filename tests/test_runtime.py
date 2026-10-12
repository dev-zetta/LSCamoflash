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
CHECKSUM = "0123456789abcdef0123456789abcdef"
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
            "find": "find", "head": "head", "md5sum": "md5sum", "awk": "awk", "touch": "touch", "grep": "grep",
            "mount": "true", "busybox_hack": str(self.paths["sd_bin"] / "busybox"),
        })
        self.write_executable(self.paths["sd_bin"] / "busybox",
                              '#!/bin/sh\n[ "$1" = sh ] || exit 90\nshift\nexec ' + shlex.join(RUNTIME_SHELL) + ' "$@"\n')
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
exit {status}
''')

    def custom(self, text):
        (self.hack / "etc/hack_custom.conf").write_text(text)

    def wrapper(self, *args):
        return subprocess.run([*RUNTIME_SHELL, str(SBIN / "anyka_ipc_wrapper.sh"), *args],
                              env=self.env, capture_output=True, text=True, timeout=3)

    def snippet(self, start, end, prefix=""):
        # Only selected blocks whose filesystem paths and commands are all
        # redirected above are run. Full init.sh would mutate the host.
        begin = INIT.index("\n", INIT.index(start)) + 1
        block = INIT[begin:INIT.index(end, begin)]
        return subprocess.run([*RUNTIME_SHELL, "-c", prefix + block], env=self.env,
                              capture_output=True, text=True, timeout=3)

    def launched(self):
        return (self.paths["sys_temp"] / "launched").read_text().strip()

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

    def test_local_mode_does_not_invoke_autopatcher(self):
        self.env.update(local_rtsp_only="1", use_ipc_autopatcher="1")
        self.write_executable(self.paths["sd_sbin"] / "apply_ips_patch.sh",
                              '#!/bin/sh\ntouch "$sys_temp/patcher_invoked"\nexit 99\n')
        result = self.snippet("# Check, whether anyka_ipc_patched exists", "# Check, whether ssl exists")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.paths["sys_temp"] / "patcher_invoked").exists())
        self.assertFalse((self.paths["sys_temp"] / "setup.lock").exists())

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
