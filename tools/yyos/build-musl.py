#!/usr/bin/env python3
"""Build pinned static musl for ARM926; never contact a camera or write an SD card."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location("yyos_dropbear_builder", HERE / "build-dropbear.py")
COMMON = importlib.util.module_from_spec(spec)
spec.loader.exec_module(COMMON)
VERSION = "1.2.6"
SOURCE_URL = f"https://musl.libc.org/releases/musl-{VERSION}.tar.gz"
SOURCE_SHA256 = "d585fd3b613c66151fc3249e8ed44f77020cb5e6c1e635a616d3f9f82460512a"
CFLAGS = "-Os -march=armv5te -mtune=arm926ej-s -mfloat-abi=soft -marm"
RUNTIME_NOTICES = {
    "GCC-COPYING3": "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
    "GCC-COPYING.RUNTIME": "9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74",
}


def unpack(archive: Path, output: Path) -> Path:
    expected = f"musl-{VERSION}"
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) > 4000 or sum(x.size for x in members) > 16 * 1024 * 1024:
            raise ValueError("musl source exceeds extraction limits")
        names = set()
        for item in members:
            name = PurePosixPath(item.name)
            if (name.is_absolute() or ".." in name.parts or not name.parts
                    or name.parts[0] != expected or str(name) in names
                    or not (item.isfile() or item.isdir()) or item.size < 0):
                raise ValueError("unsafe musl archive member")
            names.add(str(name))
        for item in members:
            path = output.joinpath(*PurePosixPath(item.name).parts)
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(item)
                if source is None:
                    raise ValueError("unreadable source member")
                with source, path.open("xb") as stream:
                    shutil.copyfileobj(source, stream)
                path.chmod(0o755 if item.mode & 0o111 else 0o644)
    return output / expected


def inventory(root: Path) -> dict:
    result = {}
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError("unexpected symlink in static musl installation")
        if item.is_file():
            result[str(item.relative_to(root))] = COMMON.digest(item)
    if not {"bin/musl-gcc", "lib/libc.a", "lib/crt1.o", "include/stdio.h"} <= result.keys():
        raise ValueError("static musl installation is incomplete")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="pinned official musl-1.2.6.tar.gz")
    parser.add_argument("--output", type=Path, required=True, help="new directory; failures are retained")
    parser.add_argument("--toolchain-prefix", type=Path, default=REPO / "SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi")
    parser.add_argument("--qemu", type=Path, default=REPO / ".local/tools/root/usr/bin/qemu-arm")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    output = args.output.absolute()
    if not 1 <= args.jobs <= 32:
        parser.error("--jobs must be between 1 and 32")
    if any(p.is_symlink() for p in (output, *output.parents)) or not output.parent.is_dir():
        parser.error("output parent must exist without symlinks")
    try:
        output.mkdir(mode=0o700)
    except FileExistsError:
        parser.error("output already exists; choose a fresh directory")
    stage, started = "inputs", time.monotonic()
    try:
        archive = args.source.absolute()
        if (archive.is_symlink() or not archive.is_file() or not 0 < archive.stat().st_size <= 2 * 1024 * 1024
                or COMMON.digest(archive) != SOURCE_SHA256):
            raise ValueError("source must be the pinned official regular musl archive")
        prefix = args.toolchain_prefix.absolute()
        gcc = Path(str(prefix) + "-gcc")
        if not all(re.fullmatch(r"[A-Za-z0-9_./+-]+", str(path)) for path in (prefix, output)):
            raise ValueError("build paths must not contain shell metacharacters or whitespace")
        for tool in (gcc, Path(str(prefix) + "-ar"), Path(str(prefix) + "-ranlib"), args.qemu):
            if not tool.is_file() or not os.access(tool, os.X_OK):
                raise ValueError("executable ARM toolchain and qemu-arm required")
        for name, expected in RUNTIME_NOTICES.items():
            notice = HERE / "licenses" / name
            if notice.is_symlink() or COMMON.digest(notice) != expected:
                raise ValueError("GCC runtime notice differs from pinned upstream text")
            shutil.copyfile(notice, output / name)
        retained = output / f"musl-{VERSION}.tar.gz"
        shutil.copyfile(archive, retained)
        stage = "extract"
        source = unpack(retained, output)
        shutil.copyfile(source / "COPYRIGHT", output / "COPYING.musl")
        install = output / "install"
        flags = ["--target=arm-linux-musleabi", "--disable-shared", f"--prefix={install}"]
        stage = "configure"
        COMMON.run_logged([str(gcc), "--version"], source, output / "compiler-version.log", 20)
        COMMON.run_logged(["env", f"CC={gcc}", f"CROSS_COMPILE={prefix}-", f"CFLAGS={CFLAGS}", "./configure", *flags],
                          source, output / "configure.log", 180)
        stage = "make"
        COMMON.run_logged(["make", f"-j{args.jobs}"], source, output / "make.log", 600)
        COMMON.run_logged(["make", "install"], source, output / "install.log", 120)
        stage = "qemu"
        probe = output / "smoke.c"
        probe.write_text('#include <stdio.h>\nint main(void) { return puts("musl-arm926-static-ok") < 0; }\n')
        COMMON.run_logged([str(install / "bin/musl-gcc"), *CFLAGS.split(), "-static", str(probe), "-o", str(output / "smoke")],
                          output, output / "smoke-build.log", 60)
        elf = COMMON.check_elf(output / "smoke")
        COMMON.run_logged([str(args.qemu.absolute()), "-cpu", "arm926", str(output / "smoke")], output, output / "smoke.log", 15)
        if (output / "smoke.log").read_text().strip() != "musl-arm926-static-ok":
            raise ValueError("unexpected ARM926 static musl smoke result")
        provenance = {"schema": 1, "name": "musl", "version": VERSION, "source_url": SOURCE_URL,
                      "source_archive_sha256": SOURCE_SHA256, "license_sha256": COMMON.digest(output / "COPYING.musl"),
                      "build_script_sha256": COMMON.digest(Path(__file__)), "configure_flags": flags[:-1],
                      "cflags": CFLAGS, "compiler_version": (output / "compiler-version.log").read_text().splitlines()[0],
                      "compiler_sha256": COMMON.digest(gcc), "install_files": inventory(install),
                      "gcc_runtime_notices": RUNTIME_NOTICES, "qemu": {"passed": True, "cpu": "arm926", "elf": elf},
                      "camera_contacted": False}
        COMMON.write_json(output / "provenance.json", provenance)
        COMMON.write_json(output / "result.json", {"ok": True, "elapsed_seconds": round(time.monotonic() - started, 3)})
        print(json.dumps({"ok": True, "libc": "musl", "version": VERSION, "qemu_passed": True}))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
        COMMON.write_json(output / "result.json", {"ok": False, "stage": stage, "error": str(error)})
        print(f"musl build failed at {stage}; logs retained: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
