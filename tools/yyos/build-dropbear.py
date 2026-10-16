#!/usr/bin/env python3
"""Build the pinned, key-only YYOS SSH server without touching a card or camera."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shutil
import struct
import subprocess
import sys
import tarfile
import time

VERSION = "2026.94"
SOURCE_URL = f"https://matt.ucc.asn.au/dropbear/releases/dropbear-{VERSION}.tar.bz2"
SOURCE_SHA256 = "e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81"
SOURCE_LIMIT = 4 * 1024 * 1024
EXTRACT_LIMIT = 32 * 1024 * 1024
MEMBER_LIMIT = 2000
CONFIG_NAME = "dropbear-localoptions.h"
CONFIG_SHA256 = "972166708b2793d1090f15a668d9afe9ad3aa6f358539bb3c3d91992edfcf745"
CONFIGURE_FLAGS = [
    "--host=arm-buildroot-linux-uclibcgnueabi", "--enable-static",
    "--disable-zlib", "--disable-syslog", "--disable-shadow",
    "--disable-lastlog", "--disable-utmp", "--disable-utmpx",
    "--disable-wtmp", "--disable-wtmpx", "--disable-loginfunc",
    "--disable-pututline", "--disable-pututxline", "--enable-bundled-libtom",
]
CFLAGS = "-Os -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -ffunction-sections -fdata-sections"
LDFLAGS = "-Wl,--gc-sections"
REPO = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def verify_source(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("source must be a regular file")
    if not 0 < path.stat().st_size <= SOURCE_LIMIT:
        raise ValueError("source archive exceeds size limit")
    if digest(path) != SOURCE_SHA256:
        raise ValueError("source archive SHA256 does not match the pinned official release")


def unpack_source(archive: Path, destination: Path) -> Path:
    expected = f"dropbear-{VERSION}"
    with tarfile.open(archive, "r:bz2") as tar:
        members = tar.getmembers()
        if len(members) > MEMBER_LIMIT or sum(x.size for x in members) > EXTRACT_LIMIT:
            raise ValueError("source archive exceeds extraction limits")
        names: set[str] = set()
        for item in members:
            name = PurePosixPath(item.name)
            if (name.is_absolute() or ".." in name.parts or not name.parts
                    or name.parts[0] != expected or str(name) in names
                    or not (item.isfile() or item.isdir()) or item.size < 0):
                raise ValueError("unsafe or unexpected archive member")
            names.add(str(name))
        for item in members:
            path = destination.joinpath(*PurePosixPath(item.name).parts)
            if item.isdir():
                path.mkdir(mode=0o755, parents=True, exist_ok=True)
            else:
                path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                source = tar.extractfile(item)
                if source is None:
                    raise ValueError("source member could not be read")
                with source, path.open("xb") as stream:
                    shutil.copyfileobj(source, stream)
                path.chmod(0o755 if item.mode & 0o111 else 0o644)
    return destination / expected


def run_logged(command: list[str], cwd: Path, log: Path, timeout: int) -> None:
    with log.open("xb") as stream:
        child = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            code = child.wait(timeout=timeout)
        except BaseException:
            # A timed-out make/configure can have compiler children. Stop its whole group.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            raise
    if code:
        raise RuntimeError(f"{log.name} failed with exit code {code}")


def check_elf(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("build output is not little-endian ELF32")
    kind, machine = struct.unpack_from("<HH", data, 16)
    phoff = struct.unpack_from("<I", data, 28)[0]
    flags = struct.unpack_from("<I", data, 36)[0]
    phsize, phcount = struct.unpack_from("<HH", data, 42)
    if kind != 2 or machine != 40 or flags & 0xFF000000 != 0x05000000 or not flags & 0x200:
        raise ValueError("build output is not ARM EABI5 soft-float executable")
    if flags & 0x400 or phsize < 32 or phoff + phsize * phcount > len(data):
        raise ValueError("unexpected ELF flags or program header layout")
    if any(struct.unpack_from("<I", data, phoff + index * phsize)[0] in (2, 3)
           for index in range(phcount)):
        raise ValueError("expected static output without dynamic loader or shared libraries")
    return {"class": "ELF32", "machine": "ARM", "eabi": 5,
            "float_abi": "soft", "static": True, "bytes": len(data)}


def license_bundle(source: Path, output: Path) -> None:
    chunks = []
    for relative in ("LICENSE", "libtomcrypt/LICENSE", "libtommath/LICENSE"):
        chunks.append(f"===== Dropbear {VERSION} {relative} =====\n" + (source / relative).read_text())
    for relative in ("src/mlkem768.c", "src/libcrux_mlkem768_sha3.h", "src/sntrup761.c",
                     "src/ed25519.c", "src/sshpty.c", "src/atomicio.c"):
        text = (source / relative).read_text()
        notices = [part for part in re.findall(r"/\*.*?\*/", text, re.DOTALL)
                   if re.search(r"copyright|license|public domain|authors", part, re.IGNORECASE)]
        if not notices:
            raise ValueError("expected upstream license notice is missing")
        # libcrux starts with a separate OpenBSD marker and has later SPDX notices.
        chunks.append(f"===== Dropbear {VERSION} {relative} notices =====\n" + "\n\n".join(notices))
    output.write_text("\n\n".join(chunks) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path,
                        help="official dropbear-2026.94.tar.bz2 (pinned SHA256 checked before extraction)")
    parser.add_argument("--output", required=True, type=Path, help="new directory; existing outputs are never overwritten")
    parser.add_argument("--toolchain-prefix", type=Path,
                        default=REPO / "SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi")
    parser.add_argument("--qemu", type=Path, help="qemu-arm for ARM926 smoke checks")
    parser.add_argument("--skip-qemu", action="store_true", help="build only; provenance explicitly records untested emulation")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error("--jobs must be between 1 and 32")
    if args.qemu and args.skip_qemu:
        parser.error("--qemu and --skip-qemu cannot be combined")
    # Allocate once, before a subprocess or extraction; a failed directory stays for inspection.
    output = args.output.absolute()
    if output.is_symlink() or not output.parent.is_dir():
        parser.error("output parent must exist, and output cannot be a symlink")
    try:
        output.mkdir(mode=0o700)
    except FileExistsError:
        parser.error("output already exists; choose a fresh directory")
    started = time.monotonic()
    stage = "inputs"
    try:
        archive = args.source.absolute()
        verify_source(archive)
        prefix = args.toolchain_prefix.absolute()
        tool = {name: Path(str(prefix) + "-" + name) for name in
                ("gcc", "ar", "ranlib", "strip", "readelf")}
        if any(not path.is_file() or not os.access(path, os.X_OK) for path in tool.values()):
            raise ValueError("complete executable ARM toolchain prefix required")
        qemu = args.qemu
        if not args.skip_qemu:
            qemu = qemu or Path(shutil.which("qemu-arm") or REPO / ".local/tools/root/usr/bin/qemu-arm")
            qemu = qemu.absolute()
            if not qemu.is_file() or not os.access(qemu, os.X_OK):
                raise ValueError("qemu-arm is required; install it or explicitly use --skip-qemu")
        config = Path(__file__).with_name(CONFIG_NAME)
        if config.is_symlink() or not config.is_file():
            raise ValueError("companion compile configuration must be a regular file")
        if digest(config) != CONFIG_SHA256:
            raise ValueError("companion configuration differs from the audited key-only build")
        retained_archive = output / f"dropbear-{VERSION}.tar.bz2"
        shutil.copyfile(archive, retained_archive)
        if digest(retained_archive) != SOURCE_SHA256:
            raise ValueError("copied source hash mismatch")
        stage = "extract"
        source = unpack_source(retained_archive, output)
        build = output / "build-arm"
        build.mkdir()
        shutil.copyfile(config, build / "localoptions.h")
        stage = "configure"
        run_logged([str(tool["gcc"]), "--version"], build, output / "compiler-version.log", 20)
        command = [str(source / "configure"), *CONFIGURE_FLAGS,
                   f"CC={tool['gcc']}", f"AR={tool['ar']}", f"RANLIB={tool['ranlib']}",
                   f"STRIP={tool['strip']}", f"CFLAGS={CFLAGS}", f"LDFLAGS={LDFLAGS}"]
        # Relative source layout also keeps __FILE__ strings consistent between builds.
        command[0] = f"../dropbear-{VERSION}/configure"
        run_logged(command, build, output / "configure.log", 180)
        stage = "make"
        run_logged(["make", f"-j{args.jobs}", "PROGRAMS=dropbear dropbearkey", "MULTI=1"],
                   build, output / "make.log", 600)
        stage = "artifact"
        binary = build / "dropbearmulti"
        run_logged([str(tool["strip"]), str(binary)], build, output / "strip.log", 30)
        elf = check_elf(binary)
        (output / "bin").mkdir()
        shutil.copyfile(binary, output / "bin/dropbear")
        (output / "bin/dropbear").chmod(0o755)
        # One multicall binary also implements dropbearkey; keys are generated by the owner separately.
        run_logged([str(tool["readelf"]), "-h", "-A", "-l", str(binary)], build,
                   output / "elf-report.txt", 30)
        license_bundle(source, output / "DROPBEAR-LICENSES.txt")
        stage = "qemu"
        emulation = {"performed": not args.skip_qemu, "cpu": "arm926", "passed": False}
        if not args.skip_qemu:
            run_logged([str(qemu), "-cpu", "arm926", str(output / "bin/dropbear"), "-V"],
                       build, output / "qemu-version.log", 20)
            if (output / "qemu-version.log").read_text().strip() != f"Dropbear v{VERSION}":
                raise ValueError("unexpected emulated Dropbear version")
            for feature in ("sig", "kex", "cipher", "mac"):
                run_logged([str(qemu), "-cpu", "arm926", str(binary), "dropbear", "-Q", feature],
                           build, output / f"qemu-{feature}.log", 20)
            if (output / "qemu-sig.log").read_text().strip() != "ssh-ed25519":
                raise ValueError("build unexpectedly permits another signing algorithm")
            emulation["passed"] = True
        provenance = {
            "schema": 1, "version": VERSION, "source_url": SOURCE_URL,
            "source_archive_sha256": SOURCE_SHA256, "binary_sha256": digest(binary),
            "build_script_sha256": digest(Path(__file__)),
            "binary_bytes": binary.stat().st_size, "elf": elf,
            "configure_flags": CONFIGURE_FLAGS, "cflags": CFLAGS, "ldflags": LDFLAGS,
            "make_args": ["PROGRAMS=dropbear dropbearkey", "MULTI=1"],
            "compiler_version": (output / "compiler-version.log").read_text().splitlines()[0],
            "localoptions_sha256": digest(config), "localoptions": config.read_text(),
            "applet_names": ["dropbear", "dropbearkey"], "qemu": emulation,
            "camera_contacted": False, "keys_generated": False,
            "password_authentication_compiled": False, "shadow_support_compiled": False,
            "sftp_compiled": False, "forwarding_compiled": False,
            "syslog_cli_note": "Omit -E: stderr is already default with --disable-syslog; -s/-j/-k accepted as no-ops.",
            "static_libc_distribution_note": "Retain the source and relinkable build objects, and supply libc license/source obligations before redistribution.",
        }
        write_json(output / "provenance.json", provenance)
        write_json(output / "result.json", {"ok": True, "stage": "complete",
                   "elapsed_seconds": round(time.monotonic() - started, 3),
                   "binary_sha256": provenance["binary_sha256"]})
        print(json.dumps({"ok": True, "version": VERSION, "binary_sha256": provenance["binary_sha256"],
                          "binary_bytes": provenance["binary_bytes"], "qemu_passed": emulation["passed"]}))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
        write_json(output / "result.json", {"ok": False, "stage": stage,
                   "elapsed_seconds": round(time.monotonic() - started, 3), "error": str(error)})
        print(f"Build failed at {stage}; output and logs retained: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
