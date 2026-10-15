# Read-only NOR firmware backup kit

The generic collector reads every exposed NOR MTD partition twice, checks exact byte counts and matching SHA-256 hashes, and saves the stock userspace files and matching libraries. Its entry mechanism depends on the camera: the legacy kit uses the stock SD-card AP hook, Fullhan uses a manual shell, and YYOS requires a separate normal-boot payload. The native launcher runs synchronously, captures bounded diagnostics, and starts the supplied static BusyBox and dumper through verified open file descriptors. It does not mount filesystems, change networking, or write flash.

The complete path was physically verified on LSC Smart PTZ Camera 3007325.5 / SI L25502, firmware V1.0.0 (6.2863.125), with eight exposed partitions totaling 8 MiB. That result establishes partition backup and host verification. Whole-chip coverage, restoration, and compatibility with other hardware or firmware remain separate questions. Backups and logs can contain device credentials and identifiers; keep them private.

The collector was also verified through an authenticated manual shell on [Fullhan SZ B22705, firmware 7.6.23](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-sz-b22705.md#manual-backup-through-the-stock-shell), collecting all six exposed NOR partitions totaling 8 MiB. That path reuses only the static BusyBox and collector; do not install this kit's Anyka `hostapd` or AP markers on Fullhan. Use current source containing the optional-process race fix for that manual procedure.

For [LSC 3225722 / SZ F26312, app firmware V14.1.5](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-3225722.md), the normal-boot YYOS entry and identity-only collection were physically verified: root execution completed, and 101 diagnostic files passed checksums after a physical SD remount and private host copy. Its six-partition NOR geometry is known, but paired-read backup and runtime acceptance remain pending. Use the camera guide's [separate source-build procedure](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-3225722.md#build-a-separate-yyos-nor-kit); the legacy `hostapd`/AP kit and released v2.00.0000 backup-kit card payload are not its boot mechanism.

## Build

The commands in this section build the legacy AP-hook kit for the documented 3007325.5 procedure. YYOS users must instead build `build-yyos-kit.py` as described in the linked camera guide. Both source builders operate on host directories only; neither formats, mounts or writes a card.

Use Python 3.9 or later, the repository's ARM uClibc toolchain, and its built static BusyBox. The default paths are resolved relative to this repository, regardless of the working directory:

```sh
python3 tools/firmware-backup/build-kit.py
```

Override inputs and the dedicated build output if needed:

```sh
python3 tools/firmware-backup/build-kit.py --cc /path/to/arm-gcc --busybox /path/to/busybox --readelf /path/to/arm-readelf --output /path/to/backup-kit
```

`CC`, `BB`, and `READELF` provide the corresponding defaults. Optional `--qemu /path/to/qemu-arm` or `QEMU_ARM` checks BusyBox's required applets and execution with an ARM926 CPU. The builder always checks that both binaries are static ARMv5TE/ARMv5TEJ EABI5 executables without the hard-float ABI. It never copies files onto a card. Rebuilding replaces only a recognized output with the exact generated inventory; additional files cause refusal.

The default output is `SOURCE/backup-kit/`, separate from the runtime build tree. It contains `card/`, the host verifier, this guide, a manifest, and checksums. Only the contents of the correct model's `card/` belong at the SD root. Use the [model-specific backup procedure](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/firmware-backup.md) before staging or booting the kit. Do not put raw partition images or firmware update files at the SD root. The output contains no private firmware or credentials.

The separate YYOS builder requires an explicit `--output` directory that is absent or empty and refuses to replace any existing kit. Its `card/` contains exactly `telnetd`, `busybox`, `dump.sh`, empty `yy_telnet_start` and `SHA256SUMS`; `dump.sh` is the generic paired-read NOR collector, not the identity-only script. The native `telnetd` filename selects the stock YYOS SD entry without starting a Telnet daemon. Its host package also retains the verifier, provenance manifest, checksums and project/BusyBox licenses. The physical investigation has tested the entry and independently staged components; acceptance of the new builder's assembled payload remains separate.

## Capture and verify

The launcher accepts only an existing writable FAT mount backed by the visible MMC block device. It handles stock firmware's covered tmpfs mount entries, and rejects ambiguous same-device mounts, symlinked paths, nonregular inputs or logs, and oversized diagnostic logs. The dumper separately checks the visible filesystem and device identity. It requires root, NOR type, no OOB data, and a write unit of 1 or the observed vendor value 256 with consistent aligned geometry. NAND requires a different ECC/OOB-aware procedure.

Each run goes under `firmware-backup/run-*/`. Repeated clock values and process IDs select a new numeric suffix, with at most 64 atomic directory attempts; existing runs remain untouched. Failed attempts and the early stock userspace archive remain available for diagnosis. Operations have individual timeouts and a 240-second monotonic budget; kernel I/O stuck in an uninterruptible state cannot be bounded by a userspace timeout. The script does not concatenate images or claim that partition coverage proves physical-chip coverage.

The userspace archive includes the standard trees and any present `/appfs` and `/config` trees, preserving symlinks and the stock application/library set. Optional process maps and executable links are collected only for exact `anyka_ipc` or `yy_cam` names with numeric PIDs. A disappearing process or failed optional snapshot is skipped without keeping a partial snapshot; required flash metadata, complete partition reads and checksum verification remain mandatory. Archive contents and logs can include credentials and must remain private.

After powering the camera off and retrieving the card, copy the entire run directory to private host storage and verify it:

```sh
python3 tools/firmware-backup/verify-backup.py /path/to/firmware-backup/run-TIMESTAMP-PID
```

The verifier reads files and archives without extracting them. It requires successful status, all exposed partitions, two matching reads of each partition, consistent hashed metadata, exact sizes, complete archive payloads, and successful read-attempt records. A zero exit status validates the collected backup; it does not validate restoration.

For the legacy AP-hook kit, remove the root `_ht_ap_mode.conf` and `_ht_get_log.conf` markers from the card or move them into an ordinary nested archive directory before a later normal cold boot. On the verified firmware, stock startup reads only these exact root paths. Stock startup copies the AP marker to persistent `/etc/config/hostapd.conf`; using the empty marker therefore leaves that file empty. Removing the markers does not restore persistent stock configuration. Normal network, app, and SD operation must be checked after the next boot.

For the separate YYOS kit, disable only the card-root `yy_telnet_start` marker after copying and verifying the results. Keep the complete output and follow the [camera guide](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-3225722.md#capture-verify-and-disable) for safe removal and subsequent normal-operation checks. Do not introduce legacy AP, debug or factory markers to disable or troubleshoot that entry.

## Offline regression tests

```sh
python3 -m unittest discover -s tests -p 'test_firmware_backup*.py' -v
python3 -m unittest discover -s tests -p 'test_yyos*.py' -v
```

Host tests need a C compiler and BusyBox with the listed applets. They use generated files and fixture-only replacements for physical filesystem and device checks. They never open real MTD devices, mount filesystems, or use a camera. Optional ARM tests use `BACKUP_ARM_CC`, `BACKUP_ARM_BUSYBOX`, and `BACKUP_QEMU` executable paths and force an ARM926 CPU. Production builds never enable the fixture macro.
