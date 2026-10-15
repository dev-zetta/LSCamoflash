#!/usr/bin/env python3
"""Build a dedicated YYOS NOR backup kit offline; never copy it to a card."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location("yyos_nor_builder_helpers", HERE / "build-kit.py")
NOR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NOR)
FORMAT = "lscamoflash-yyos-nor-backup-kit-v1"
CARD_FILES = {"telnetd", "busybox", "dump.sh", "yy_telnet_start", "SHA256SUMS"}
PACKAGE_FILES = {"README.md", "verify-backup.py", "manifest.json", "SHA256SUMS", "LICENSE.MIT", "COPYING.BusyBox"}
FLAGS = ["-static", "-Os", "-s", "-std=c99", "-Wall", "-Wextra", "-Werror",
         "-march=armv5te", "-mtune=arm926ej-s", "-mfloat-abi=soft", "-marm"]
README = """# YYOS SD NOR backup kit

This host-built kit collects two matching reads of every exposed supported NOR MTD partition, plus stock userspace and private metadata. Building it does not install anything, access a camera, change configuration or restore firmware. Compatibility of the stock YYOS SD entry must be established separately on the exact camera and firmware; this kit does not bypass a runtime profile check.

Only card/ contains SD-root files: telnetd, busybox, dump.sh, yy_telnet_start and SHA256SUMS. Despite its required filename, telnetd is the project's native backup launcher and starts no Telnet daemon. It waits for its collector child; normal stock startup must independently launch this hook in the background. Do not add yy_debug.ini, hack.sh, AP/log/factory markers or firmware-update files. Do not mix this kit with another hook or overwrite existing card files.

Use the camera-specific public guide to prepare a spare compatible card, verify its existing mount and stage the marker last while the camera is powered off. This builder provides no copying, formatting or repartitioning command. It refuses nonempty output directories; create a new host output for another build.

The collector independently requires root and one visible writable MMC/FAT mount. It preserves its size limits, 240-second monotonic budget, per-command timeouts and supported NOR geometry checks. NAND requires a separate ECC/OOB-aware plan. Userspace includes existing /appfs and /config trees; mutable stock files can make capture fail, and a failed capture is retained rather than repaired by changing the stock application. Kernel I/O in an uninterruptible state cannot be bounded by userspace timeouts.

After the powered-off card is retrieved, copy firmware-backup/ privately to the host and run python3 verify-backup.py /private/path/firmware-backup/run-NAME. Success requires a zero exit and verified:true, not merely a completed boot. Preserve failed attempts and all paired reads/metadata. No guessed concatenated flash image is produced, and exposed partitions do not establish whole-chip coverage or restoration.

Raw firmware, /config, userspace and logs can contain credentials and identifiers. Keep them private. The launcher writes backup-launcher.log only after establishing a safe SD destination; absent output does not prove the hook never ran. Remove the root yy_telnet_start marker while powered off to stop requesting this hook, then check normal app, network and recording behavior separately.

LICENSE.MIT covers project-authored code. COPYING.BusyBox retains the GPLv2 license text from the declared source archive; the whole kit is not solely MIT-licensed. manifest.json records binary hashes, build flags, project source hashes and repository BusyBox source/configuration inputs. A caller-supplied BusyBox override is separately hashed and validated as an ARM executable; this alone does not prove it was built from those repository inputs. Distributing modified overrides requires their matching source/configuration and notices. The repository's SOURCE/3RD_PARTY_LICENSES.md describes source and static toolchain-runtime licensing, including corresponding Bootlin toolchain sources. Retain those notices and use the matching public source bundle when redistributing binaries.
"""


def regular(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Expected a regular input: {path.name}")
    return path


def validate_output(output):
    if any(path.is_symlink() for path in (output, *output.parents)) or output.is_mount():
        raise ValueError("Output must not be a symlink or mountpoint")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output must be absent or an empty dedicated host directory")


def busybox_sources():
    recipe = regular(REPO / "SOURCE/Makefile")
    text = recipe.read_text()
    version = re.search(r"^BUSYBOX\s*:?=\s*(busybox-[A-Za-z0-9._+-]+)\s*$", text, re.M)
    base = re.search(r"^DOWNLOAD_URL\s*:?=\s*(https?://\S+)\s*$", text, re.M)
    if not version or not base:
        raise ValueError("Missing declared BusyBox source inputs")
    name = version[1]
    source = regular(REPO / "SOURCE/download" / (name + ".tar.bz2"))
    config = regular(REPO / "SOURCE/src/patches" / name / "uclibc-config")
    with source.open("rb") as stream:
        if stream.read(43).startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise ValueError("BusyBox source archive is an unhydrated Git LFS pointer")
    with tarfile.open(source, "r:bz2") as archive:
        member = archive.getmember(name + "/LICENSE")
        if not member.isfile() or member.size <= 0 or member.size > 1024 * 1024:
            raise ValueError("Invalid BusyBox license member")
        copying = archive.extractfile(member).read()
    return copying, {"name": name, "archive": "SOURCE/download/" + source.name,
                     "archive_sha256": NOR.digest(source), "source_url": base[1].rstrip("/") + "/" + source.name,
                     "config": "SOURCE/src/patches/" + name + "/uclibc-config", "config_sha256": NOR.digest(config),
                     "recipe": "SOURCE/Makefile", "recipe_sha256": NOR.digest(recipe),
                     "binary_source_relationship": "Repository recipe inputs; caller-supplied binary is separately hashed, not source-attested"}


def build(args):
    output = args.output.absolute()
    validate_output(output)
    cc = NOR.executable(args.cc)
    readelf = NOR.executable(args.readelf or str(cc).removesuffix("gcc") + "readelf")
    busybox = regular(args.busybox.absolute())
    if busybox.stat().st_size > 8 * 1024 * 1024 or not os.access(busybox, os.X_OK):
        raise ValueError("BusyBox must be executable and no larger than 8 MiB")
    bb_report = NOR.validate_arm_elf(busybox, readelf)
    copying, source_inputs = busybox_sources()
    project_license = regular(REPO / "LICENSE")
    qemu = NOR.executable(args.qemu) if args.qemu else None
    if qemu:
        applets = subprocess.run([str(qemu), "-cpu", "arm926", str(busybox), "--list"], check=True,
                                 capture_output=True, text=True, timeout=15).stdout.splitlines()
        missing = NOR.APPLETS - set(applets)
        if missing:
            raise ValueError("BusyBox lacks required applets: " + ", ".join(sorted(missing)))
        subprocess.run([str(qemu), "-cpu", "arm926", str(busybox), "true"], check=True, timeout=5)
        subprocess.run([str(qemu), "-cpu", "arm926", str(busybox), "sh", "-n", str(HERE / "backup-nor.sh")],
                       check=True, capture_output=True, timeout=5)
    output.parent.mkdir(parents=True, exist_ok=True)
    validate_output(output)
    with tempfile.TemporaryDirectory(prefix=".yyos-backup-build-", dir=output.parent) as temporary:
        stage = Path(temporary) / "kit"
        card = stage / "card"
        card.mkdir(parents=True)
        subprocess.run([str(cc), *FLAGS, str(regular(HERE / "hostapd.c")), "-o", str(card / "telnetd")],
                       check=True, capture_output=True, timeout=120)
        launcher = NOR.validate_arm_elf(card / "telnetd", readelf)
        shutil.copyfile(busybox, card / "busybox")
        shutil.copyfile(regular(HERE / "backup-nor.sh"), card / "dump.sh")
        for name in ("telnetd", "busybox", "dump.sh"):
            (card / name).chmod(0o755)
        (card / "yy_telnet_start").touch(mode=0o600)
        NOR.write_sums(card, CARD_FILES - {"SHA256SUMS"})
        shutil.copyfile(regular(HERE / "verify-backup.py"), stage / "verify-backup.py")
        shutil.copyfile(project_license, stage / "LICENSE.MIT")
        (stage / "COPYING.BusyBox").write_bytes(copying)
        (stage / "README.md").write_text(README)
        names = (PACKAGE_FILES - {"manifest.json", "SHA256SUMS"}) | {"card/" + name for name in CARD_FILES}
        manifest = {"format": FORMAT, "target": "ARMv5TE soft-float Linux; separately confirmed YYOS SD hook",
                    "entry": {"executable": "telnetd", "marker": "yy_telnet_start", "starts_telnet_daemon": False,
                              "stock_hook_requires_confirmation": True, "expected_sd_mount": "/mnt/sdcard"},
                    "launcher": launcher, "busybox": bb_report, "busybox_qemu_smoke": bool(qemu),
                    "collector_qemu_syntax": bool(qemu), "busybox_repository_sources": source_inputs,
                    "build": {"compiler": cc.name, "compiler_sha256": NOR.digest(cc), "flags": FLAGS},
                    "sources": {name: NOR.digest(regular(HERE / name)) for name in
                                ("build-yyos-kit.py", "build-kit.py", "hostapd.c", "backup-nor.sh", "verify-backup.py")},
                    "files": {name: NOR.digest(stage / name) for name in sorted(names)}}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        NOR.write_sums(stage, names | {"manifest.json"})
        # Never erase additions made while the compiler was running.
        validate_output(output)
        if output.exists():
            output.rmdir()
        stage.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="absent or empty dedicated host output directory")
    parser.add_argument("--cc", default=os.environ.get("CC", str(REPO / "SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi-gcc")))
    parser.add_argument("--busybox", type=Path, default=Path(os.environ.get("BB", str(REPO / "SOURCE/build/mmcblk0p2/HACK/bin/busybox"))))
    parser.add_argument("--readelf", default=os.environ.get("READELF"))
    parser.add_argument("--qemu", default=os.environ.get("QEMU_ARM"), help="optional qemu-arm for ARM926 applet/syntax checks")
    args = parser.parse_args()
    try:
        output = build(args)
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, f"YYOS backup kit build failed: {error}\n")
    print(f"Built YYOS NOR backup kit: {output}")
    print("Only card/ contains SD-root files. No card installation or firmware operation was performed.")


if __name__ == "__main__":
    main()
