"""Offline YYOS kit packaging controls; no camera, card, network or firmware."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools/firmware-backup/build-yyos-kit.py"
spec = importlib.util.spec_from_file_location("yyos_backup_builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def check_sums(test, directory):
    names = set()
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        checksum, name = line.split("  ", 1)
        test.assertNotIn(name, names)
        names.add(name)
        test.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), checksum)
    return names


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="yyos-kit-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        (self.repo / "SOURCE/download").mkdir(parents=True)
        config = self.repo / "SOURCE/src/patches/busybox-fixture/uclibc-config"
        config.parent.mkdir(parents=True)
        config.write_text("CONFIG_STATIC=y\n")
        (self.repo / "SOURCE/Makefile").write_text(
            "BUSYBOX := busybox-fixture\nDOWNLOAD_URL := https://example.invalid/public\n")
        (self.repo / "LICENSE").write_text("MIT fixture notice\n")
        self.copying = b"GPL version 2 fixture notice\n"
        self.archive = self.repo / "SOURCE/download/busybox-fixture.tar.bz2"
        with tarfile.open(self.archive, "w:bz2") as archive:
            member = tarfile.TarInfo("busybox-fixture/LICENSE")
            member.size = len(self.copying)
            archive.addfile(member, io.BytesIO(self.copying))
        self.cc = self.root / "fixture-gcc"
        self.cc.write_text("#!/bin/sh\nexit 99\n")
        self.cc.chmod(0o755)
        self.readelf = self.root / "fixture-readelf"
        self.readelf.write_text("#!/bin/sh\nexit 99\n")
        self.readelf.chmod(0o755)
        self.busybox = self.root / "busybox"
        self.busybox.write_bytes(b"SYNTHETIC-BUSYBOX\0")
        self.busybox.chmod(0o755)
        self.output = self.root / "output"
        self.args = SimpleNamespace(output=self.output, cc=str(self.cc), readelf=str(self.readelf),
                                    busybox=self.busybox, qemu=None)
        self.addCleanup(patch.stopall)
        patch.object(builder, "REPO", self.repo).start()

    def compile(self, command, **kwargs):
        self.assertEqual(command[0], str(self.cc))
        self.assertTrue(set(builder.FLAGS).issubset(command))
        self.assertEqual(command[-3], str(builder.HERE / "hostapd.c"))
        destination = Path(command[-1])
        self.assertEqual(destination.name, "telnetd")
        destination.write_bytes(b"SYNTHETIC-ARM-LAUNCHER\0")
        return SimpleNamespace(returncode=0)

    def elf(self, path, readelf):
        self.assertEqual(readelf, self.readelf)
        return {"static": True, "cpu_arch": "v5TEJ", "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def build_fixture(self, compiler=None):
        with patch.object(builder.subprocess, "run", side_effect=compiler or self.compile), \
                patch.object(builder.NOR, "validate_arm_elf", side_effect=self.elf):
            return builder.build(self.args)

    def test_exact_inventory_checksums_and_source_provenance(self):
        self.output.mkdir()  # Empty existing directories are explicitly supported.
        self.build_fixture()
        self.assertEqual({p.name for p in self.output.iterdir()}, builder.PACKAGE_FILES | {"card"})
        card = self.output / "card"
        self.assertEqual({p.name for p in card.iterdir()}, builder.CARD_FILES)
        self.assertEqual((card / "yy_telnet_start").read_bytes(), b"")
        self.assertEqual((card / "dump.sh").read_bytes(), (builder.HERE / "backup-nor.sh").read_bytes())
        self.assertEqual((card / "busybox").read_bytes(), self.busybox.read_bytes())
        self.assertEqual((self.output / "COPYING.BusyBox").read_bytes(), self.copying)
        self.assertEqual(check_sums(self, card), builder.CARD_FILES - {"SHA256SUMS"})
        manifest = json.loads((self.output / "manifest.json").read_text())
        expected = (builder.PACKAGE_FILES - {"SHA256SUMS"}) | {"card/" + name for name in builder.CARD_FILES}
        self.assertEqual(check_sums(self, self.output), expected)
        for name, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(manifest["sources"]["hostapd.c"], builder.NOR.digest(builder.HERE / "hostapd.c"))
        self.assertEqual(manifest["busybox_repository_sources"]["archive_sha256"], builder.NOR.digest(self.archive))
        self.assertFalse(manifest["entry"]["starts_telnet_daemon"])
        self.assertTrue(manifest["entry"]["stock_hook_requires_confirmation"])
        self.assertNotIn(str(self.root), (self.output / "manifest.json").read_text())
        previous = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "empty"):
            self.build_fixture()
        self.assertEqual(previous, {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob("*") if p.is_file()})

    def test_refuses_nonempty_output_before_tool_execution(self):
        self.output.mkdir()
        marker = self.output / "keep"
        marker.write_bytes(b"KEEP\0")
        with patch.object(builder.NOR, "executable") as executable:
            with self.assertRaisesRegex(ValueError, "empty"):
                builder.build(self.args)
            executable.assert_not_called()
        self.assertEqual(marker.read_bytes(), b"KEEP\0")

    def test_refuses_symlink_output_and_ancestor(self):
        target = self.root / "target"
        target.mkdir()
        self.output.symlink_to(target, target_is_directory=True)
        for output in (self.output, self.output / "nested"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "symlink"):
                builder.validate_output(output)
        self.assertEqual(list(target.iterdir()), [])

    def test_refuses_mountpoint_and_regular_file(self):
        with self.assertRaisesRegex(ValueError, "mountpoint"):
            builder.validate_output(Path("/"))
        self.output.write_bytes(b"KEEP")
        with self.assertRaisesRegex(ValueError, "empty"):
            builder.validate_output(self.output)
        self.assertEqual(self.output.read_bytes(), b"KEEP")

    def test_compile_failure_retains_empty_output(self):
        self.output.mkdir()
        def failed(command, **kwargs):
            raise subprocess.CalledProcessError(1, command)
        with self.assertRaises(subprocess.CalledProcessError):
            self.build_fixture(failed)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertFalse(list(self.root.glob(".yyos-backup-build-*")))

    def test_concurrent_addition_is_not_removed(self):
        def concurrent(command, **kwargs):
            result = self.compile(command, **kwargs)
            self.output.mkdir()
            (self.output / "added-during-build").write_bytes(b"PRESERVE")
            return result
        with self.assertRaisesRegex(ValueError, "empty"):
            self.build_fixture(concurrent)
        self.assertEqual((self.output / "added-during-build").read_bytes(), b"PRESERVE")

    def test_rejects_unhydrated_or_nonregular_license_source(self):
        self.archive.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:fixture\n")
        with self.assertRaisesRegex(ValueError, "unhydrated"):
            builder.busybox_sources()
        with tarfile.open(self.archive, "w:bz2") as archive:
            member = tarfile.TarInfo("busybox-fixture/LICENSE")
            member.type = tarfile.SYMTYPE
            member.linkname = "../../private"
            archive.addfile(member)
        with self.assertRaisesRegex(ValueError, "license member"):
            builder.busybox_sources()
        self.assertFalse(self.output.exists())

    def test_output_argument_is_required(self):
        result = subprocess.run([os.sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--output", result.stderr)

    def test_real_arm926_build_is_reproducible_and_credential_free(self):
        cc, busybox, qemu = (os.environ.get(name) for name in ("BACKUP_ARM_CC", "BACKUP_ARM_BUSYBOX", "BACKUP_QEMU"))
        if not all((cc, busybox, qemu)):
            self.skipTest("Set BACKUP_ARM_CC, BACKUP_ARM_BUSYBOX and BACKUP_QEMU for real ARM926 build")
        args = SimpleNamespace(output=self.output, cc=cc, busybox=Path(busybox), readelf=None, qemu=qemu)
        with patch.object(builder, "REPO", REPO):
            builder.build(args)
            args.output = self.root / "second-output"
            builder.build(args)
        self.assertEqual({p.name for p in (self.output / "card").iterdir()}, builder.CARD_FILES)
        first = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        second = {str(p.relative_to(args.output)): p.read_bytes() for p in args.output.rglob("*") if p.is_file()}
        self.assertEqual(first, second)
        check_sums(self, self.output / "card")
        check_sums(self, self.output)
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertTrue(manifest["launcher"]["static"])
        self.assertIn(manifest["launcher"]["cpu_arch"], ("v5TE", "v5TEJ"))
        self.assertTrue(manifest["busybox_qemu_smoke"])
        self.assertTrue(manifest["collector_qemu_syntax"])


if __name__ == "__main__":
    unittest.main()
