#!/usr/bin/env python3
"""Packaging guards and optional real ARM build; no card or firmware inputs."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "tools/firmware-backup/build-kit.py"
spec = importlib.util.spec_from_file_location("backup_builder", SOURCE)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def arm_elf(machine=40, flags=0x05000200, segment=1):
    identification = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    header = struct.pack("<HHIIIIIHHHHHH", 2, machine, 1, 0, 52, 0, flags, 52, 32, 1, 0, 0, 0)
    return identification + header + struct.pack("<IIIIIIII", segment, 0, 0, 0, 0, 0, 5, 4096)


class BuildTests(unittest.TestCase):
    def test_accepts_static_armv5_attributes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "binary"
            path.write_bytes(arm_elf())
            with patch.object(builder.subprocess, "run", return_value=SimpleNamespace(stdout="Tag_CPU_arch: v5TEJ\n")):
                report = builder.validate_arm_elf(path, Path("fixture-readelf"))
            self.assertTrue(report["static"])
            self.assertEqual(report["cpu_arch"], "v5TEJ")

    def test_compiler_wrapper_preserves_invocation_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wrapper = directory / "toolchain-wrapper"
            wrapper.write_text("#!/bin/sh\nexit 0\n")
            wrapper.chmod(0o755)
            compiler = directory / "arm-fixture-gcc"
            compiler.symlink_to(wrapper.name)
            self.assertEqual(builder.executable(str(compiler)), compiler)

    def test_rejects_soft_float_abi_with_hardware_fp_instructions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "binary"
            path.write_bytes(arm_elf())
            report = "Tag_CPU_arch: v5TEJ\nTag_FP_arch: VFPv2\n"
            with patch.object(builder.subprocess, "run", return_value=SimpleNamespace(stdout=report)):
                with self.assertRaisesRegex(ValueError, "hardware floating-point"):
                    builder.validate_arm_elf(path, Path("fixture-readelf"))

    def test_refuses_unknown_output_without_removing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / "keep-this-file"
            marker.write_text("unchanged\n")
            with self.assertRaisesRegex(ValueError, "unknown files"):
                builder.validate_output(directory)
            self.assertEqual(marker.read_text(), "unchanged\n")

    def test_refuses_symlink_output_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / "target"
            target.mkdir()
            link = directory / "link"
            link.symlink_to(target.name, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                builder.validate_output(link / "output")
            self.assertEqual(list(target.iterdir()), [])

    def test_refuses_mountpoint_output(self):
        with self.assertRaisesRegex(ValueError, "mountpoint"):
            builder.validate_output(Path("/"))

    def test_real_arm_package_and_safe_rebuild(self):
        cc, busybox, qemu = (os.environ.get(key) for key in ("BACKUP_ARM_CC", "BACKUP_ARM_BUSYBOX", "BACKUP_QEMU"))
        if not all((cc, busybox, qemu)):
            self.skipTest("Set BACKUP_ARM_CC, BACKUP_ARM_BUSYBOX and BACKUP_QEMU for package build")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "kit"
            args = SimpleNamespace(cc=cc, busybox=Path(busybox), qemu=qemu, readelf=None, output=output)
            builder.build(args)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertTrue(manifest["busybox_qemu_smoke"])
            self.assertTrue(manifest["launcher"]["static"])
            self.assertEqual({path.name for path in (output / "card").iterdir()}, builder.CARD_FILES)
            self.assertEqual((output / "card/_ht_ap_mode.conf").stat().st_size, 0)
            self.assertEqual((output / "card/_ht_get_log.conf").stat().st_size, 0)
            builder.build(args)
            self.assertEqual(json.loads((output / "manifest.json").read_text()), manifest)
            (output / "keep-this-file").write_bytes(b"unchanged")
            with self.assertRaisesRegex(ValueError, "unknown files"):
                builder.build(args)
            self.assertEqual((output / "keep-this-file").read_bytes(), b"unchanged")


INVALID_BINARIES = {
    "host_machine": (arm_elf(machine=62), "v5TEJ"),
    "hard_float": (arm_elf(flags=0x05000400), "v5TEJ"),
    "old_eabi": (arm_elf(flags=0x04000200), "v5TEJ"),
    "dynamic_segment": (arm_elf(segment=2), "v5TEJ"),
    "interpreter_segment": (arm_elf(segment=3), "v5TEJ"),
    "truncated_headers": (arm_elf()[:60], "v5TEJ"),
    "newer_cpu": (arm_elf(), "v7"),
    "missing_attributes": (arm_elf(), ""),
}


def add_case(name, data, architecture):
    def test(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "binary"
            path.write_bytes(data)
            with patch.object(builder.subprocess, "run", return_value=SimpleNamespace(stdout="Tag_CPU_arch: " + architecture + "\n")):
                with self.assertRaises(ValueError):
                    builder.validate_arm_elf(path, Path("fixture-readelf"))
    setattr(BuildTests, "test_rejects_" + name, test)


for name, (data, architecture) in INVALID_BINARIES.items():
    add_case(name, data, architecture)

if __name__ == "__main__":
    unittest.main()
