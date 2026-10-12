#!/usr/bin/env python3
"""Read-only host verification of one backup-kit run directory."""
import argparse
import csv
import hashlib
import json
import re
import tarfile
from pathlib import Path


def check(condition, message):
    if not condition:
        raise ValueError(message)


def safe_file(root, name):
    relative = Path(name)
    check(not relative.is_absolute() and ".." not in relative.parts, f"Unsafe path: {name}")
    target = root / relative
    check(target.resolve().is_relative_to(root), f"Path escapes backup: {name}")
    current = root
    for component in relative.parts:
        current = current / component
        check(not current.is_symlink(), f"Symlink in backup path: {name}")
    check(target.is_file(), f"Missing regular file: {name}")
    return target


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify(directory):
    root = directory.resolve(strict=True)
    check(root.is_dir(), "Expected a run directory")
    status_lines = safe_file(root, "status.txt").read_text().splitlines()
    check(status_lines and status_lines[0] == "VERIFIED_NOR_BACKUP", "Backup status is incomplete or failed")
    status = dict(line.split("=", 1) for line in status_lines[1:] if "=" in line)
    check(status.get("flash_image_concatenated") == "no", "Unexpected reconstructed flash image claim")
    checksums = {}
    for line in safe_file(root, "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        check(match is not None, "Malformed SHA256SUMS entry")
        expected, name = match.groups()
        check(name not in checksums, f"Duplicate checksum entry: {name}")
        target = safe_file(root, name)
        check(digest(target) == expected, f"SHA256 mismatch: {name}")
        checksums[name] = expected
    for name in ("partitions.tsv", "read-attempts.tsv", "stock-userspace.tar"):
        check(name in checksums, f"Required file lacks checksum: {name}")
    def checked_file(name):
        check(name in checksums, f"Required metadata lacks checksum: {name}")
        return safe_file(root, name)

    with tarfile.open(safe_file(root, "stock-userspace.tar"), "r:") as archive:
        members = archive.getmembers()
        check(bool(members), "Empty userspace archive")
        for member in members:
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            check(stream is not None, f"Unreadable archive member: {member.name}")
            with stream:
                length = sum(len(block) for block in iter(lambda: stream.read(1024 * 1024), b""))
            check(length == member.size, f"Truncated archive member: {member.name}")
    with safe_file(root, "partitions.tsv").open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    check(0 < len(rows) <= 64, "Invalid partition count")
    discovered = {}
    for line in checked_file("meta/proc-mtd.txt").read_text().splitlines():
        match = re.fullmatch(r'(mtd[0-9]+):\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+"(.*)"', line)
        if match:
            identity, size_hex, erase_hex, _ = match.groups()
            check(identity not in discovered, f"Duplicate /proc/mtd ID: {identity}")
            discovered[identity] = (int(size_hex, 16), int(erase_hex, 16))
        else:
            check(not line.lstrip().startswith("mtd"), "Malformed /proc/mtd row")
    seen = set()
    total = 0
    partitions = []
    for row in rows:
        identity = row["id"]
        check(re.fullmatch(r"mtd[0-9]+", identity) is not None, "Invalid partition ID")
        check(identity not in seen, f"Duplicate partition: {identity}")
        seen.add(identity)
        size, erase = int(row["bytes"]), int(row["erase_bytes"])
        check(0 < size <= 64 * 1024 * 1024 and 0 < erase <= size, f"Invalid geometry: {identity}")
        check(discovered.get(identity) == (size, erase), f"Inventory disagrees with /proc/mtd: {identity}")
        check(row["type"] == "nor" and row["oob_bytes"] == "0", f"Unsupported flash type/OOB geometry: {identity}")
        # Match the dumper's bounded policy, including the observed EV330 report.
        write = int(row["write_bytes"])
        check(row["write_bytes"] == str(write) and write in (1, 256), f"Unsupported NOR write unit: {identity}")
        check(erase % write == 0 and size % erase == 0 and size % write == 0, f"Unaligned NOR geometry: {identity}")
        check(re.fullmatch(r"[0-9]+:[0-9]+", row["dev"]) is not None, f"Invalid device identifier: {identity}")
        for attribute, expected in (("type", "nor"), ("size", str(size)), ("erasesize", str(erase)), ("writesize", str(write)), ("oobsize", "0"), ("dev", row["dev"])):
            actual = checked_file(f"meta/{identity}/{attribute}").read_text().strip()
            check(actual == expected, f"Sysfs metadata differs: {identity}/{attribute}")
        offset = row["offset"]
        check(offset == "unknown" or re.fullmatch(r"[0-9]+", offset) is not None, f"Invalid offset: {identity}")
        if offset != "unknown":
            check(checked_file(f"meta/{identity}/offset").read_text().strip() == offset, f"Sysfs offset differs: {identity}")
        names = [f"partitions/{identity}/read{number}.bin" for number in (1, 2)]
        for name in names:
            check(name in checksums, f"Partition lacks checksum: {name}")
            check(safe_file(root, name).stat().st_size == size, f"Wrong partition length: {name}")
        check(checksums[names[0]] == checksums[names[1]], f"Independent reads differ: {identity}")
        partitions.append({"id": identity, "bytes": size, "offset": row["offset"], "sha256": checksums[names[0]]})
        total += size
    check(seen == set(discovered), "Not every discovered partition was backed up")
    check(total <= 128 * 1024 * 1024, "Partition total exceeds kit limit")
    check(int(status.get("partitions", "-1")) == len(rows), "Status partition count differs")
    check(int(status.get("total_partition_bytes", "-1")) == total, "Status byte count differs")
    expected_images = {f"partitions/{identity}/read{number}.bin" for identity in seen for number in (1, 2)}
    check({name for name in checksums if name.startswith("partitions/")} == expected_images, "Unexpected partition checksum inventory")
    with safe_file(root, "read-attempts.tsv").open(newline="") as stream:
        attempts = list(csv.DictReader(stream, delimiter="\t"))
    for partition in partitions:
        valid_pair = False
        for attempt in ("1", "2", "3"):
            pair = [row for row in attempts if row["id"] == partition["id"] and row["attempt"] == attempt]
            if len(pair) != 2 or {row["read"] for row in pair} != {"1", "2"}:
                continue
            valid_pair |= all(row["dd_exit"] == "0" and row["result"] == "ok" and int(row["bytes"]) == partition["bytes"] and row["sha256"] == partition["sha256"] for row in pair)
        check(valid_pair, f"Missing successful independent-read evidence: {partition['id']}")
    return {"verified": True, "run_directory": str(root), "partition_count": len(partitions), "total_partition_bytes": total, "checked_files": len(checksums), "whole_chip_coverage": "not established; retain individual partitions and metadata", "partitions": partitions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.run_directory)
    except (OSError, ValueError, KeyError, TypeError, csv.Error, tarfile.TarError) as error:
        parser.exit(1, f"Backup verification failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
