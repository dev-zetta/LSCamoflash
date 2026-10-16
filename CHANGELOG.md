# Changelog

## Unreleased

No changes yet.

## [2.01.0000] - 2026-10-16

This release adds a separate experimental YYOS package for **LSC 3225722 / SZ F26312 / V14.1.5 / AK3918AV130**. Use `LSCamoflash-2.01.0000-yyos.tar.gz` from the [v2.01.0000 release page](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.01.0000) and follow [private provisioning and setup](docs/yyos-setup.md). Existing Anyka and Fullhan cameras retain their separate packages; matching a retail name alone does not establish compatibility.

### Features

- Add authenticated Dashboard, Recordings, Streams and Diagnostics views, optional indicator/timestamp switches, short cardinal movement commands and Stop. Controls require the camera's private local key and stock tracking off before movement; a detached pre-armed Stop guardian, operation lock and strict authenticated same-origin CGI limit the action set. See [controls and limits](docs/yyos-controls.md).
- Add key-only SSH administration and checked SD-file transfer, plus authenticated raw recording/metadata downloads and a host converter for the observed unencrypted v5 H.264/PCMU format. No recording deletion or browser media playback is supplied.
- Add a guarded Linux plan/provision/install helper that preserves recognized credentials, logs and recordings, verifies staged bytes and arms the normal marker last. The public package contains no proprietary firmware, web/native credentials or SSH private keys; HTTP/controls/SSH require private provisioning, and SSH defaults disabled.
- Add exact-profile identity/NOR collectors and an explicit SSH-guarded native setup with fresh binary/flag/listener checks, durable private preservation and one-attempt journals. Legacy unguarded `configure` remains blocked; the accepted guarded trial retained the existing 15-byte password.

### Fixes

- Read native setup and cosmetic-setting results through an independent authenticated session after observed stale/failing same-connection readback. Preserve failed results and separate resolution evidence; password/enable/setting writes are not replayed automatically.
- Limit new native passwords to 8–15 ASCII bytes after confirming unsafe 16-byte stock password caches. Keep the earlier 24-byte boot-loop and verified configuration-off recovery evidence in the [camera](docs/camera-3225722.md) and [recovery](docs/yyos-recovery.md) guides; the exact earlier crash path remains unproven.
- Build static musl SSH/controls with a narrow legacy-clock adapter for this kernel's success-without-output time64 stub, retaining typed-clock checks and fail-closed deadlines. The kernel and stock application are not replaced.

### Provenance

- Include pinned component sources/notices, recipes, relinkable objects and exact compiler/clock/crypto provenance for BusyBox, musl and Dropbear-based components. The package is not solely MIT-licensed and excludes device firmware/configuration and private keys.
- Build the separate YYOS asset in CI with explicit ARM/runtime inputs, validate its public inventory and provenance, and include production recording/control helpers in CodeQL extraction.

### Validation and limits

- Host/ARM926 fixtures and fresh package builds passed, alongside bounded live HTTP/authentication, owned HTTP restart, recording downloads, desktop/mobile navigation, SSH/root PTY and SD round-trip checks. The installer itself has not yet been used on a physical card; the packaged musl SSH build passed temporary-server checks, with its own normal boot still unverified.
- Native H.264 main/sub video and PCMU audio decoded over TCP/UDP; RTSP Digest and ONVIF WSSE authorization controls passed. One earlier enabled normal boot passed short checks, and the owner accepted recorded microphone sound and Tuya app connectivity. The later guarded disable/setup retaining the existing password also passed, with both streams decoded afterward; that trial does not establish a new cold boot, first provisioning or a different password.
- Indicator/timestamp off/on, manual Stop and short horizontal movement passed live checks; the owner subsequently confirmed camera operation and rotation. This does not establish every axis, a physical 200 ms deadline, simultaneous app control or long-term motor safety.
- Direct VLC live playback, detailed synchronization/app/recording behavior, repeated boots, endurance and general ONVIF/PTZ compatibility remain open. The verified six-partition / 8 MiB NOR backup establishes paired reads and post-remount host verification, not whole-chip coverage, atomicity or restore. Detailed evidence and earlier failures remain in the linked [camera guide](docs/camera-3225722.md).

## [2.00.0000] - 2026-10-14

This major release introduces distinct Anyka runtime and experimental Fullhan management packages. The project keeps its custom `major.minor.revision` numbering (`2.00.0000`); the package choice follows the camera’s exact platform and firmware. Downloads and checksums are on the [v2.00.0000 release page](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.00.0000).

### Features

- Add a separate experimental Fullhan FH8626V100 / SZ B22705 firmware 7.6.23 management interface with mandatory authentication, CPU/SD/RAM/service diagnostics, finalized MP4 recording lists and range-aware downloads, and stock RTSP links. Its SD-only package has exact firmware guards, manual startup and owned-process shutdown; it keeps the stock application running. Camera settings, audio and automatic startup remain outside this port.
- Add an optional static Fullhan ONVIF Device/Media server with WSSE UsernameToken or HTTP Digest authentication, anonymous clock bootstrap for timestamp synchronization, native main/sub H.264 profiles, bounded discovery and guarded independent startup/shutdown. Unsupported camera mutations, PTZ and snapshots return faults.
- Publish a separate credential-free `LSCamoflash-2.00.0000-fullhan.tar.gz` release asset and build it independently in CI, including ARM1176 compatibility and SOAP checks. It contains the required `LSCamoflash-fullhan/` folder; private dashboard/ONVIF authentication and endpoint UUID must be provisioned before use.

### Fixes

- Accept positive decimal major versions in build/release validators and the explicit version helper; major/minor bumps reset lower counters to zero, and invalid or overflowing changes preserve the prior version.
- Build an isolated Fullhan BusyBox with a scoped HTTP Range-to-CGI fix, preserving the shared Anyka and stock binaries. Live authenticated recording requests now return correct partial responses through the complete HTTP path.
- Include the separate Fullhan recording and discovery helpers in CodeQL extraction by compiling their production branches explicitly.
- Support SHA-256 HTTP Digest in the ONVIF test client on Python 3.11 and 3.12, preserving the server's authentication algorithm and adding an independent protocol test vector.
- Keep NOR firmware collection running when an optional process disappears during `/proc` inspection, and discard incomplete optional map snapshots. Required flash metadata and paired-read verification remain strict.
- Verify the Fullhan FH8626V100 SZ B22705 / firmware 7.6.23 diagnostic entry and manual backup path: all six exposed NOR partitions have matching repeated reads, totaling 8 MiB, with a host-verified stock userspace archive. Proprietary firmware and configuration remain private.

### Documentation

- Rework the English and German READMEs around compatibility, release downloads and first setup; move build instructions, configuration, SD layout and troubleshooting details into dedicated guides under `docs/`.
- Correct fork download, badge, support, web UI, shell-banner and build-source links while retaining upstream attribution and original issue/PR references.
- Document ready-made backup-kit downloads and separate web UI/root passwords; replace stale autobuild, camera-acceptance and deleted CI-run links.
- Enable the fork's issue tracker and private vulnerability reporting, and point support/security instructions to those channels.

### Compatibility and validation

- **Anyka:** keep using the full `-uclibc.tar.gz` runtime or matching `update-...-uclibc.tgz` for supported profiles. The tested 3007325.5 / 6.2863.125.1348 profile retains local H.265 main/H.264 sub video and PCMA audio, explicit local-mode Wi-Fi, manual H.264 ONVIF and disabled toolkit PTZ. Its local mode replaces Tuya app operation; detailed and long-term limits remain in the [camera guide](https://github.com/dev-zetta/LSCamoflash/blob/v2.00.0000/docs/camera-3007325.5.md).
- **Fullhan:** SZ B22705 / FH8626V100 with stock firmware 7.6.23 requires the separate `-fullhan.tar.gz` package, mandatory private credentials and manual startup after each reboot. Keep the stock application running; do not use Anyka installers, overlays or boot hooks. Stock H.264 main/sub video remains on port 8554, with no audio track advertised in the verified streams.
- Fullhan recording lists, authenticated HEAD/Range, WSSE and HTTP Digest ONVIF profiles/stream URIs, an independent Zeep client, and owned stop/restart passed short live checks. The optional port-5000 server must be added manually with `--no-discovery` because stock `dgiot` owns UDP 3702 and advertises a separate port-835 endpoint whose SOAP control path remains unverified. Only read-only `GetSystemDateAndTime` is anonymous for WSSE clock synchronization; protected Device/Media operations retain authentication and timestamp/replay checks.
- Fullhan camera controls, PTZ, microphone forwarding and automatic startup are not implemented. Long-term or multiple-client use, normal app/recording behavior, internet-blocked operation, repeatable cold-boot acceptance and restore remain separate gates. See the [Fullhan guide](https://github.com/dev-zetta/LSCamoflash/blob/v2.00.0000/docs/camera-sz-b22705.md) for exact binary identity, measured resources and bounded evidence.
- The separate firmware backup kit is not a runtime installer or recovery image. Its Anyka SD launcher must not be used on Fullhan; the verified Fullhan backup uses the generic collector through the stock shell. Proprietary firmware, credentials and logs are excluded from every release asset. Matching exposed-partition backups do not prove whole-chip coverage, atomic capture or a working restore.

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
