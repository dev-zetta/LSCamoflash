# LSC Indoor 1080p SZ B22705: Fullhan investigation

This camera already provides local RTSP video through its stock firmware. Its hardware and diagnostic shell were identified on **2026-10-14**, but a complete LSCamoflash runtime for this Fullhan platform has not been implemented. Use the stock stream addresses below; do not install the Anyka runtime package or reuse the [3007325.5 camera profile](camera-3007325.5.md).

The observations apply to the tested **SZ B22705 running firmware 7.6.23**. Other cameras sold as “LSC Indoor 1080p” can use different hardware and firmware, including a later Anyka platform.

## What works so far

| Feature | Current evidence |
| --- | --- |
| Main and sub RTSP video | Both stock streams decoded over TCP without RTSP credentials. |
| Diagnostic Telnet | Port 23 opened after booting with the minimal `product.cof` configuration and its FAT read-only attribute. |
| Hardware and flash identification | CPU, kernel, libc, application identity, mounts and six NOR partitions inspected through the stock shell. |
| Firmware backup | All six exposed NOR partitions collected with paired matching reads; the private host copy passed verification of 109 checksummed files. Physical SD remount and restoration remain untested. |
| RTSP audio | Neither tested stream advertised an audio track. Microphone hardware and other audio paths have not been tested. |
| LSCamoflash web UI, ONVIF and automatic SD startup | No Fullhan implementation or device acceptance established. |

Stock RTSP operation does not establish independence from Tuya services, successful operation with internet access blocked, or long-term stability. Those remain separate tests.

## Watch the stock video streams

Find the camera's current address in your router's DHCP leases and open one of these addresses in an RTSP-capable player:

| Stream | Address | Observed video |
| --- | --- | --- |
| Main | `rtsp://<camera-ip>:8554/main` | H.264, 1920×1080, 15 fps |
| Sub | `rtsp://<camera-ip>:8554/sub` | H.264, 640×360, 15 fps |

Each TCP check finished successfully after decoding 76 frames covering five seconds of media, with no RTSP authentication requested. No recording was retained. Their session descriptions contained video only, so the absence of sound in these RTSP tests does not establish a defective microphone.

[Guino's reference](https://github.com/guino/LSC1080P#review) also describes these paths on port 80. Port 80 streaming has not been verified on this exact camera. Use the tested port 8554 endpoints first; the Anyka profile's ports 88/89 and `/videoMain`/`/videoSub` paths do not apply here.

## Diagnostic access through the SD card

The stock `product.cof` setting documented by [guino/LSC1080P](https://github.com/guino/LSC1080P#root-access) enabled Telnet on the tested camera. This provides a diagnostic shell; it does not install LSCamoflash or start its services.

Use a spare card and preserve existing recordings before changing it. The first attempt used FAT32 on the whole card without a partition table. The camera reformatted that card to an MBR layout with a first FAT partition, removing the diagnostic file. On the subsequent attempt, the file was placed on the camera-formatted partition with the FAT read-only attribute set. Telnet then opened on port 23, and the file remained after the second boot. A whole-device FAT layout working on the Anyka camera therefore does not establish suitability here.

With the camera powered off, mount that camera-formatted card on the computer and put a plain-text file named **`product.cof`** directly at its root. The accepted minimal contents were:

```ini
[DEFAULT_SETTING]
telnet=1

```

Use Unix line endings, retaining a blank line after `telnet=1`. Set the file's **FAT read-only attribute (`R`)** before safely ejecting the card. A Unix `chmod` command on a mounted FAT filesystem does not establish that this DOS/FAT attribute is set; use a FAT-aware attribute tool and inspect the result. Do not make the entire card read-only, because stock recording and backup output require writable storage.

Insert the card while the camera is off, power it on, and check its current LAN address. Connect to **Telnet port 23** using the stock login documented in [the reference's root-access section](https://github.com/guino/LSC1080P#root-access). The LSCamoflash web UI and shell defaults for Anyka installations are separate and do not apply to this stock firmware.

Keep this access on a trusted LAN: Telnet sends its session without encryption, and this firmware family has publicly documented credentials. Copying the reference repository's complete toolkit is unnecessary for this minimal diagnostic step. In particular, do not add `[STATION]` Wi-Fi settings or replace startup scripts merely to open the shell; those select other operating modes in related projects.

To stop requesting diagnostic access, power off, retrieve the card, clear the file's FAT read-only attribute if needed, and move `product.cof` away from the card root or remove it. Safely eject and cold-boot, then check whether port 23 is closed and normal camera functions still work. Disabling Telnet and persistence of this setting after marker removal have not yet been physically verified.

## Exact identity

| Item | Observed value |
| --- | --- |
| Product label | LSC Indoor 1080p, SZ B22705 |
| App firmware / MCU version | 7.6.23 / 7.6.23 |
| SoC / kernel hardware field | Fullhan FH8626V100 |
| CPU | ARM1176 family; ARMv6-compatible processor, `armv6l` |
| Linux kernel | 4.9.129 |
| Stock C library | uClibc 0.9.33.2 |
| Stock BusyBox | 1.26.2 |
| Kernel-reported total RAM | 31,320 KiB |
| Stock application | `/usr/bin/dgiot`, 5,807,124 bytes |
| Root filesystem | SquashFS, mounted read-only |
| Persistent configuration | `/etc/conf`, JFFS2, mounted read-write |
| SD mount | `/mnt`, VFAT from `/dev/mmcblk0p1` |

The tested `dgiot` executable has this SHA-256:

```text
ef9545b2f4fce419d71dadf7723a9cb010500c994a87a325a8c325b51648c8b2
```

This identity is a compatibility boundary. An application with a different hash requires its own inspection; settings, binary offsets and runtime hooks from another firmware must not be assumed compatible. The stock binary and recovered configuration remain private and are not included in this repository.

## NOR layout and backup status

The live proc/sysfs inventory exposed six NOR partitions. Their reported offsets and sizes form a contiguous 8 MiB address range:

| MTD | Name | Offset in bytes | Size in bytes |
| --- | --- | ---: | ---: |
| `mtd0` | `bootstrap` | 0 | 262,144 |
| `mtd1` | `uboot-env` | 262,144 | 65,536 |
| `mtd2` | `uboot` | 327,680 | 262,144 |
| `mtd3` | `kernel` | 589,824 | 1,900,544 |
| `mtd4` | `rootfs` | 2,490,368 | 5,570,560 |
| `mtd5` | `config` | 8,060,928 | 327,680 |
| **Total** | | | **8,388,608** |

The inventory reports 65,536-byte erase blocks, a one-byte write unit and no OOB data. These observations identify the exposed layout; they do not establish physical chip coverage or a working restoration procedure. Do not concatenate partition files into a guessed flash image or apply another device's recovery image.

The manual collection completed on this exact camera, producing two matching reads of each of the six partitions, totaling **8,388,608 partition bytes**, and a **12,785,664-byte stock userspace archive**. After transfer to private host storage, the verifier checked the complete manifest, partition lengths and read pairs, and **109 checksummed files**. The recovered `dgiot` executable also matched the live application's SHA-256 above. The earlier failed attempt was retained separately.

Additional checked file and directory `fsync` calls, including the SD root, returned success before transfer. They used BusyBox `sync FILE` without `-f`. The completed backup was transferred through an authenticated FTP service restricted to the camera and verified on the host; this was a temporary transfer arrangement, not a Fullhan runtime FTP service. A fresh physical SD remount/readback and a restore have not been performed.

Writable stock configuration can change while the camera runs, so matching reads do not establish an atomic snapshot of the entire device. Keep partition images, userspace archives, credentials and raw logs in private host storage. This guide intentionally provides no flash erase, write or restore procedure.

## Manual backup through the stock shell

The repository's [NOR backup tools](../tools/firmware-backup/README.md) separate the reusable collector from the Anyka-specific SD launcher. On this Fullhan camera, collection is started manually through the existing authenticated diagnostic shell. Use only the collector script and its compatible static BusyBox in a dedicated directory on the writable, camera-formatted SD card. Do not install the Anyka `hostapd` launcher or its `_ht_ap_mode.conf` / `_ht_get_log.conf` markers.

Before collection, confirm the exact application/hardware identity, the live NOR inventory and the writable VFAT mount at `/mnt`. The collector checks the visible mount and device, bounds each operation, retains independent read pairs and writes each attempt into a new `firmware-backup/run-*/` directory. Its optional process-map collection now tolerates a stock process exiting during inspection; this correction passed 66 focused host and ARM tests before the successful device capture.

Keep the complete run directory and its metadata together when transferring it to the host, then run the [host verifier](../tools/firmware-backup/verify-backup.py). Check its exit status and `verified: true` result before treating the copy as a verified backup. Preserve failed attempts for diagnosis, and keep the additional checked file/directory flush and physical remount limits above separate from host checksum verification. Preparing the runtime or modifying startup files is unnecessary for this software backup path.

## What a Fullhan port still needs

This camera starts `dgiot` rather than the Anyka `anyka_ipc` application. The Anyka native `hostapd` hook, SD overlay assumptions and RTSP callback preload were developed for another startup path and binary ABI. They are not compatible Fullhan components.

No automatic custom-script startup from the stock SD card has been established. Guino's non-flashing customization uses an external host to start tools after reboot; that is a separate design from a self-starting LSCamoflash runtime. A Fullhan port still needs a validated startup method, its own service and configuration integration, resource measurements, and repeatable reboot/streaming acceptance. Stock Telnet and RTSP working are useful investigation results, not full runtime support.

## Related primary references

- [guino/LSC1080P](https://github.com/guino/LSC1080P) documents the `product.cof` Telnet setting and stock RTSP paths on a related device running firmware 7.6.32. Its exact-version evidence is separate from the 7.6.23 observations above.
- [berobloom/LSCIndoorCameraLocal1080p](https://github.com/berobloom/LSCIndoorCameraLocal1080p) explicitly targets the 2021 Fullhan variant and describes a different TUTK development mode. Its flash-modifying setup is not a verified installation procedure for this camera.
- [berobloom/LSC-1080p-Anyka-Decloud](https://github.com/berobloom/LSC-1080p-Anyka-Decloud) targets a separate 2025 Anyka variant. A similar housing or product name does not make that platform's instructions applicable to the identified FH8626V100 unit.

When reporting another unit, include its label, app/MCU versions, observed hardware identity and stream behavior through this fork's [issue tracker](https://github.com/dev-zetta/LSCamoflash/issues). Redact network credentials, serial numbers and account identifiers before sharing diagnostics.
