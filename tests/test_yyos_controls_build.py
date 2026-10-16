#!/usr/bin/env python3
"""Offline builder integrity checks; no downloads, camera or SD-card actions."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("yyos_controls_builder", REPO / "tools/yyos/build-controls.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class ControlsBuilderTests(unittest.TestCase):
    def test_audited_companions_match(self):
        self.assertEqual(BUILDER.digest(REPO / "SOURCE/src/contrib/yyos-controls/yyos_controls.c"),
                         BUILDER.BRIDGE_SHA256)
        self.assertEqual(BUILDER.digest(REPO / "tools/yyos/yyos-clock-compat.c"), BUILDER.CLOCK_SHA256)

    def test_minimal_crypto_configuration_is_consistent(self):
        self.assertEqual(len(BUILDER.CRYPTO_SOURCES), 26)
        self.assertEqual(len(set(BUILDER.CRYPTO_SOURCES)), 26)
        for feature in ("LTC_NOTHING", "LTC_RIJNDAEL", "LTC_GCM_MODE", "LTC_HMAC", "LTC_SHA256",
                        "LTC_CLEAN_STACK", "LTC_NO_FAST", "LTC_NO_ASM"):
            self.assertIn(feature, BUILDER.DEFINITIONS)
        self.assertNotIn("YYOS_TEST_FIXTURE", " ".join(BUILDER.DEFINITIONS + BUILDER.CFLAGS))

    def test_exact_allocator_and_wipe_patches_preserve_algorithms(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            header = source / "src/headers/tomcrypt_custom.h"
            zero = source / "src/misc/zeromem.c"
            aes = source / "src/ciphers/aes/aes.c"
            for path in (header, zero, aes):
                path.parent.mkdir(parents=True, exist_ok=True)
            header.write_text("before\n" + BUILDER.ALLOCATOR_ORIGINAL + "after\n")
            zero.write_text('#include "dbhelpers.h"\nvoid test(void) {' + BUILDER.ZERO_ORIGINAL + '}\n')
            aes.write_text("synthetic unchanged algorithm marker\n")
            original = BUILDER.digest(aes)
            records = BUILDER.patch_crypto(source)
            self.assertEqual(len(records), 2)
            self.assertNotIn("dbmalloc.h", header.read_text())
            self.assertNotIn("tomcrypt_dropbear.h", header.read_text())
            self.assertNotIn("m_burn", zero.read_text())
            self.assertIn("volatile unsigned char", zero.read_text())
            self.assertEqual(BUILDER.digest(aes), original)
            for record in records:
                self.assertEqual(BUILDER.digest(source / record["file"]), record["patched_sha256"])

    def test_unexpected_upstream_patch_anchor_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            header = source / "src/headers/tomcrypt_custom.h"
            header.parent.mkdir(parents=True)
            header.write_text("unexpected upstream contents\n")
            with self.assertRaisesRegex(ValueError, "anchor differs"):
                BUILDER.patch_crypto(source)
            self.assertEqual(header.read_text(), "unexpected upstream contents\n")

    def test_bad_source_retains_new_failure_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "bad-source.tar.bz2"
            source.write_bytes(b"bad archive")
            output = directory / "failed"
            args = argparse.Namespace(output=output, source=source,
                musl_build=directory / "not-used", toolchain_prefix=directory / "not-used", qemu=directory / "not-used")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                BUILDER.build(args)
            record = json.loads((output / "result.json").read_text())
            self.assertFalse(record["ok"])
            self.assertEqual(record["stage"], "inputs")
            self.assertEqual(source.read_bytes(), b"bad archive")

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            sentinel = output / "unknown-owner.txt"
            sentinel.write_text("keep\n")
            with self.assertRaises(FileExistsError):
                BUILDER.build(argparse.Namespace(output=output))
            self.assertEqual(sentinel.read_text(), "keep\n")
            self.assertFalse((output / "result.json").exists())

    def test_symlink_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            actual = directory / "actual"
            actual.mkdir()
            link = directory / "link"
            link.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                BUILDER.build(argparse.Namespace(output=link))
            self.assertEqual(list(actual.iterdir()), [])

    def test_completed_build_has_source_object_and_license_proof(self):
        location = os.environ.get("YYOS_CONTROLS_BUILD")
        if not location:
            self.skipTest("set YYOS_CONTROLS_BUILD to inspect a complete public production build")
        output = Path(location)
        proof = json.loads((output / "provenance.json").read_text())
        self.assertEqual(proof["name"], "yyos-controls")
        self.assertFalse(proof["test_fixture_compiled"])
        self.assertFalse(proof["camera_contacted"])
        self.assertEqual(BUILDER.digest(output / "bin/yyos-controls"), proof["binary_sha256"])
        self.assertEqual(BUILDER.digest(output / "COPYING.Controls"), proof["license_sha256"])
        self.assertEqual(len(proof["objects"]), 28)
        for record in proof["objects"]:
            self.assertEqual(BUILDER.digest(output / record["source"]), record["source_sha256"])
            self.assertEqual(BUILDER.digest(output / record["object"]), record["object_sha256"])
        self.assertEqual(BUILDER.digest(output / "objects/libyyoscrypto.a"), proof["crypto_archive_sha256"])
        binary = (output / "bin/yyos-controls").read_bytes()
        self.assertNotIn(b"0123456789abcdef", binary)
        self.assertNotIn(b"YYOS_FIXTURE_", binary)
        self.assertEqual({p.name for p in (output / "bin").iterdir()}, {"yyos-controls"})


if __name__ == "__main__":
    unittest.main()
