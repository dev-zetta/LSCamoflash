# Changelog

## Unreleased

### Features

- Add a separate experimental Fullhan FH8626V100 / SZ B22705 firmware 7.6.23 management interface with mandatory authentication, CPU/SD/RAM/service diagnostics, finalized MP4 recording lists and range-aware downloads, and stock RTSP links. Its SD-only package has exact firmware guards, manual startup and owned-process shutdown; it keeps the stock application running. Camera settings, audio and automatic startup remain outside this port.
- Add an optional static Fullhan ONVIF Device/Media server with WSSE UsernameToken or HTTP Digest authentication, anonymous clock bootstrap for timestamp synchronization, native main/sub H.264 profiles, bounded discovery and guarded independent startup/shutdown. Unsupported camera mutations, PTZ and snapshots return faults.
- Build and upload the credential-free Fullhan management package separately in CI, including ARM1176 compatibility and SOAP checks. Private site authentication is never included in the public payload.

### Fixes

- Include the separate Fullhan recording and discovery helpers in CodeQL extraction by compiling their production branches explicitly.
- Support SHA-256 HTTP Digest in the ONVIF test client on Python 3.11 and 3.12, preserving the server's authentication algorithm and adding an independent protocol test vector.
- Keep NOR firmware collection running when an optional process disappears during `/proc` inspection, and discard incomplete optional map snapshots. Required flash metadata and paired-read verification remain strict.
- Verify the Fullhan FH8626V100 SZ B22705 / firmware 7.6.23 diagnostic entry and manual backup path: all six exposed NOR partitions have matching repeated reads, totaling 8 MiB, with a host-verified stock userspace archive. Proprietary firmware and configuration remain private.

### Documentation

- Rework the English and German READMEs around compatibility, release downloads and first setup; move build instructions, configuration, SD layout and troubleshooting details into dedicated guides under `docs/`.
- Correct fork download, badge, support, web UI, shell-banner and build-source links while retaining upstream attribution and original issue/PR references.
- Document ready-made backup-kit downloads and separate web UI/root passwords; replace stale autobuild, camera-acceptance and deleted CI-run links.
- Enable the fork's issue tracker and private vulnerability reporting, and point support/security instructions to those channels.

## [1.03.2413] - 2026-10-13

First release of the `dev-zetta/LSCamoflash` fork, based on upstream 1.03.2412 and the subsequent upstream source history. Release packages, checksums and source are provided on the [v1.03.2413 release page](https://github.com/dev-zetta/LSCamoflash/releases/tag/v1.03.2413).

### Changes

- Integrate upstream PRs [#5](https://github.com/Bunkerschild/LSCamoflash/pull/5), [#6](https://github.com/Bunkerschild/LSCamoflash/pull/6), [#8](https://github.com/Bunkerschild/LSCamoflash/pull/8) and [#9](https://github.com/Bunkerschild/LSCamoflash/pull/9), retaining their original commits: build and USB-reader installation fixes, RTSP/ONVIF configuration repair, Wi-Fi association before DHCP, and IPC-XC-C323 detection/PTZ with valid motor JSON responses.
- Add an exact stock firmware profile for LSC Smart PTZ Camera 3007325.5 / SI L25502, build 6.2863.125.1348. Preserve the verified stock executable, software-settings schema, motor calibration and stock network-tool aliases; reject incompatible binary identities and manufacturing-mode markers.
- Enable local RTSP through guarded video and encoded-audio callbacks for that exact profile. Physical checks decoded H.265 main video at 2304×1296, H.264 sub video at 640×360 and 8 kHz mono PCMA on both streams over TCP and UDP after reboot. The user confirmed audible microphone sound. Manual ONVIF Device/Media requests correctly select the H.264 substream.
- Add a separate SD firmware backup kit with a static ARM launcher, bounded operations, double reads, exact sizes and SHA-256 verification. Physical verification recovered all eight exposed NOR partitions totaling 8 MiB and a matching stock userspace archive from the documented camera; no proprietary firmware or private device data is distributed.
- Repair ARM/uClibc builds, verified Git LFS download hydration, current host-tool/CMake compatibility and explicit version handling. Check packaged ARM executables, preload behavior, bootstrap entry points and archive contents instead of treating archive creation alone as validation.
- Make Linux SD installation stop on disk-selection, partition, mount or copy failures. Support native bootstrap on the traditional two-partition layout and a single FAT card; bound init and service startup, retain diagnostics, preserve stock process handoff and replace running update files through temporary files and renames.
- Correct RAM reporting to use `MemAvailable`, with a labelled free-memory fallback and cache counters, and make SD status valid for whole-device FAT, one-partition and two-partition layouts.
- Extend host and ARM926 regression coverage for bootstrap, runtime modes, networking, updates, backup geometry, callback ABI and teardown. Resolve bare QEMU executable names before isolated PATH changes and exercise child exec through PATH. Release validation requires these checks and artifact verification before publication; workflows use pinned Node 24-compatible actions.

### Compatibility and remaining limits

- Local RTSP mode replaces normal Tuya app operation. The 3007325.5 profile uses ports 88 `/videoMain` and 89 `/videoSub`; older profiles have different endpoints and mode markers. Follow the [camera guide](https://github.com/dev-zetta/LSCamoflash/blob/v1.03.2413/docs/camera-3007325.5.md), including explicit Wi-Fi configuration for a cold local-mode boot.
- ONVIF requires manual connection; WS-Discovery is not bundled. The ONVIF server advertises the H.264 substream because it cannot represent the H.265 main stream. Toolkit PTZ remains disabled for 3007325.5 despite its two physical motors.
- Short device checks and audible microphone confirmation do not establish long-term memory stability, detailed audio/video synchronization, multiple-client behavior, recording or all Tuya functions. Earlier failed attempts and the observed OOM history are recorded in the [integration notes](https://github.com/dev-zetta/LSCamoflash/blob/v1.03.2413/docs/integration.md).
- Backup verification covers the exposed partition collection, not proven whole-chip coverage or a tested flash restore. The kit does not program flash, but stock startup can change persistent configuration before the SD hook runs; see the [backup procedure](https://github.com/dev-zetta/LSCamoflash/blob/v1.03.2413/docs/firmware-backup.md).
- Generic fixes address reported startup/configuration blockers, but issues [#4](https://github.com/Bunkerschild/LSCamoflash/issues/4) and [#10](https://github.com/Bunkerschild/LSCamoflash/issues/10) still need their exact stock binaries and device tests. Issue [#7](https://github.com/Bunkerschild/LSCamoflash/issues/7) has reporter-confirmed C323 stock factory RTSP behavior; that evidence does not validate other revisions. Integrating changes in this fork does not close upstream PRs or issues.

See [release and installation notes](https://github.com/dev-zetta/LSCamoflash/blob/v1.03.2413/docs/release.md) for the full runtime, update archive and separate backup kit. Project code and bundled third-party components retain their respective licenses; release source and notice assets accompany the binary packages.
