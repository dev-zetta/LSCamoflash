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
CLOCK_COMPAT_SHA256 = "f3f3c87472abbaf78756f8245416b980b63e2e733b2c95072c5a71a2a5514655"
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
    environment = os.environ.copy()
    for name in ("REALGCC", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH"):
        environment.pop(name, None)
    with log.open("xb") as stream:
        child = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True, env=environment)
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


def validate_musl(root: Path) -> tuple[Path, dict]:
    """Accept a complete pinned builder output, not an arbitrary compiler override."""
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("musl build must not contain symlink ancestors")
    path = root / "provenance.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("bounded regular musl provenance required")
    proof = json.loads(path.read_text())
    archive = root / "musl-1.2.6.tar.gz"
    pinned = "d585fd3b613c66151fc3249e8ed44f77020cb5e6c1e635a616d3f9f82460512a"
    if (proof.get("schema") != 1 or proof.get("name") != "musl" or proof.get("version") != "1.2.6"
            or proof.get("source_archive_sha256") != pinned or not proof.get("qemu", {}).get("passed")
            or archive.is_symlink() or digest(archive) != pinned):
        raise ValueError("pinned ARM926-tested musl build required")
    files = proof.get("install_files", {})
    if not isinstance(files, dict) or len(files) > 1000 or not {
            "bin/musl-gcc", "lib/libc.a", "lib/crt1.o", "include/stdio.h"} <= files.keys():
        raise ValueError("musl installation inventory is incomplete")
    actual = set()
    for index, item in enumerate((root / "install").rglob("*")):
        if index >= 2000 or item.is_symlink() or not (item.is_dir() or item.is_file()):
            raise ValueError("unexpected musl installation entry")
        if item.is_file():
            actual.add(item.relative_to(root / "install").as_posix())
    if actual != set(files):
        raise ValueError("musl installation contains unproven or missing files")
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("unsafe musl installation inventory")
        item = root / "install" / name
        if (any(p.is_symlink() for p in (item, *item.parents)) or not item.is_file()
                or digest(item) != expected):
            raise ValueError("musl installation differs from build provenance")
    for name, expected in {"COPYING.musl": proof.get("license_sha256"),
                           **proof.get("gcc_runtime_notices", {})}.items():
        if name not in {"COPYING.musl", "GCC-COPYING3", "GCC-COPYING.RUNTIME"}:
            raise ValueError("unexpected libc license filename")
        item = root / name
        if item.is_symlink() or not item.is_file() or digest(item) != expected:
            raise ValueError("libc license differs from build provenance")
    if set(proof.get("gcc_runtime_notices", {})) != {"GCC-COPYING3", "GCC-COPYING.RUNTIME"}:
        raise ValueError("GCC runtime license notices missing")
    return root / "install/bin/musl-gcc", {
        "name": "musl", "version": "1.2.6", "source_archive_sha256": pinned,
        "license_sha256": proof["license_sha256"], "provenance_sha256": digest(path),
        "gcc_runtime_notices": proof["gcc_runtime_notices"],
    }


def patch_clock_fallback(source: Path) -> dict:
    """The musl YYOS build must fail closed if its monotonic clock is unavailable."""
    path = source / "src/dbutil.c"
    text = path.read_text()
    original = digest(path)
    anchor = "void gettime_wrapper(struct timespec *now) {\n\tstruct timeval tv;\n"
    if text.count(anchor) != 1:
        raise ValueError("unexpected upstream clock wrapper")
    addition = '''#if defined(LSCAMOFLASH_YYOS_CLOCK_COMPAT)
    /* The exact YYOS kernel has broken time64 stubs. Never fall back to a
     * time32 syscall into a libc time64 struct, or to wall-clock deadlines. */
    if (clock_gettime(CLOCK_MONOTONIC, now) != 0 || now->tv_sec < 0
            || now->tv_nsec < 0 || now->tv_nsec >= 1000000000)
        dropbear_exit("YYOS monotonic clock unavailable");
    return;
#endif
'''
    path.write_text(text.replace(anchor, anchor + addition))
    return {"file": "src/dbutil.c", "original_sha256": original,
            "patched_sha256": digest(path), "monotonic_failure": "exit, no raw or wall-clock fallback"}


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
    parser.add_argument("--musl-build", type=Path, help="complete build-musl.py output for a redistributable static musl server")
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error("--jobs must be between 1 and 32")
    if args.qemu and args.skip_qemu:
        parser.error("--qemu and --skip-qemu cannot be combined")
    # Allocate once, before a subprocess or extraction; a failed directory stays for inspection.
    output = args.output.absolute()
    if any(p.is_symlink() for p in (output, *output.parents)) or not output.parent.is_dir():
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
        libc = None
        if args.musl_build:
            tool["gcc"], libc = validate_musl(args.musl_build.absolute())
        ldflags = LDFLAGS + (" -static" if libc else "")
        clock_compat = None
        if libc:
            companion = Path(__file__).with_name("yyos-clock-compat.c")
            if companion.is_symlink() or digest(companion) != CLOCK_COMPAT_SHA256:
                raise ValueError("YYOS legacy clock compatibility differs from audited source")
            if not re.fullmatch(r"[A-Za-z0-9_./+-]+", str(output)):
                raise ValueError("musl output path must not contain shell metacharacters or whitespace")
            shutil.copyfile(companion, output / "yyos-clock-compat.c")
            obj = output / "yyos-clock-compat.o"
            run_logged([str(tool["gcc"]), *CFLAGS.split(), "-std=c11", "-c", str(companion), "-o", str(obj)],
                       output, output / "clock-compat-build.log", 60)
            ldflags += " " + str(obj)
            clock_compat = {"source_sha256": CLOCK_COMPAT_SHA256, "object_sha256": digest(obj),
                            "kernel_time_abi": "ARM EABI signed time32 converted to libc time64",
                            "clock_source": "requested POSIX clock, including monotonic", "timeouts_disabled": False}
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
        clock_patch = patch_clock_fallback(source) if libc else None
        build = output / "build-arm"
        build.mkdir()
        shutil.copyfile(config, build / "localoptions.h")
        stage = "configure"
        run_logged([str(tool["gcc"]), "--version"], build, output / "compiler-version.log", 20)
        configure_flags = CONFIGURE_FLAGS.copy()
        if libc:
            configure_flags[0] = "--host=arm-linux-musleabi"
        cflags = CFLAGS + (" -DLSCAMOFLASH_YYOS_CLOCK_COMPAT=1" if libc else "")
        command = [str(source / "configure"), *configure_flags,
                   f"CC={tool['gcc']}", f"AR={tool['ar']}", f"RANLIB={tool['ranlib']}",
                   f"STRIP={tool['strip']}", f"CFLAGS={cflags}", f"LDFLAGS={ldflags}"]
        # Relative source layout also keeps __FILE__ strings consistent between builds.
        command[0] = f"../dropbear-{VERSION}/configure"
        run_logged(command, build, output / "configure.log", 180)
        if libc and not re.search(r"^#define HAVE_OPENPTY\b", (build / "config.h").read_text(), re.MULTILINE):
            raise ValueError("static musl configure did not detect required openpty support")
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
        if libc:
            with (output / "DROPBEAR-LICENSES.txt").open("a") as notices:
                for name in ("COPYING.musl", "GCC-COPYING3", "GCC-COPYING.RUNTIME"):
                    notices.write(f"\n===== Static runtime {name} =====\n")
                    notices.write((args.musl_build / name).read_text())
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
            "configure_flags": configure_flags, "cflags": cflags, "ldflags": LDFLAGS + (" -static" if libc else ""),
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
        if libc:
            provenance.update({"libc": libc, "static_libc_version": "musl1.2.6",
                               "yyos_clock_compat": clock_compat,
                               "yyos_clock_patch": clock_patch,
                               "static_libc_distribution_note": "Pinned musl MIT notices and GCC runtime exception included; retain the supplied source and build provenance."})
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
