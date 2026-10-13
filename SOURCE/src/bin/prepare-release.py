#!/usr/bin/env python3
"""Stage versioned public release assets; never build, publish, or access a card."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[3]
VERSION_RE = re.compile(r"1\.[0-9]{2}\.[0-9]{4}\Z")
LFS_HEADER = b"version https://git-lfs.github.com/spec/v1\n"
KIT_FILES = {"README.md", "verify-backup.py", "manifest.json", "SHA256SUMS",
             "card/hostapd", "card/busybox", "card/dump.sh", "card/_ht_ap_mode.conf",
             "card/_ht_get_log.conf", "card/SHA256SUMS"}
VERSION_MEMBER = "mmcblk0p2/HACK/etc/version.txt"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def version_text(data):
    value = data.decode("ascii").rstrip("\r\n")
    if not VERSION_RE.fullmatch(value):
        raise ValueError("Version must have the form 1.xx.xxxx")
    return value


def regular(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Expected a regular file: {path.name}")
    with path.open("rb") as stream:
        if stream.read(len(LFS_HEADER)) == LFS_HEADER:
            raise ValueError(f"Unhydrated Git LFS pointer: {path.name}")
    return path


def declared_inputs(makefile):
    """Expand simple Make variables, without executing Make/shell functions."""
    logical = re.sub(r"\\\r?\n", " ", makefile.read_text())
    variables = {}
    for line in logical.splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::=|\?=|=)\s*(.*)$", line)
        if match:
            variables[match[1]] = match[2]

    def expand(value, stack=()):
        def replace(match):
            key = match[1] or match[2]
            if key in stack or key not in variables:
                raise ValueError(f"Unsupported or recursive Make variable: {key}")
            return expand(variables[key], (*stack, key))
        value = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)
        if "$" in value:
            raise ValueError("URLS must use simple declared Make variables")
        return value

    if "URLS" not in variables:
        raise ValueError("Makefile has no declared URLS inputs")
    names = []
    for url in expand(variables["URLS"]).split():
        name = url.rsplit("/", 1)[-1]
        if not url.startswith(("https://", "http://")) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name):
            raise ValueError("Unsupported Makefile download filename")
        if name in names:
            raise ValueError(f"Duplicate declared download: {name}")
        names.append(name)
    if not names:
        raise ValueError("Makefile URLS inputs are empty")
    busybox = expand(variables.get("BUSYBOX", ""))
    if not re.fullmatch(r"busybox-[A-Za-z0-9._+-]+", busybox):
        raise ValueError("Makefile must declare the BusyBox source version")
    return names, busybox


def public_paths(repo):
    result = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], check=True, stdout=subprocess.PIPE)
    paths = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = PurePosixPath(os.fsdecode(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe tracked source path")
        if any(part in {".local", ".git"} for part in relative.parts):
            continue
        if relative.parts[:2] == ("SOURCE", "download"):
            continue
        path = repo / str(relative)
        # A tracked symlink itself is preserved. An ancestor symlink would
        # redirect a supposedly tracked regular file to unrelated local data.
        for ancestor in path.parents:
            if ancestor == repo:
                break
            if ancestor.is_symlink():
                raise ValueError(f"Symlink ancestor of tracked file: {relative}")
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode):
            regular(path)
        elif not stat.S_ISLNK(mode):
            raise ValueError(f"Unsupported tracked file type: {relative}")
        paths.append(str(relative))
    if not paths:
        raise ValueError("No tracked public source files")
    return sorted(set(paths))


def input_hashes(repo, names):
    result = {}
    download = repo / "SOURCE/download"
    if download.is_symlink():
        raise ValueError("Download directory must not be a symlink")
    for name in names:
        path = regular(download / name)
        checksum = digest(path)
        # Verify hydrated data against the tracked LFS object when available.
        spec = ":SOURCE/download/" + name
        size = subprocess.run(["git", "-C", str(repo), "cat-file", "-s", spec],
                              capture_output=True, text=True)
        if size.returncode == 0 and int(size.stdout.strip()) <= 512:
            pointer = subprocess.check_output(["git", "-C", str(repo), "cat-file", "blob", spec])
            if pointer.startswith(LFS_HEADER):
                match = re.fullmatch(LFS_HEADER + rb"oid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n?", pointer)
                if not match or checksum != match[1].decode() or path.stat().st_size != int(match[2]):
                    raise ValueError(f"Hydrated LFS input differs from tracked object: {name}")
        result[name] = checksum
    return result


def archive_inventory(path):
    inventory = {}
    with tarfile.open(regular(path), "r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"Unsafe release archive member: {path.name}")
            name = str(name)
            if member.isdir():
                continue
            if name in inventory:
                raise ValueError(f"Duplicate release archive member: {name}")
            if member.isfile() or member.islnk():
                if member.islnk():
                    target = PurePosixPath(member.linkname)
                    if target.is_absolute() or ".." in target.parts:
                        raise ValueError("Unsafe release hardlink target")
                if name == VERSION_MEMBER and member.size > 64:
                    raise ValueError("Oversized runtime version file")
                with archive.extractfile(member) as stream:
                    checksum = hashlib.sha256()
                    version = b"" if name == VERSION_MEMBER else None
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        checksum.update(block)
                        if version is not None:
                            version += block
                    inventory[name] = ("file", checksum.hexdigest(), version)
            elif member.issym():
                inventory[name] = ("symlink", member.linkname)
            else:
                raise ValueError(f"Unsupported release archive member: {name}")
    return inventory


def verify_sums(directory, expected):
    entries = {}
    for line in regular(directory / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_./-]+)", line)
        if not match or match[2] in entries or ".." in PurePosixPath(match[2]).parts:
            raise ValueError("Invalid backup-kit checksum list")
        entries[match[2]] = match[1]
    if set(entries) != expected:
        raise ValueError("Backup-kit checksum inventory differs from expected files")
    for name, checksum in entries.items():
        if digest(regular(directory / name)) != checksum:
            raise ValueError(f"Backup-kit checksum mismatch: {name}")


def validate_kit(kit):
    if kit.is_symlink() or (kit / "card").is_symlink():
        raise ValueError("Backup kit must not contain symlink directories")
    actual = {str(path.relative_to(kit)) for path in kit.rglob("*")}
    if actual != KIT_FILES | {"card"}:
        raise ValueError("Backup kit contains missing or unexpected files")
    for name in KIT_FILES:
        regular(kit / name)
    if json.loads((kit / "manifest.json").read_text()).get("format") != "lscamoflash-nor-backup-kit-v1":
        raise ValueError("Unrecognized backup-kit format")
    verify_sums(kit, KIT_FILES - {"SHA256SUMS"})
    verify_sums(kit / "card", {Path(name).name for name in KIT_FILES if name.startswith("card/")} - {"SHA256SUMS"})
    for name in ("card/_ht_ap_mode.conf", "card/_ht_get_log.conf"):
        if (kit / name).stat().st_size:
            raise ValueError("Backup kit diagnostic markers must be empty")


def output_empty(output):
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("Release output must not use symlinks")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Release output must be absent or empty; refusing overwrite")


def add_file(archive, path, name):
    # recursive=False is essential: git's explicit list is the source boundary.
    archive.add(path, arcname=name, recursive=False)


def busybox_license(repo, busybox):
    archive_path = regular(repo / "SOURCE/download" / (busybox + ".tar.bz2"))
    with tarfile.open(archive_path, "r:bz2") as archive:
        member = archive.getmember(busybox + "/LICENSE")
        if not member.isfile() or member.size > 1024 * 1024:
            raise ValueError("Invalid BusyBox source license member")
        return archive.extractfile(member).read()


def notices(repo, version, source_name, inputs):
    summary = regular(repo / "SOURCE/3RD_PARTY_LICENSES.md").read_text()
    return f"""# LSCamoflash {version}: third-party notices

The project-authored code is covered by LICENSE.MIT. The runtime and backup kit also contain independently licensed third-party software; this distribution as a whole is not licensed solely under MIT. COPYING.BusyBox contains the GPL version 2 text supplied with the exact BusyBox source input.

The accompanying `{source_name}` contains the Git-tracked public repository files, including build recipes, patches, configurations and project notices, plus every hydrated input explicitly listed by SOURCE/Makefile URLS. Untracked working directories, private research and undeclared download files are excluded. Source archives retain their upstream license texts. FFmpeg is built with --enable-gpl and --enable-version3, giving this build GPL version 3 or later licensing.

The Bootlin toolchain archives are prebuilt toolchains, not complete component-source archives. Their README.txt files describe the mixed component licenses and rebuilding with https://github.com/bootlin/buildroot-toolchains at tag `toolchains.bootlin.com-2020.08-1`. Bootlin publishes separate [component sources](https://toolchains.bootlin.com/downloads/releases/sources/) and [license information](https://toolchains.bootlin.com/downloads/releases/licenses/). Those external catalogs are not mirrored in this bundle. Runtime libraries supplied by a toolchain retain their component licenses, including the GNU runtime exceptions where applicable. This inventory does not claim to replace those component-specific terms or to contain all toolchain corresponding source.

## Hydrated build inputs

Each input is stored under SOURCE/download/ in the source bundle. SHA256 values identify the exact input bytes:

""" + "\n".join(f"- `{name}` — `{checksum}`" for name, checksum in sorted(inputs.items())) + "\n\n## Component license summary\n\n" + summary


def prepare(repo, output):
    repo, output = repo.resolve(), output.absolute()
    output_empty(output)
    version = version_text(regular(repo / "SOURCE/version.txt").read_bytes())
    if version_text(regular(repo / "SOURCE/build" / VERSION_MEMBER).read_bytes()) != version:
        raise ValueError("Built runtime version differs from SOURCE/version.txt")
    full_name = f"LSCamoflash-{version}-uclibc.tar.gz"
    update_name = f"update-{version}-uclibc.tgz"
    source_name = f"LSCamoflash-{version}-source.tar.gz"
    kit_name = f"LSCamoflash-{version}-backup-kit.tar.gz"
    full, update = repo / "SOURCE" / full_name, repo / "SOURCE" / update_name
    full_members, update_members = archive_inventory(full), archive_inventory(update)
    full_version = full_members.get(VERSION_MEMBER)
    if not full_version or full_version[0] != "file" or version_text(full_version[2]) != version:
        raise ValueError("Full archive version differs from SOURCE/version.txt")
    if not update_members or any(full_members.get(name) != value for name, value in update_members.items()):
        raise ValueError("Update archive differs from the matching full archive")
    kit = repo / "SOURCE/backup-kit"
    validate_kit(kit)
    tracked = public_paths(repo)
    names, busybox = declared_inputs(repo / "SOURCE/Makefile")
    inputs = input_hashes(repo, names)
    if busybox + ".tar.bz2" not in inputs:
        raise ValueError("BusyBox source archive is not a declared URLS input")
    copying = busybox_license(repo, busybox)
    project_license = regular(repo / "SOURCE/LICENSE.MIT")
    notice_text = notices(repo, version, source_name, inputs)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-stage-", dir=output.parent) as temporary:
        stage = Path(temporary) / "release"
        stage.mkdir()
        for original in (full, update):
            shutil.copyfile(original, stage / original.name)
            if digest(original) != digest(stage / original.name):
                raise ValueError(f"Archive copy verification failed: {original.name}")
        shutil.copyfile(project_license, stage / "LICENSE.MIT")
        (stage / "COPYING.BusyBox").write_bytes(copying)
        (stage / "THIRD_PARTY_NOTICES.md").write_text(notice_text)
        with tarfile.open(stage / source_name, "w:gz", dereference=False) as archive:
            prefix = f"LSCamoflash-{version}-source"
            for relative in tracked + ["SOURCE/download/" + name for name in sorted(names)]:
                add_file(archive, repo / relative, prefix + "/" + relative)
        with tarfile.open(stage / kit_name, "w:gz", dereference=False) as archive:
            prefix = f"LSCamoflash-{version}-backup-kit"
            for relative in sorted(KIT_FILES):
                add_file(archive, kit / relative, prefix + "/" + relative)
            for relative in ("LICENSE.MIT", "COPYING.BusyBox", "THIRD_PARTY_NOTICES.md"):
                add_file(archive, stage / relative, prefix + "/" + relative)
        assets = sorted(path.name for path in stage.iterdir())
        (stage / "SHA256SUMS").write_text("".join(f"{digest(stage / name)}  {name}\n" for name in assets))
        output_empty(output)
        stage.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "release", help="dedicated absent or empty output directory")
    args = parser.parse_args()
    try:
        output = prepare(REPO, args.output)
    except (OSError, ValueError, UnicodeError, KeyError, EOFError, tarfile.TarError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Release preparation failed: {error}\n")
    print(f"Prepared public release assets: {output}")
    for path in sorted(output.iterdir()):
        print(f"{path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
