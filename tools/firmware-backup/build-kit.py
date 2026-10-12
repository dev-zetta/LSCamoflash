#!/usr/bin/env python3
"""Build a dedicated ARMv5 NOR backup kit; never install it on a card."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FORMAT = "lscamoflash-nor-backup-kit-v1"
CARD_FILES = {"hostapd", "busybox", "dump.sh", "_ht_ap_mode.conf", "_ht_get_log.conf", "SHA256SUMS"}
PACKAGE_FILES = {"README.md", "verify-backup.py", "manifest.json", "SHA256SUMS"}
APPLETS = {"sh", "awk", "cat", "cmp", "date", "dd", "df", "dmesg", "du", "find", "id", "mkdir", "mv", "readlink", "rmdir", "sha256sum", "stat", "sync", "tar", "timeout", "tr", "true", "uname", "wc"}


def digest(path):
    with path.open("rb") as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def executable(value):
    resolved = shutil.which(str(value))
    if resolved is None:
        raise ValueError(f"Executable not found: {value}")
    # Buildroot's compiler is a symlink to a wrapper that uses argv[0].
    return Path(resolved).absolute()


def validate_arm_elf(path, readelf):
    """Reject dynamic, host, hard-float, or newer-ISA input binaries."""
    data = path.read_bytes()
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError(f"Expected a 32-bit little-endian ARM ELF: {path.name}")
    fields = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    kind, machine, version, _, phoff, _, flags, ehsize, phsize, phcount, _, _, _ = fields
    if kind != 2 or machine != 40 or version != 1 or ehsize != 52:
        raise ValueError(f"Expected an ARM executable: {path.name}")
    if flags & 0xFF000000 != 0x05000000 or flags & 0x400:
        raise ValueError(f"Expected EABI5 without hard-float ABI: {path.name}")
    if phcount == 0 or phsize < 32 or phoff + phsize * phcount > len(data):
        raise ValueError(f"Invalid ELF program headers: {path.name}")
    for number in range(phcount):
        kind = struct.unpack_from("<I", data, phoff + phsize * number)[0]
        if kind in (2, 3):
            raise ValueError(f"Binary must be statically linked: {path.name}")
    report = subprocess.run([str(readelf), "-A", str(path)], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    architecture = re.search(r"Tag_CPU_arch:\s*(\S+)", report)
    if architecture is None or architecture.group(1) not in {"v5TE", "v5TEJ"}:
        raise ValueError(f"Expected ARMv5TE/ARMv5TEJ attributes: {path.name}")
    if "Tag_ABI_VFP_args: VFP registers" in report:
        raise ValueError(f"Hard-float calling convention is unsupported: {path.name}")
    if re.search(r"Tag_(?:FP_arch|Advanced_SIMD_arch):", report):
        raise ValueError(f"ARM926 hardware floating-point/SIMD is unsupported: {path.name}")
    return {"bytes": len(data), "sha256": digest(path), "cpu_arch": architecture.group(1), "static": True}


def validate_output(output):
    """A rebuild may replace only our exact previous generated inventory."""
    if any(path.is_symlink() for path in (output, *output.parents)) or output.is_mount():
        raise ValueError("Output must be a dedicated build directory, not a symlink or mountpoint")
    if not output.exists():
        return
    if not output.is_dir():
        raise ValueError("Output is not a directory")
    if not any(output.iterdir()):
        return
    expected = PACKAGE_FILES | {"card"} | {"card/" + name for name in CARD_FILES}
    actual = {str(path.relative_to(output)) for path in output.rglob("*")}
    if actual != expected or any(path.is_symlink() for path in output.rglob("*")):
        raise ValueError("Refusing to replace output with unknown files; choose a dedicated empty build directory")
    if not (output / "card").is_dir() or any(not (output / name).is_file() for name in expected - {"card"}):
        raise ValueError("Unexpected generated output file types")
    if json.loads((output / "manifest.json").read_text()).get("format") != FORMAT:
        raise ValueError("Output is not a recognized generated backup kit")


def write_sums(directory, names):
    (directory / "SHA256SUMS").write_text("".join(f"{digest(directory / name)}  {name}\n" for name in sorted(names)))


def build(args):
    cc = executable(args.cc)
    readelf = executable(args.readelf or str(cc).removesuffix("gcc") + "readelf")
    busybox = args.busybox.resolve(strict=True)
    output = args.output.absolute()
    validate_output(output)
    if not busybox.is_file() or busybox.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("BusyBox must be a regular executable no larger than 8 MiB")
    bb_report = validate_arm_elf(busybox, readelf)
    qemu = executable(args.qemu) if args.qemu else None
    if qemu:
        applets = subprocess.run([str(qemu), "-cpu", "arm926", str(busybox), "--list"], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15).stdout.splitlines()
        missing = APPLETS - set(applets)
        if missing:
            raise ValueError("BusyBox lacks required applets: " + ", ".join(sorted(missing)))
        subprocess.run([str(qemu), "-cpu", "arm926", str(busybox), "true"], check=True, timeout=5)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".backup-kit-build-", dir=output.parent) as temporary:
        stage = Path(temporary) / "kit"
        card = stage / "card"
        card.mkdir(parents=True)
        subprocess.run([str(cc), "-static", "-Os", "-s", "-std=c99", "-Wall", "-Wextra", "-Werror", "-march=armv5te", "-mtune=arm926ej-s", "-mfloat-abi=soft", "-marm", str(HERE / "hostapd.c"), "-o", str(card / "hostapd")], check=True)
        launcher_report = validate_arm_elf(card / "hostapd", readelf)
        shutil.copyfile(busybox, card / "busybox")
        shutil.copyfile(HERE / "backup-nor.sh", card / "dump.sh")
        for name in ("hostapd", "busybox", "dump.sh"):
            (card / name).chmod(0o755)
        for name in ("_ht_ap_mode.conf", "_ht_get_log.conf"):
            (card / name).touch(mode=0o600)
        write_sums(card, CARD_FILES - {"SHA256SUMS"})
        shutil.copyfile(HERE / "verify-backup.py", stage / "verify-backup.py")
        shutil.copyfile(HERE / "README.md", stage / "README.md")
        manifest = {"format": FORMAT, "target": "ARMv5TE soft-float Linux", "launcher": launcher_report, "busybox": bb_report, "busybox_qemu_smoke": qemu is not None, "sources": {name: digest(HERE / name) for name in ("hostapd.c", "backup-nor.sh", "verify-backup.py")}}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        write_sums(stage, (PACKAGE_FILES - {"SHA256SUMS"}) | {"card/" + name for name in CARD_FILES})
        # Validate again after compilation so concurrent additions are never erased.
        validate_output(output)
        previous = Path(temporary) / "previous"
        if output.exists():
            output.rename(previous)
        try:
            stage.rename(output)
        except OSError:
            if previous.exists():
                previous.rename(output)
            raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default=os.environ.get("CC", str(REPO / "SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi-gcc")), help="ARM compiler executable (or CC)")
    parser.add_argument("--busybox", type=Path, default=Path(os.environ.get("BB", str(REPO / "SOURCE/build/mmcblk0p2/HACK/bin/busybox"))), help="built static ARMv5 BusyBox (or BB)")
    parser.add_argument("--readelf", default=os.environ.get("READELF"), help="ELF reader; defaults to the compiler's matching readelf")
    parser.add_argument("--qemu", default=os.environ.get("QEMU_ARM"), help="optional qemu-arm for ARM926 BusyBox applet/smoke checks")
    parser.add_argument("--output", type=Path, default=REPO / "SOURCE/backup-kit", help="dedicated generated output directory")
    args = parser.parse_args()
    try:
        output = build(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Backup kit build failed: {error}\n")
    print(f"Built backup kit: {output}")
    print("Only card/ contains SD-root files. Building does not install or flash anything.")


if __name__ == "__main__":
    main()
