"""Exercise bounded service readiness with fixture children; never run full init."""
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
INIT = (ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK/sbin/init.sh").read_text()
SERVICES = (ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK/sbin/services.sh").read_text()
RUNTIME = [str((ROOT / item).resolve()) if "/" in item and not item.startswith("-") else item
           for item in shlex.split(os.environ.get("CAMOFLASH_RUNTIME_SHELL", "/bin/sh"))]
APPLETS = RUNTIME[:-1] if RUNTIME[-1] in ("ash", "sh") else [shutil.which("busybox") or "busybox"]


@unittest.skipUnless(shutil.which("busybox"), "Host BusyBox is needed for fixture applets")
class ServiceStartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="camoflash-services-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.logs = self.base / "logs"
        self.sbin = self.base / "sbin"
        self.logs.mkdir()
        self.sbin.mkdir()
        self.busybox = self.base / "busybox"
        self.calls = self.base / "calls"
        # Shorten fixture clocks while preserving real process/signal behavior.
        # All other applets use the tested BusyBox, including ARM when selected.
        self.busybox.write_text(f'''#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_CALLS"
case "$1" in
 ash) shift; exec {shlex.join(RUNTIME)} "$@";;
 sleep) exec /bin/sleep 0.025;;
 timeout)
  shift
  [ "$1" = -k ] && [ "$2" = 5 ] && [ "$3" = 60 ] || exit 99
  shift 3
  exec {shlex.join(APPLETS)} timeout -k 1 "$TEST_TIMEOUT_SECONDS" "$@";;
 *) exec {shlex.join(APPLETS)} "$@";;
esac
''')
        self.busybox.chmod(0o755)
        self.env = dict(os.environ, busybox_hack=str(self.busybox), sys_temp=str(self.base),
                        sd_log=str(self.logs), sd_sbin=str(self.sbin),
                        setup_lock_file=str(self.base / "setup.lock"),
                        breakout_file=str(self.base / "breakout"),
                        TEST_CALLS=str(self.calls), TEST_TIMEOUT_SECONDS="10")
        for key in tuple(self.env):
            if key.startswith("custom_"):
                self.env.pop(key)
        start = INIT.index("# Start and supervise services")
        self.block = INIT[start:INIT.index("# Initialization completed", start)]
        begin = INIT.index("# Stop only this init's children")
        self.cleanup = INIT[begin:INIT.index("# Initialize network", begin)]

    def run_startup(self, source, *, suffix=None, expected=0):
        service = self.sbin / "services.sh"
        service.write_text("#!/bin/sh\n" + source)
        service.chmod(0o755)
        if suffix is None:
            suffix = '\nprintf "ready-returned\\n"\n: > "$breakout_file"\nwait "$services_supervisor"\n'
        start = time.monotonic()
        result = subprocess.run([*RUNTIME, "-c", self.cleanup + self.block + suffix], env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertFalse(list(self.base.glob("services-startup.pipe.*")))
        return result, time.monotonic() - start

    def test_first_ready_run_returns_and_uses_explicit_shell(self):
        result, _ = self.run_startup('printf "fixture service started\\n"\n: > "$sys_temp/services.run"\n')
        self.assertIn("ready-returned", result.stdout)
        calls = self.calls.read_text()
        self.assertIn("timeout -k 5 60", calls)
        self.assertIn("ash " + str(self.sbin / "services.sh"), calls)
        self.assertTrue((self.base / "services.run").exists())

    def test_early_exit_without_readiness_releases_stock_startup(self):
        for status in (0, 17):
            with self.subTest(status=status):
                result, elapsed = self.run_startup(f'printf "fixture first failure\\n" >&2\nexit {status}\n', expected=1)
                self.assertIn("Services stopped before readiness", result.stdout)
                self.assertNotIn("ready-returned", result.stdout)
                self.assertIn("fixture first failure", (self.logs / "services-startup.log").read_text())
                self.assertLess(elapsed, 8)

    def test_hung_first_child_is_killed_and_fifo_removed(self):
        result, elapsed = self.run_startup(
            'printf "%s\\n" "$$" > "$sys_temp/child.pid"\nexec /bin/sleep 30\n', expected=1)
        self.assertIn("Services readiness timed out", result.stdout)
        self.assertLess(elapsed, 8)
        pid = int((self.base / "child.pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_stale_ready_marker_does_not_hide_first_child_failure(self):
        (self.base / "services.run").touch()
        result, _ = self.run_startup('exit 23\n', expected=1)
        self.assertIn("Services stopped before readiness", result.stdout)
        self.assertFalse((self.base / "services.run").exists())

    def test_startup_log_is_rotated_capped_and_excess_output_is_drained(self):
        (self.logs / "services-startup.log").write_text("previous boot\n")
        source = '''
awk 'BEGIN {for (i=0;i<10000;i++) printf "fixture diagnostic line 0123456789"}'
: > "$sys_temp/all-output-written"
: > "$sys_temp/services.run"
'''
        self.run_startup(source)
        self.assertEqual((self.logs / "services-startup.previous.log").read_text(), "previous boot\n")
        self.assertEqual((self.logs / "services-startup.log").stat().st_size, 65536)
        self.assertTrue((self.base / "all-output-written").exists())

    def test_init_signal_stops_owned_network_service_and_logger_children(self):
        service = self.sbin / "services.sh"
        service.write_text('#!/bin/sh\nprintf "%s\\n" "$$" > "$sys_temp/child.pid"\nexec /bin/sleep 30\n')
        service.chmod(0o755)
        code = self.cleanup + '\n/bin/sleep 30 &\nnetwork_pid=$!\nprintf "%s\\n" "$network_pid" > "$sys_temp/network.pid"\n' + self.block
        process = subprocess.Popen([*RUNTIME, "-c", code], env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 3
            while not (self.base / "child.pid").exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue((self.base / "child.pid").exists())
            network = int((self.base / "network.pid").read_text())
            child = int((self.base / "child.pid").read_text())
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 1, stdout + stderr)
            self.assertIn("Initialization interrupted", stderr)
            for pid in (network, child):
                with self.subTest(pid=pid), self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            # The real logger function and head/cat reader are killed through
            # these applets too. Check their actual PIDs, not only FIFO removal.
            killed = set()
            for line in self.calls.read_text().splitlines():
                args = line.split()
                if args[0] == "kill" and "-0" not in args:
                    killed.add(int(args[-1]))
            self.assertGreaterEqual(len(killed), 4)
            for pid in killed:
                with self.subTest(cleaned_pid=pid), self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            self.assertFalse(list(self.base.glob("services-startup.pipe.*")))
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_successful_init_with_absent_optional_hooks_returns_zero(self):
        completion = INIT[INIT.index("# Initialization completed"):]
        result, _ = self.run_startup(': > "$sys_temp/services.run"\n: > "$breakout_file"\n', suffix=completion)
        self.assertEqual(result.returncode, 0)

    def test_failing_configured_post_service_hook_propagates_failure(self):
        hook = self.base / "post hook"
        hook.write_text('#!/bin/sh\n: > "$sys_temp/post-hook-ran"\nexit 27\n')
        hook.chmod(0o755)
        self.env["custom_post_services_once"] = str(hook)
        result, _ = self.run_startup(': > "$sys_temp/services.run"\n: > "$breakout_file"\n',
                                     suffix=INIT[INIT.index("# Initialization completed"):], expected=1)
        self.assertTrue((self.base / "post-hook-ran").exists())

    def test_later_hung_iteration_times_out_and_supervision_continues(self):
        self.env["TEST_TIMEOUT_SECONDS"] = "1"
        source = '''
count=0
[ ! -f "$sys_temp/count" ] || read -r count < "$sys_temp/count"
count=$((count + 1))
printf '%s\\n' "$count" > "$sys_temp/count"
case "$count" in
 1) : > "$sys_temp/services.run";;
 2) exec /bin/sleep 30;;
 *) : > "$breakout_file";;
esac
'''
        result, elapsed = self.run_startup(source, suffix='\nwait "$services_supervisor"\n')
        self.assertEqual((self.base / "count").read_text(), "3\n")
        self.assertLess(elapsed, 8, result.stdout)

    def test_readiness_publish_failure_is_fatal(self):
        begin = SERVICES.index("# Touch services.run")
        end = SERVICES.index("# Update script path", begin)
        block = SERVICES[begin:end]
        env = dict(self.env, services_run=str(self.base / "missing" / "services.run"))
        result = subprocess.run([*RUNTIME, "-c", block], env=env, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot publish services readiness", result.stderr)


if __name__ == "__main__":
    unittest.main()
