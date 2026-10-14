# Back up stock LSC camera firmware through the SD boot hook

The reusable [backup kit](../tools/firmware-backup/README.md) was physically verified on an LSC Smart PTZ Camera, SI L25502, article **3007325.5**, app firmware **V1.0.0 (6.2863.125)**, exact build **6.2863.125.1348**. It recovered all eight exposed MTD partitions, totaling **8,388,608 bytes**, with two matching reads of every partition, a stock userspace archive and matching library files. USB on this unit did not expose a firmware interface. This procedure uses its existing SD boot hook; it does not require an installed LSCamoflash runtime.

The kit does not erase, program or restore flash. Stock startup itself copies the empty AP marker to persistent `/etc/config/hostapd.conf` before invoking the kit, and performs its normal configuration maintenance. The result is a backup taken after those startup effects, rather than a pristine pre-boot configuration. Removing the SD markers does not undo persistent stock changes. Whole-chip coverage and a successful restore have not been established. Other camera revisions must be checked separately; this tool rejects NAND and unsupported NOR geometry.

Backups, configuration archives and logs can contain Wi-Fi, cloud and device credentials. Keep the complete result in private storage. Share the public scripts and redacted technical findings, not your firmware dump or raw logs.

For the Fullhan SZ B22705 running 7.6.23, use its separate [manual backup entry](camera-sz-b22705.md#manual-backup-through-the-stock-shell). Its six exposed NOR partitions and stock userspace were verified through the collector and host verifier. The Anyka SD `hostapd` launcher and AP markers below do not apply to that camera.

## Download or build the kit

Download `LSCamoflash-<version>-backup-kit.tar.gz` and `SHA256SUMS` from the [fork's latest release](https://github.com/dev-zetta/LSCamoflash/releases/latest), verify the archive against its checksum, and extract it into a new folder. The kit contains `card/`, `verify-backup.py`, instructions, a manifest and checksums. It requires no runtime installation or compilation. Python 3.9 or later is needed for host verification.

The archive contains a versioned top-level directory. Set `KIT_DIR` to that directory, replacing the example version with the release you downloaded:

```sh
KIT_DIR="$PWD/LSCamoflash-1.03.2413-backup-kit"
(cd "$KIT_DIR/card" && sha256sum -c SHA256SUMS)
```

For a source build instead, follow [Building and testing](building.md), then run `make -C SOURCE backup-kit` from the repository root. This creates host-side files in `SOURCE/backup-kit/`; set `KIT_DIR="$PWD/SOURCE/backup-kit"`. The [tool guide](../tools/firmware-backup/README.md#build) describes compiler/BusyBox overrides and optional ARM926 checks.

The `card/` payload contains `hostapd`, `busybox`, `dump.sh`, `_ht_ap_mode.conf`, `_ht_get_log.conf` and `SHA256SUMS`. Only these card files belong on the SD root; keep the host verifier on your computer. The kit includes no proprietary stock firmware.

## Prepare a spare card

Use a spare, mounted FAT32 microSD card with sufficient free space. For the tested camera with 8 MiB of exposed NOR, allow at least 512 MiB free. Other accepted partition inventories can require more; the dumper calculates its reserve and refuses insufficient space. The verified camera accepted a whole-device FAT32 card without a partition table. A FAT32 first partition is also understood by its stock mount script. This backup procedure does not need LSCamoflash's two-partition runtime layout. Do not run the destructive runtime installer or disk preparation script merely to take a backup.

With the camera powered off and the spare card mounted on the computer, copy only the kit's `card/` contents to its root. Use your actual mount path below. The interactive copy protects existing filenames from silent replacement; use a clean spare card if it already contains another `hostapd` hook or firmware update files.

```sh
CARD_MOUNT="/media/your-user/CAMERA"
cp -i "$KIT_DIR/card/hostapd" "$KIT_DIR/card/busybox" "$KIT_DIR/card/dump.sh" "$KIT_DIR/card/SHA256SUMS" "$CARD_MOUNT/"
cp -i "$KIT_DIR/card/_ht_ap_mode.conf" "$KIT_DIR/card/_ht_get_log.conf" "$CARD_MOUNT/"
(cd "$CARD_MOUNT" && sha256sum -c SHA256SUMS)
sync
```

Do not copy firmware update `.bin` files, `update.tar` or recovery markers to the card root. Do not mix the backup hook with the runtime hook: they use the same `hostapd` filename. Close file-manager windows and safely eject the card through your operating system before removing it.

## Capture and verify

1. Insert the card into the powered-off camera, then power it on. Give startup and the backup about five minutes. The camera can be unavailable in the app during this AP boot attempt; do not reset or re-pair it to address that temporary state.
2. Power the camera off before removing the card, then mount the card on the computer. Look for `backup-launcher.log` at its root and `firmware-backup/run-*/` directories. The camera clock may start in the year 2000, so the timestamp alone does not establish when a capture happened.
3. Copy the entire `firmware-backup/` directory and root diagnostic log into private host storage. Retain failed attempts too. Verify the chosen run with the host-side script:

```sh
python3 "$KIT_DIR/verify-backup.py" "/private/path/firmware-backup/run-TIMESTAMP-PID"
```

A successful command exits zero and reports `verified: true`, the partition count, total bytes and individual SHA-256 hashes. On the tested unit, `status.txt` reported `VERIFIED_NOR_BACKUP`, eight partitions and 8 MiB. The verifier checks the complete recorded inventory and archive payloads without executing or extracting the recovered firmware. A partial archive or a nonzero exit is not a verified backup. Keep the paired partition files and metadata together; do not concatenate them into a guessed flash image.

The dumper has a 240-second monotonic budget, per-command timeouts, up to three paired read attempts, explicit size limits, and strict visible MMC/FAT mount checks. Kernel I/O stuck in an uninterruptible state cannot be bounded by a userspace timeout. Missing output is not proof that the hook never ran: the launcher intentionally writes no log when it cannot establish a safe SD destination. Inspect the launch log and incomplete run status before changing the procedure.

## Disable the backup hook

After verifying and copying the result, move the two root markers into an ordinary nested directory on the card while the camera is off:

```sh
mkdir -p "$CARD_MOUNT/diagnostic-archive/disabled-backup-kit"
mv -i "$CARD_MOUNT/_ht_ap_mode.conf" "$CARD_MOUNT/_ht_get_log.conf" "$CARD_MOUNT/diagnostic-archive/disabled-backup-kit/"
sync
```

The exact tested firmware checks these marker names only at the card root. Nested diagnostic files and backups therefore do not reactivate this hook. Keep the backup output; deleting it is unnecessary. Safely eject the card, cold-boot the camera, and check normal app access, Wi-Fi and recordings. These acceptance checks and restoration are separate from successful backup verification.

## Developer checks

The following commands are for a source checkout; see [Building and testing](building.md) for its dependencies.

The [public fixtures](../tests/) synthesize devices, mounts and partition contents. They do not read real MTD devices, mount cards or require the private firmware dump:

```sh
python3 -m unittest discover -s tests -p 'test_firmware_backup*.py' -v
```

Set `BACKUP_ARM_CC`, `BACKUP_ARM_BUSYBOX` and `BACKUP_QEMU` to executable paths to include ARM926 tests. Production binaries never enable the fixture mount/device substitutions. The NOR write-unit allowlist includes the tested vendor report of 256 bytes with zero OOB; that observation is not a universal rule for all NOR drivers.
