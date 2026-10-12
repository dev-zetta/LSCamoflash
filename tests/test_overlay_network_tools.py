"""Exercise actual overlay policy and PATH lookup without camera tools/mounts."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INIT = (ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK/sbin/init.sh").read_text()
BEGIN = INIT.index("configure_overlay_network_tools()")
FUNCTION = INIT[BEGIN:INIT.index('\noverlay_dirs=', BEGIN)]
SHELL = [str((ROOT / item).resolve()) if "/" in item and not item.startswith("-") else item
         for item in shlex.split(os.environ.get("CAMOFLASH_RUNTIME_SHELL", "/bin/sh"))]
EXACT_MD5 = "7c2a124cdd607ebef63fb66d063b6a87"


class OverlayNetworkToolsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="camoflash-overlay-tools-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name) / "camera files"
        self.mount = self.base / "overlay"
        self.sbin = self.mount / "override/sbin"
        self.sbin.mkdir(parents=True)
        self.stock = self.mount / "real/bin/busybox"
        self.hack = self.base / "hack-busybox"
        self.calls = self.base / "tool-calls"
        for path, label in [(self.stock, "stock"), (self.hack, "hack")]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#!/bin/sh\nprintf "%s:%s\\n" ' + label +
                            ' "${0##*/}" >> "$TOOL_CALLS"\n')
            path.chmod(0o755)
        for name in ("ifconfig", "udhcpc"):
            (self.sbin / name).symlink_to(self.hack)
        self.env = dict(os.environ, sd_mnt=str(self.mount), anyka_md5=EXACT_MD5,
                        ln=shutil.which("ln"), rm=shutil.which("rm"), TOOL_CALLS=str(self.calls),
                        PATH=str(self.sbin))

    def policy(self, expected=0):
        result = subprocess.run([*SHELL, "-c", FUNCTION + "\nconfigure_overlay_network_tools || exit 1\n"],
                                env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_exact_profile_restores_bare_path_commands_to_stock_busybox(self):
        self.policy()
        for name in ("ifconfig", "udhcpc"):
            alias = self.sbin / name
            self.assertTrue(alias.is_symlink())
            self.assertEqual(alias.resolve(), self.stock)
            # execvp-style lookup is deliberate: standalone BusyBox ash can
            # resolve its own applets even when a PATH alias is missing.
            # These executables are harmless fixtures, never network tools.
            result = subprocess.run([name, "fixture-argument"], env=self.env,
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text().splitlines(), ["stock:ifconfig", "stock:udhcpc"])

    def test_legacy_profile_keeps_existing_alias_removal(self):
        self.env["anyka_md5"] = "0123456789abcdef0123456789abcdef"
        self.policy()
        for name in ("ifconfig", "udhcpc"):
            self.assertFalse((self.sbin / name).exists())
            with self.assertRaises(FileNotFoundError):
                subprocess.run([name], env=self.env, timeout=5)
        self.assertFalse(self.calls.exists())

    def test_exact_profile_link_failure_stops_before_overlay_handoff(self):
        self.env["ln"] = shutil.which("false")
        result = self.policy(expected=1)
        self.assertIn("Cannot preserve stock network tool ifconfig", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_overlay_uses_policy_before_mounting_system_sbin(self):
        begin = INIT.index("# Prepare overlay filesystem")
        block = INIT[begin:INIT.index("# Copy shadow and passwd", begin)]
        self.assertLess(block.index("configure_overlay_network_tools || exit 1"),
                        block.index('$mount --bind $sd_mnt/override/sbin /sbin'))


if __name__ == "__main__":
    unittest.main()
