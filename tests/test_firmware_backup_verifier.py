#!/usr/bin/env python3
"""Validate synthetic backups and reject coherently rehashed corruptions."""
import csv
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "tools/firmware-backup/verify-backup.py"
spec = importlib.util.spec_from_file_location("backup_verifier", SOURCE)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def create_backup(root, write=1):
    root.mkdir()
    rows = []
    attempts = []
    for number, size in ((0, 4096), (1, 8192)):
        identity = f"mtd{number}"
        attributes = {"type": "nor", "size": str(size), "erasesize": "4096", "writesize": str(write), "oobsize": "0", "dev": "0:0", "offset": str(number * 4096)}
        metadata = root / "meta" / identity
        metadata.mkdir(parents=True)
        for name, value in attributes.items():
            (metadata / name).write_text(value + "\n")
        image = bytes(range(256)) * (size // 256)
        checksum = hashlib.sha256(image).hexdigest()
        for read in (1, 2):
            name = f"partitions/{identity}/read{read}.bin"
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(image)
            attempts.append([identity, "1", str(read), "0", str(size), checksum, "ok"])
        rows.append([identity, str(size), "4096", "nor", str(write), "0", str(number * 4096), "0:0", "FIXTURE"])
    with (root / "partitions.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "bytes", "erase_bytes", "type", "write_bytes", "oob_bytes", "offset", "dev", "name"])
        writer.writerows(rows)
    with (root / "read-attempts.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "attempt", "read", "dd_exit", "bytes", "sha256", "result"])
        writer.writerows(attempts)
    (root / "meta/proc-mtd.txt").write_text('dev: size erasesize name\nmtd0: 00001000 00001000 "FIXTURE"\nmtd1: 00002000 00001000 "FIXTURE"\n')
    with tarfile.open(root / "stock-userspace.tar", "w") as archive:
        for name in ("usr/bin/anyka_ipc", "lib/libfixture.so"):
            content = b"generated fixture, not firmware\n"
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    (root / "status.txt").write_text("VERIFIED_NOR_BACKUP\npartitions=2\ntotal_partition_bytes=12288\nflash_image_concatenated=no\n")
    sums = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "status.txt":
            sums.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + str(path.relative_to(root)))
    (root / "SHA256SUMS").write_text("\n".join(sums) + "\n")


def rehash(root, name):
    sums = root / "SHA256SUMS"
    entries = [line for line in sums.read_text().splitlines() if line.split("  ", 1)[1] != name]
    entries.append(hashlib.sha256((root / name).read_bytes()).hexdigest() + "  " + name)
    sums.write_text("\n".join(entries) + "\n")


def change_geometry(root, updates, metadata=True):
    name = "partitions.tsv"
    with (root / name).open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        fields, rows = reader.fieldnames, list(reader)
    row = next(row for row in rows if row["id"] == "mtd1")
    row.update(updates)
    with (root / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    rehash(root, name)
    if not metadata:
        return
    attributes = {"bytes": "size", "erase_bytes": "erasesize", "write_bytes": "writesize", "oob_bytes": "oobsize", "type": "type"}
    for column, value in updates.items():
        name = f"meta/mtd1/{attributes[column]}"
        (root / name).write_text(str(value) + "\n")
        rehash(root, name)
    name = "meta/proc-mtd.txt"
    (root / name).write_text('dev: size erasesize name\n' + "".join(f'{row["id"]}: {int(row["bytes"]):08x} {int(row["erase_bytes"]):08x} "{row["name"].strip()}"\n' for row in rows))
    rehash(root, name)


GEOMETRY_CASES = {
    "nor256-nand": ({"write_bytes": "256", "type": "nand"}, "Unsupported flash type/OOB geometry", True),
    "nor256-oob": ({"write_bytes": "256", "oob_bytes": "16"}, "Unsupported flash type/OOB geometry", True),
    "nor-zero-write": ({"write_bytes": "0"}, "Unsupported NOR write unit", True),
    "nor-unsupported-write": ({"write_bytes": "128"}, "Unsupported NOR write unit", True),
    "nor256-erase-unaligned": ({"write_bytes": "256", "erase_bytes": "4095"}, "Unaligned NOR geometry", True),
    "nor256-size-unaligned": ({"write_bytes": "256", "bytes": "8191"}, "Unaligned NOR geometry", True),
    "nor256-erase-division": ({"write_bytes": "256", "erase_bytes": "3840"}, "Unaligned NOR geometry", True),
    "nor-write-metadata-mismatch": ({"write_bytes": "256"}, "Sysfs metadata differs", False),
}


def corrupt(root, case):
    image = root / "partitions/mtd0/read1.bin"
    if case == "tampered-image":
        image.write_bytes(b"x" + image.read_bytes()[1:])
    elif case == "short-pair-with-new-hashes":
        for number in (1, 2):
            name = f"partitions/mtd0/read{number}.bin"
            (root / name).write_bytes(b"x")
            rehash(root, name)
    elif case == "missing-partition":
        (root / "partitions/mtd1/read2.bin").unlink()
    elif case == "failed-status":
        (root / "status.txt").write_text("FAILED exit=1\n")
    elif case == "symlink-image":
        image.unlink()
        image.symlink_to("read2.bin")
    elif case == "missing-read-evidence":
        name = "read-attempts.tsv"
        (root / name).write_text((root / name).read_text().splitlines()[0] + "\n")
        rehash(root, name)
    elif case == "unhashed-metadata":
        sums = root / "SHA256SUMS"
        sums.write_text("\n".join(line for line in sums.read_text().splitlines() if not line.endswith("  meta/proc-mtd.txt")) + "\n")
    elif case == "wrong-offset-with-new-hash":
        name = "partitions.tsv"
        (root / name).write_text((root / name).read_text().replace("\t0\t0:0\t", "\t9000\t0:0\t"))
        rehash(root, name)
    elif case == "unexpected-proc-partition":
        name = "meta/proc-mtd.txt"
        (root / name).write_text((root / name).read_text() + 'mtd2: 00001000 00001000 "MISSING"\n')
        rehash(root, name)
    elif case == "bad-archive-with-new-hash":
        name = "stock-userspace.tar"
        (root / name).write_bytes(b"not an archive")
        rehash(root, name)
    elif case == "truncated-later-archive-member":
        name = "stock-userspace.tar"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for filename in ("first", "second"):
                member = tarfile.TarInfo(filename)
                member.size = 1
                archive.addfile(member, io.BytesIO(b"x"))
        (root / name).write_bytes(buffer.getvalue()[:1536])
        rehash(root, name)
    elif case == "parent-path-checksum":
        sums = root / "SHA256SUMS"
        with sums.open("a") as stream:
            stream.write("0" * 64 + "  ../outside\n")
    elif case == "symlink-metadata-directory":
        (root / "meta").rename(root / "real-meta")
        (root / "meta").symlink_to("real-meta", target_is_directory=True)
    elif case in GEOMETRY_CASES:
        updates, _, metadata = GEOMETRY_CASES[case]
        change_geometry(root, updates, metadata)
    else:
        raise AssertionError(case)


class VerifierTests(unittest.TestCase):
    def test_valid_generated_backups(self):
        for write in (1, 256):
            with self.subTest(write=write), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "run"
                create_backup(root, write)
                result = verifier.verify(root)
                self.assertEqual(result["partition_count"], 2)
                self.assertEqual(result["total_partition_bytes"], 12288)
                self.assertIn("not established", result["whole_chip_coverage"])


CASES = ["tampered-image", "short-pair-with-new-hashes", "missing-partition", "failed-status", "symlink-image", "missing-read-evidence", "unhashed-metadata", "wrong-offset-with-new-hash", "unexpected-proc-partition", "bad-archive-with-new-hash", "truncated-later-archive-member", "parent-path-checksum", "symlink-metadata-directory"] + list(GEOMETRY_CASES)


def add_case(case):
    def test(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            create_backup(root)
            corrupt(root, case)
            with self.assertRaises((OSError, ValueError, KeyError, TypeError, tarfile.TarError)) as raised:
                verifier.verify(root)
            if case in GEOMETRY_CASES:
                self.assertIn(GEOMETRY_CASES[case][1], str(raised.exception))
    setattr(VerifierTests, "test_rejects_" + case.replace("-", "_"), test)


for case in CASES:
    add_case(case)

if __name__ == "__main__":
    unittest.main()
