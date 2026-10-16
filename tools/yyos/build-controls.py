#!/usr/bin/env python3
"""Build the exact-profile YYOS native controls helper; never contacts a camera."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
VERSION = "1"
SOURCE_SHA256 = "e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81"
BRIDGE_SHA256 = "01be10422aed1f6de44fad26c1c5135d129cc29ab57bb3ad005cd14507eeb927"
CLOCK_SHA256 = "f3f3c87472abbaf78756f8245416b980b63e2e733b2c95072c5a71a2a5514655"
CFLAGS = ["-Os", "-march=armv5te", "-mtune=arm926ej-s", "-mfloat-abi=soft",
          "-ffunction-sections", "-fdata-sections", "-Wall", "-Wextra", "-Werror"]
DEFINITIONS = ["LTC_NOTHING", "LTC_NO_MATH", "LTC_RIJNDAEL", "LTC_GCM_MODE",
               "LTC_HMAC", "LTC_SHA256", "LTC_NO_FILE", "LTC_NO_TEST",
               "LTC_CLEAN_STACK", "LTC_NO_ASM", "LTC_NO_FAST", "LTC_SOURCE",
               "LTC_HASH_HELPERS"]
CRYPTO_SOURCES = ["ciphers/aes/aes.c", "hashes/sha2/sha256.c",
                  "hashes/helper/hash_memory.c", "misc/zeromem.c",
                  "misc/burn_stack.c", "misc/mem_neq.c"]
CRYPTO_SOURCES += [f"misc/crypt/{name}.c" for name in
                   ("crypt_register_cipher", "crypt_register_hash",
                    "crypt_cipher_descriptor", "crypt_hash_descriptor",
                    "crypt_cipher_is_valid", "crypt_hash_is_valid", "crypt_argchk")]
CRYPTO_SOURCES += [f"mac/hmac/{name}.c" for name in
                   ("hmac_init", "hmac_process", "hmac_done", "hmac_memory")]
CRYPTO_SOURCES += [f"encauth/gcm/{name}.c" for name in
                   ("gcm_init", "gcm_reset", "gcm_add_iv", "gcm_add_aad",
                    "gcm_process", "gcm_done", "gcm_gf_mult", "gcm_mult_h", "gcm_memory")]
ALLOCATOR_ORIGINAL = ('#include "tomcrypt_dropbear.h"\n\n#include "dbmalloc.h"\n'
                      '#define XMALLOC m_malloc\n#define XFREE m_free_direct\n'
                      '#define XREALLOC m_realloc\n#define XCALLOC m_calloc\n')
ALLOCATOR_REPLACEMENT = "/* Standalone libc allocation; no Dropbear configuration or allocator hooks. */\n"
ZERO_ORIGINAL = "m_burn((void*)out, outlen);"
ZERO_REPLACEMENT = "volatile unsigned char *cursor = out;\n   while (outlen--) *cursor++ = 0;"


def helpers():
    path = Path(__file__).with_name("build-dropbear.py")
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular companion build-dropbear.py is required")
    spec = importlib.util.spec_from_file_location("yyos_controls_build_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def patch_crypto(source: Path) -> list[dict]:
    """Only allocator integration changes; AES/GCM/HMAC/SHA algorithms untouched."""
    header = source / "src/headers/tomcrypt_custom.h"
    zero = source / "src/misc/zeromem.c"
    reports = []
    for path, replacements in (
        (header, [(ALLOCATOR_ORIGINAL, ALLOCATOR_REPLACEMENT)]),
        (zero, [('#include "dbhelpers.h"', ""), (ZERO_ORIGINAL, ZERO_REPLACEMENT)]),
    ):
        original = digest(path)
        text = path.read_text()
        for old, new in replacements:
            if text.count(old) != 1:
                raise ValueError("pinned LibTomCrypt integration anchor differs")
            text = text.replace(old, new)
        path.write_text(text)
        reports.append({"file": path.relative_to(source).as_posix(),
                        "original_sha256": original, "patched_sha256": digest(path),
                        "replacements": [{"original": a, "replacement": b}
                                         for a, b in replacements]})
    return reports


def license_bundle(source: Path, musl: Path, destination: Path) -> None:
    sections = [("LSCamoflash MIT license", REPO / "LICENSE"),
                ("Pinned LibTomCrypt license", source / "libtomcrypt/LICENSE")]
    sections += [("Static runtime " + name, musl / name)
                 for name in ("COPYING.musl", "GCC-COPYING3", "GCC-COPYING.RUNTIME")]
    with destination.open("x") as output:
        for label, path in sections:
            if path.is_symlink() or not path.is_file():
                raise ValueError("required controls license notice is missing")
            output.write(f"===== {label} =====\n{path.read_text()}\n\n")
        output.write("Only the listed LibTomCrypt AES/GCM/HMAC/SHA256 support sources are linked. "
                     "Full pinned source, integration patches and relinkable objects are retained.\n")


def build(args) -> dict:
    h = helpers()
    output = args.output.absolute()
    if any(p.is_symlink() for p in (output, *output.parents)) or not output.parent.is_dir():
        raise ValueError("existing output parent without symlink ancestors required")
    output.mkdir(mode=0o700)  # Never overwrite an unknown or failed build.
    stage = "inputs"
    started = time.monotonic()
    try:
        archive = args.source.absolute()
        h.verify_source(archive)
        compiler, libc = h.validate_musl(args.musl_build.absolute())
        prefix = args.toolchain_prefix.absolute()
        tools = {name: Path(str(prefix) + "-" + name)
                 for name in ("ar", "strip", "readelf")}
        if any(not p.is_file() or not os.access(p, os.X_OK) for p in tools.values()):
            raise ValueError("complete executable ARM toolchain is required")
        bridge = REPO / "SOURCE/src/contrib/yyos-controls/yyos_controls.c"
        clock = Path(__file__).with_name("yyos-clock-compat.c")
        for path, expected in ((bridge, BRIDGE_SHA256), (clock, CLOCK_SHA256)):
            if path.is_symlink() or not path.is_file() or digest(path) != expected:
                raise ValueError("audited controls/clock source hash differs")
        qemu = args.qemu.absolute()
        if not qemu.is_file() or not os.access(qemu, os.X_OK):
            raise ValueError("qemu-arm is required for the ARM926 execution guard")
        for name in ("sources", "objects", "bin", "logs"):
            (output / name).mkdir()
        retained = output / "dropbear-2026.94.tar.bz2"
        shutil.copyfile(archive, retained)
        h.verify_source(retained)
        shutil.copyfile(bridge, output / "sources/yyos_controls.c")
        shutil.copyfile(clock, output / "sources/yyos-clock-compat.c")
        for name in ("build-controls.py", "build-dropbear.py", "build-musl.py"):
            shutil.copyfile(Path(__file__).with_name(name), output / "sources" / name)
        musl_root = args.musl_build.absolute()
        shutil.copyfile(musl_root / "musl-1.2.6.tar.gz", output / "sources/musl-1.2.6.tar.gz")
        shutil.copyfile(musl_root / "provenance.json", output / "sources/musl-provenance.json")
        stage = "extract_and_patch"
        source = h.unpack_source(retained, output)
        crypto = source / "libtomcrypt"
        patches = patch_crypto(crypto)
        write_json(output / "sources/crypto-patches.json", patches)
        h.run_logged([str(compiler), "--version"], output, output / "logs/compiler-version.txt", 20)
        include = "-Idropbear-2026.94/libtomcrypt/src/headers"
        flags = [*CFLAGS, *("-D" + name for name in DEFINITIONS), include]
        objects = []
        stage = "compile_crypto"
        for index, name in enumerate(CRYPTO_SOURCES):
            src = "dropbear-2026.94/libtomcrypt/src/" + name
            obj = f"objects/crypto-{index:02d}.o"
            h.run_logged([str(compiler), *flags, "-c", src, "-o", obj], output,
                         output / f"logs/crypto-{index:02d}.log", 60)
            objects.append({"source": src, "source_sha256": digest(output / src),
                            "object": obj, "object_sha256": digest(output / obj)})
        h.run_logged([str(tools["ar"]), "rcsD", "objects/libyyoscrypto.a",
                      *(item["object"] for item in objects)], output,
                     output / "logs/archive.log", 30)
        stage = "compile_bridge"
        for name, src, extra in (("controls", "sources/yyos_controls.c", flags),
                                 ("clock", "sources/yyos-clock-compat.c", CFLAGS)):
            obj = f"objects/{name}.o"
            h.run_logged([str(compiler), *extra, "-c", src, "-o", obj], output,
                         output / f"logs/{name}.log", 60)
            objects.append({"source": src, "source_sha256": digest(output / src),
                            "object": obj, "object_sha256": digest(output / obj)})
        stage = "link"
        h.run_logged([str(compiler), "-static", "-Wl,--gc-sections", "objects/controls.o",
                      "objects/clock.o", "objects/libyyoscrypto.a", "-o", "objects/yyos-controls-unstripped"],
                     output, output / "logs/link.log", 60)
        binary = output / "bin/yyos-controls"
        shutil.copyfile(output / "objects/yyos-controls-unstripped", binary)
        h.run_logged([str(tools["strip"]), "--strip-all", "bin/yyos-controls"], output,
                     output / "logs/strip.log", 30)
        binary.chmod(0o755)
        elf = h.check_elf(binary)
        h.run_logged([str(tools["readelf"]), "-h", "-A", "-l", "bin/yyos-controls"],
                     output, output / "logs/elf.txt", 30)
        if not re.search(r"Tag_CPU_arch:\s+v5TE(?:J)?\b", (output / "logs/elf.txt").read_text()):
            raise ValueError("expected ARMv5TE architecture attributes")
        if b"0123456789abcdef" in binary.read_bytes() or b"YYOS_FIXTURE_" in binary.read_bytes():
            raise ValueError("fixture-only key or hooks found in production binary")
        stage = "arm926_execution"
        # Invalid CLI is deliberately rejected before identity/key/network access.
        run = subprocess.run([str(qemu), "-cpu", "arm926", str(binary), "invalid-interface"],
                             stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
        if run.returncode != 2 or run.stdout or run.stderr:
            raise ValueError("ARM926 production interface refusal did not pass")
        license_bundle(source, musl_root, output / "COPYING.Controls")
        provenance = {
            "schema": 1, "name": "yyos-controls", "version": VERSION,
            "binary_sha256": digest(binary), "binary_bytes": binary.stat().st_size,
            "source_archive_sha256": SOURCE_SHA256,
            "source_url": h.SOURCE_URL, "bridge_source_sha256": BRIDGE_SHA256,
            "build_script_sha256": digest(Path(__file__)),
            "build_helper_sha256": digest(Path(__file__).with_name("build-dropbear.py")),
            "clock_compat_sha256": CLOCK_SHA256, "libc": libc,
            "static_libc_version": "musl1.2.6", "elf": elf, "cflags": CFLAGS,
            "crypto_definitions": DEFINITIONS, "crypto_patches": patches,
            "crypto_archive_sha256": digest(output / "objects/libyyoscrypto.a"),
            "objects": objects, "license_sha256": digest(output / "COPYING.Controls"),
            "compiler_version": (output / "logs/compiler-version.txt").read_text().splitlines()[0],
            "qemu": {"passed": True, "cpu": "arm926", "check": "production invalid-interface exit2 before network"},
            "test_fixture_compiled": False, "keys_generated": False, "camera_contacted": False,
            "endpoint": "127.0.0.1:6668", "jog_ms": 200,
            "allowlist": {"indicator": 101, "timestamp_osd": 104, "stop": 116,
                          "jog_cardinals": {"up": "0", "right": "2", "down": "4", "left": "6"}},
            "physical_hard_deadline_proven": False,
            "source_distribution": "Retain pinned archives, sources, exact patch records, objects and COPYING.Controls.",
        }
        write_json(output / "provenance.json", provenance)
        write_json(output / "result.json", {"ok": True, "stage": "complete",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "binary_sha256": provenance["binary_sha256"]})
        return provenance
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        write_json(output / "result.json", {"ok": False, "stage": stage,
                    "elapsed_seconds": round(time.monotonic() - started, 3), "error": str(error)})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="pinned official dropbear-2026.94.tar.bz2")
    parser.add_argument("--musl-build", required=True, type=Path, help="complete tested build-musl.py output")
    parser.add_argument("--output", required=True, type=Path, help="new output directory, never overwritten")
    parser.add_argument("--toolchain-prefix", type=Path,
                        default=REPO / "SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi")
    parser.add_argument("--qemu", type=Path,
                        default=Path(shutil.which("qemu-arm") or REPO / ".local/tools/root/usr/bin/qemu-arm"))
    args = parser.parse_args()
    try:
        proof = build(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Controls build failed; new output/logs retained: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "binary_sha256": proof["binary_sha256"],
                      "binary_bytes": proof["binary_bytes"], "qemu_passed": proof["qemu"]["passed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
