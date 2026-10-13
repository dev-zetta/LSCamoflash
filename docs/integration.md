# Fork integration and camera compatibility

This fork starts at upstream commit `40bf27bcd782139e05b7067761cad337cf52d1fd`. The inventory below was retrieved from GitHub on 2026-10-12. Upstream pull requests and issues remain owned by their original repository; merging their commits here does not close them upstream.

## Integrated pull requests

All four open pull requests were merged with their original commits and attribution preserved.

| Upstream PR | Integrated head | Change |
| --- | --- | --- |
| [#5](https://github.com/Bunkerschild/LSCamoflash/pull/5) | `78999982bf40b5d5850a58321045b818afc7cc9d` | 64-bit build fixes and SD installation through USB readers. |
| [#6](https://github.com/Bunkerschild/LSCamoflash/pull/6) | `16220de1d69ae401f7d516b9d3111af6f5189d5b` | Correct the `anyka_cfg.ini` existence check before enabling RTSP/ONVIF. |
| [#8](https://github.com/Bunkerschild/LSCamoflash/pull/8) | `6049046d650911919a243dba12f95bf81813c7aa` | Poll Wi-Fi association for up to 30 seconds before starting DHCP. |
| [#9](https://github.com/Bunkerschild/LSCamoflash/pull/9) | `be20358f95ea1da3d8c012f2f8ee09d948aa83e5` | IPC-XC-C323 model detection and PTZ offsets, and suppress motor diagnostics in JSON responses. |

The installer additionally validates the selected whole removable disk, checks command failures, accounts for partition alignment and releases temporary mounts. Installer tests replace disk commands with stubs; they never erase a real disk. On Debian/Ubuntu, the Linux installer requires `dosfstools`, `fdisk`, `parted`, `udev` and `util-linux`, plus Bash and coreutils. It asks for the whole device name twice and refuses to proceed after a failed unmount or partition operation. PTZ offsets in PR #9 were verified on hardware by its author. This fork's initial build validation did not use a camera; subsequent work physically verified the [3007325.5 backup procedure](firmware-backup.md) and added its [experimental runtime profile](camera-3007325.5.md). That evidence does not validate PR #9 on different hardware.

## Open issue disposition

| Issue | Evidence and action | Remaining requirement |
| --- | --- | --- |
| [#7: IPC-XC-C323 RTSP](https://github.com/Bunkerschild/LSCamoflash/issues/7) | The [reporter's final update](https://github.com/Bunkerschild/LSCamoflash/issues/7#issuecomment-5477018872) confirms stock factory mode provides `554/main_ch` and ONVIF on port 5000 without an IPS patch. PR #6 fixes the prerequisite config block. This fork makes explicit local mode select the stock binary before any patched binary. | Recheck the updated startup on the camera. Concurrent operation of RTSP and the patched Tuya runtime has not been established. |
| [#4: outdoor FW 3.10.68.4](https://github.com/Bunkerschild/LSCamoflash/issues/4) | MD5 `08157e4568ca2df26f359003621d1a25`, 5,198,324 bytes. The report offers to upload the original binary, but none was supplied in the issue or comments. Generic config/startup fixes apply, and an unknown checksum does not itself prevent the web services from starting. | Original `anyka_ipc` plus startup logs and a device test are needed for a revision-specific patch and verified compatibility. |
| [#10: indoor TuyaOS 6.2.8](https://github.com/Bunkerschild/LSCamoflash/issues/10) | MD5 `419007fd0f4d23175549286045d865db`, 5,318,856 bytes. No original binary was attached. The report says its main stream is H.265; factory-mode behavior must be tested separately from the older C323. | Original `anyka_ipc`, relevant matching vendor libraries and startup logs, followed by a device test. |

Issues #4 and #10 are not claimed fixed for their exact firmware revisions. A checksum identifies a binary; it does not provide the bytes needed to locate patch sites, motor descriptors or video callbacks. No guessed patch or motor memory address has been added for either revision. The unsupported-device branch supplies conservative metadata and disables PTZ; service initialization continues independently.

## Local RTSP setup

For older firmware using the AK39 factory RTSP path, put the following line in `HACK/etc/hack_custom.conf` on the second SD partition and reboot:

```sh
export local_rtsp_only="1"
```

For those older profiles, the wrapper selects the camera's unmodified binary and creates `/tmp/_ak39_factory.ini` before starting it. Local mode bypasses dynamic and static patched binary selection and does not wait for a default gateway, so a LAN without Internet routing can use it. Normal firmware supervision can restart the process if it exits.

For the C323, the reporter verified `rtsp://<camera-ip>:554/main_ch` over TCP and UDP and ONVIF on port 5000. Factory mode replaces the normal vendor runtime; it does not establish simultaneous Tuya cloud operation. The reporter also observed RTSP without authentication, so restrict access to the intended LAN. The newer binaries in #4/#10 remain unverified even with this option.

Removing the option and rebooting restores normal binary selection. The fork also invalidates a cached generated patch when the original firmware binary changes, so a patch from an older firmware revision is not silently reused.

The exact 3007325.5 firmware uses different RAM mode markers, stream ports and codecs. Follow its [camera-specific configuration](camera-3007325.5.md#stock-tuya-or-local-rtsp), including explicit Wi-Fi settings for a cold local RTSP boot. The older `554/main_ch` address above does not apply to that profile.

## Reproducing verification

Run the hermetic host regression suite from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Build the default ARM/uclibc configuration and both archives with:

```sh
cd SOURCE
make nproc=8 all release update
```

After building, install `qemu-user` on Debian/Ubuntu and run `python3 src/bin/verify-build.py` with Python 3.11 or later from `SOURCE` to repeat the packaged program and archive checks. The checker accepts `--qemu /path/to/qemu-arm` for a portable local emulator.

From the repository root, include the ARM926 runtime and backup checks in the full suite with:

```sh
CAMOFLASH_RUNTIME_SHELL="qemu-arm -cpu arm926 $PWD/SOURCE/build/mmcblk0p2/HACK/bin/busybox ash" \
BACKUP_ARM_CC="$PWD/SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi-gcc" \
BACKUP_ARM_BUSYBOX="$PWD/SOURCE/build/mmcblk0p2/HACK/bin/busybox" \
BACKUP_QEMU="qemu-arm" \
python3 -m unittest discover -s tests -v
```

The build requires the host dependencies listed in the README and real archive contents rather than Git LFS pointer files. The downloader hydrates pointer files atomically and checks their recorded SHA-256 before replacing them; a global Git LFS installation is optional. Creating the build directory no longer increments the source version. Version changes are explicit through the existing `update-version-*` targets. The fork's Build-Test workflow builds the default configuration and uploads archives and a log. Experimental libc configurations and all optional packages are separate from this default build gate. GitHub Pages publication and stable releases are manual operations.

Host regressions, cross compilation and archive inspection do not establish SD installation, physical PTZ motion, camera boot, RTSP frame delivery or ONVIF discovery on real hardware. The initial checks below completed locally on 2026-10-12 before the subsequent camera backup work. They describe that earlier fork snapshot, not the current artifacts. The later backup verification and runtime acceptance limits are recorded in the camera-specific guides.

## Initial fork validation

| Check | Result |
| --- | --- |
| Full default build: `make -C SOURCE JOBS=8 all` | Exit 0. ARM/uclibc, including FFmpeg, PHP CLI/CGI, ONVIF, MQTT and BusyBox. |
| Final packaging: `make -C SOURCE JOBS=8 all release update` | Exit 0. Both archives produced from the latest source; version remains `1.03.2412`. |
| Host regression suite | 57 tests passed, including two sparse-file partition tables checked by real `sfdisk`. |
| Runtime, DHCP and motor tests with packaged ARM BusyBox ash under QEMU | 26 tests passed. |
| Source and archive freshness | 145 source templates match the built files; every regular file in both archives matches the build tree. |
| Packaged ELF scan | 117 ELF files checked; all ELF32 ARM. |
| Packaged executables under QEMU | 23 checks passed using packaged libraries, including PHP JSON/SHA-256, an SQLite query, SQLCipher, FFmpeg, ONVIF help, MQTT tools and motor usage. |
| GitHub Actions definitions | All workflows pass actionlint 1.7.12. |

The first build attempt failed because the bundled toolchains put an older Bison ahead of the matching host tool; corrected host-tool selection allowed the full build to pass. A separate CMake 4.2 probe reproduced obsolete policy handling in cJSON; the CMake recipes now set the compatibility floor and cross-compilation target. Download, extraction and source-version regressions cover the additional build fixes. The unchanged default msmtp build reports no TLS/SSL library; no SMTP delivery or TLS notification acceptance is claimed by these probes. Initial failure logs, final build logs and runtime outputs are retained in the checkout's ignored `.local/logs/` directory.

| Local archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `LSCamoflash-1.03.2412-uclibc.tar.gz` | 44,463,095 | `f72a3a9288e967e562b7be1dc8bd835cc6d60d66b662bf57a6cd29a0b52d3610` |
| `update-1.03.2412-uclibc.tgz` | 44,038,068 | `0d44aaec20f4666ddef981bfe45ca365cde8aae4fd34ff318d725858e2d19ede` |

These historical development artifacts belong to the initial fork snapshot, with the existing upstream version number. Later builds replace them; use the current local verification report for current hashes. No stable release or GitHub Pages firmware publication was performed. Build-Test publishes reviewable workflow artifacts separately from a stable release.

The first fork push was published as commit `77736caa53b7ff4ab1df177e85aae6992d072059`. GitHub-hosted [Build-Test](https://github.com/dev-zetta/LSCamoflash/actions/runs/38203785627), [Shell regressions](https://github.com/dev-zetta/LSCamoflash/actions/runs/38203785711) and [CodeQL](https://github.com/dev-zetta/LSCamoflash/actions/runs/38203785666) jobs were rejected before any steps began because of an account execution restriction. Remote CI acceptance is therefore outstanding; the completed checks in this report were run locally.

## Exact-camera compatibility validation

The subsequent 3007325.5 work added the native SD entry, single-FAT runtime layout, exact stock-binary profile, bounded network initialization, ports 88/89 stream metadata and update handling. The backup kit and its host verifier are public source tools; captured proprietary firmware, credentials, recordings and raw camera logs remain private. The following final local checks completed on 2026-10-12 after the cold-boot updater and single-FAT status-page fixes.

| Check | Result |
| --- | --- |
| `make -C SOURCE nproc=8 all backup-kit release update` | Exit 0; default ARM/uClibc runtime, separate backup kit and both runtime archives. |
| Full host regression suite | Exit 0; 263 cases in 25.039 seconds, with 36 optional ARM cases skipped and 227 executed. |
| Full suite with ARM926 BusyBox and backup compiler/emulator settings | Exit 0; all 263 cases passed in 64.147 seconds, with no skips. |
| Source and archive freshness | Exit 0; 145 source templates match the build; 695 full-archive and 647 update-archive regular files match it. |
| Packaged ELF and execution checks | 119 ELF32 ARM files; 23 packaged program checks plus two static native-entry/BusyBox ARM926 checks passed. |
| Generated backup kit | Static ARMv5TEJ launcher and BusyBox verified; optional ARM926 BusyBox applet smoke check and card checksums passed. |
| Workflow and UI syntax | actionlint and JavaScript syntax checks passed. |

| Current local archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `LSCamoflash-1.03.2412-uclibc.tar.gz` | 46,186,376 | `9e36ac710178c1c8ce2d37b2c163e832b02a7fe2049a707c64990fade79f3715` |
| `update-1.03.2412-uclibc.tgz` | 45,764,626 | `44b154ea101837121cf8c881510848d186a47f4221bd7dcf42ad9e795a875753` |

These hashes identify the local development artifacts for this validation; the upstream version number remains unchanged and no stable release was published. The [camera guide](camera-3007325.5.md#binary-evidence-and-acceptance) records the remaining physical runtime gates. Successful backup verification, fixtures and QEMU execution do not establish camera boot, decoded RTSP frames, ONVIF discovery, custom PTZ control or flash restoration.

The first physical normal-mode runtime attempt subsequently failed to provide app access. The staged files matched the build and initialization reached backups and the overlay, but RAM logs did not survive power-off. Stock pairing and app access worked without the SD card. The exact profile now preserves the current stock software-settings file without applying the generic template. Bootstrap records persistent boot/init diagnostics with one previous boot, runs init through static BusyBox with a 600-second deadline and five-second forced-kill grace period, and attempts limited owned-wrapper/setup-lock cleanup on failure. Init checks supervisor liveness and bounds first service readiness to 45 nominal seconds, retaining at most 64 KiB of startup service output. These changes address observed software gaps; they do not establish the cause of the failed boot or successful runtime recovery. See the [camera diagnostics guide](camera-3007325.5.md#first-boot-and-diagnostics) for the timing limits, private log collection and distinction between stock-managed pairing and opt-in local RTSP.

## Startup hardening validation

The subsequent startup-hardening checkpoint passed the full host suite on 2026-10-12: 279 cases, 243 executed and 36 optional ARM cases skipped, in 29.238 seconds. With the ARM926 shell and backup environment enabled, all 279 cases passed in 69.858 seconds. New fixtures cover early service exit, hung first and later invocations, actual child and logger cleanup after a signal, newline-free diagnostic output capped at 65,536 bytes while excess output drains, stock software-settings byte identity, persistent log rotation, timeout status, conditional application-bind cleanup and pre-existing setup-lock preservation. Successful initialization now explicitly returns zero when optional hooks are absent; configured post-service hook failures still propagate.

The default build, backup-kit build and both archive targets exited zero. The artifact checker verified 145 source files, 119 ELF32 ARM files, 23 packaged program checks and two early-bootstrap ARM926 checks, and compared every regular archive file against the build. These replacement local development artifacts retain the upstream version number; no stable release or successful camera runtime is claimed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `LSCamoflash-1.03.2412-uclibc.tar.gz` | 46,191,999 | `629a53c28fc0659553e1e17b80e220e072fc0ebdedc83bca2687e0586358ac3d` |
| `update-1.03.2412-uclibc.tgz` | 45,765,327 | `072bfd2a2b652d80e5152e6755defd049d1d6ae047e2fe3cc5df9226410f5d79` |

## Stock handoff diagnostic checkpoint

The second physical normal-mode attempt also stayed offline, without observed repeated restarts. Before modifying the returned card, all 745 built payload files matched it exactly. Both retained boots reached service readiness and init status 0, completing the hook roughly one minute after power-on, while service output logs were empty. This establishes successful initialization, not stock application startup or Wi-Fi association. The GPIO export warning and FAT-overlay symlink errors do not independently establish the offline cause. Stock pairing still works after a cold boot without the card.

A separate fixture reproduced diagnostic loss: buffered `head` held a short message while a background child kept the FIFO writer open. Byte-counted `dd` now writes each short read immediately, preserving the existing 65,536-byte cap and excess-output drain. The opt-in stock `_ht_get_log.conf` marker additionally enables fixed wrapper launch phases and a detached sampler of filtered process, marker, mount, interface, route and WPA state at nominal 0/5/15/30/60-second offsets. The wrapper retains its direct same-PID exec. An `exec-stock` record means an exec attempt, not accepted application startup. Stock logging keeps `/mnt` mounted and produces private raw logs; its per-file rotation threshold does not cap total storage. The [camera guide](camera-3007325.5.md#first-boot-and-diagnostics) documents enabling, collecting and disabling these diagnostics. Their physical camera result remains open.

The final local checks on 2026-10-12 all exited zero: the full host suite ran 291 cases in 29.046 seconds (255 executed, 36 optional ARM cases skipped), and the ARM926 suite passed all 291 in 71.712 seconds without skips. New regressions cover an inherited FIFO writer, wrapper log rotation and same-PID exec, failed launch phases, diagnostic opt-in gating, five sampled states, log-path rejection and exclusion of private or malformed WPA fields. The default build, backup kit and both runtime archives completed successfully. The artifact checker verified 146 source files, 119 ELF32 ARM files, 23 packaged program checks, two early-bootstrap ARM926 checks, and all 696 full-archive and 648 update-archive regular files against the build.

These artifacts supersede the earlier local archive hashes above, retain the upstream version number and are development builds. No stable release or successful physical runtime is claimed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `LSCamoflash-1.03.2412-uclibc.tar.gz` | 46,194,446 | `570dc3bbfb810e48df4450b6b447a725026a30c882d13fde55889c2c0538c827` |
| `update-1.03.2412-uclibc.tgz` | 45,768,561 | `30dae50c575872c9501aabf31f883394d4c8e7c98a2f282003148182c9a1c7da` |

## Stock network command compatibility correction

The third physical test exercised the new diagnostics. The stock application remained at the same PID through the later handoff samples, and the user observed calibration and motion tracking. However, `wlan0` disappeared after init, a WPA process appeared only transiently, no DHCP client was observed, and stock logging reported an all-zero MAC value. This does not establish a change to the stored hardware MAC. All four staged diagnostic scripts matched their recorded hashes; the stock `ifconfig.txt` capture was empty.

A concrete overlay defect was identified: init explicitly removed `/sbin/ifconfig` and `/sbin/udhcpc` before binding its replacement directory over `/sbin`. The verified original userspace archive contains no alternate executable paths for those names, and stock networking invokes both through PATH. The recovered stock BusyBox ash under ARM926 returned status 127 for both bare help commands with the aliases absent, confirming that it does not provide a standalone applet fallback. The exact 3007325.5 profile now recreates both aliases against the copied stock BusyBox before the bind, and fails init if link creation fails. Other profiles retain their prior behavior. This corrects the proven missing paths; a further physical boot must establish whether WLAN, DHCP and app access recover.

Final local checks on 2026-10-12 all exited zero. The full host suite ran 295 cases in 29.149 seconds (259 executed, 36 optional ARM cases skipped), and the ARM926 suite passed all 295 in 71.711 seconds without skips. Four new fixtures cover actual PATH invocation through stock aliases in an isolated overlay, legacy alias removal, link failure and policy ordering before the system bind. The default build, backup kit and both archives succeeded. Artifact checks verified 146 source files, 119 ELF32 ARM files, 23 packaged program checks, two early-bootstrap ARM926 checks and every regular archive file against the build.

The following development artifacts replace the earlier hashes above, with the existing upstream version number. Physical network recovery and stable release publication remain unclaimed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `LSCamoflash-1.03.2412-uclibc.tar.gz` | 46,194,956 | `633d6d5e9bd04742dc321284c2248957073c015eb5fa6f839c80de720899ab38` |
| `update-1.03.2412-uclibc.tgz` | 45,768,985 | `b068a4d41b50ce9f298ab5057c3ddc041903028e0319f1d49bc9585c896c8785` |

## Normal-mode acceptance, memory reporting and local streaming setup

The fourth physical boot accepted the stock network-tool correction: `wlan0` remained present, WPA reached `COMPLETED`, the camera acquired `192.168.88.12` and a default route, and the user confirmed web UI login on port 8080. This establishes normal-mode network and web UI operation for this card. The user then selected a switch to local RTSP/ONVIF mode after being told that it replaces Tuya app mode. Its explicit Wi-Fi override was prepared privately from validated paired-network evidence; no credentials, camera logs, account database or proprietary firmware enter the repository or archives. A new cold boot and actual streaming tests remain necessary.

The old RAM bar calculated total minus `MemFree`, so cache contributed to its reported roughly 90% use. The UI now uses the kernel's `MemAvailable` estimate, distinguishes a genuine zero from a missing counter, labels the free-memory fallback, and exposes overlapping cache/buffer/shared-memory details. The status API retains its existing memory fields and adds counter-presence and breakdown fields. Opt-in handoff samples now retain selected numeric `/proc/meminfo` counters and process resident/virtual memory and thread counts, with the existing five sample times and 64-process limit. No actual RAM pressure or memory reduction is inferred from the old bar; the next camera boot must establish headroom.

The local-stream error now explains this exact firmware's mode switch, Wi-Fi requirement and Tuya tradeoff. ONVIF link generation returns the bundled server's advertised root HTTP service address, `http://<camera-ip>:5000/`, rather than a custom `onvif://` display URI. Main RTSP remains port 88 `/videoMain` with H.265; sub RTSP remains port 89 `/videoSub` with H.264, which the bundled ONVIF server advertises after its listener starts. A generated URL does not prove a listening service, decoded frames or discovery, and DHCP may change the address.

Final local checks on 2026-10-12 all exited zero: the host suite ran 309 cases in 30.614 seconds (273 executed, 36 optional ARM cases skipped), and the suite configured for ARM926 runtime and backup checks passed all 309 in 86.875 seconds without skips. New fixtures exercise the actual system-info UI callback with available, missing, zero and invalid memory counters, target BusyBox parsing and bounded/redacted memory observations, the explanatory mode error, and the ONVIF HTTP endpoint. The default build, backup kit and both runtime archives succeeded. Artifact checks verified 146 source files, 119 ELF32 ARM files, 23 packaged program checks, two early-bootstrap ARM926 checks and every regular archive file against the build. These checks do not establish local-mode physical acceptance.

The replacement development artifacts below keep the upstream version number. No stable release was published.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `LSCamoflash-1.03.2412-uclibc.tar.gz` | 46,195,690 | `285ef802d5b34f4e2c53931ca24fd23bef800d169f02a59e946852ca86b71047` |
| `update-1.03.2412-uclibc.tgz` | 45,769,587 | `74622c0d917768d5f7a6f54226ba3bb50159702f70a5e3556d8bcea7fdf9fc89` |

## Exact 3007325.5 video forwarding and live acceptance

On 2026-10-13, the exact local-mode stock executable opened ports 88 and 89 but did not answer fresh RTSP `OPTIONS` or `DESCRIBE` requests. Static inspection found that mode 2 leaves its encoder callbacks NULL, while the stock RTSP event loop runs when a video frame is forwarded. Calling normal Tuya capture initialization would also enter ring buffers that this mode never initializes. The new small preload instead forwards the two stock video buffers and their original 64-bit millisecond timestamps directly to the stock RTSP sender. The launcher checks the complete stock SHA-256, and the helper checks the ELF layout, critical instructions, exported addresses, explicit mode and owning process before touching firmware-specific state.

The helper waits at the existing idle-loop call until both RTSP demos and sessions are ready. Its process-lifetime mutex serializes forwarding and drains in-flight calls before either stock shutdown path frees RTSP objects; published callbacks remain installed but harmlessly disabled until process exit. An initial preload candidate failed on the camera with kernel OOM. A separate dependency-constructor fixture reproduced an early interposed mutex call returning `EINVAL` before the helper constructor. Real libc functions now resolve through `pthread_once` at first use, and the regression verifies actual exclusion between threads before helper initialization. The corrected helper remained running and installed both callbacks on the camera. Failed diagnostic attempts were preserved privately, and temporary debugger files were removed from the card.

The final launcher and helper were installed on the existing SD card and the camera completed a full reboot through the normal wrapper. Both streams then decoded 60 frames over TCP and 60 over UDP: H.265 main at 2304×1296 and H.264 sub at 640×360, both 15 frames per second. All four FFmpeg runs exited zero with completed progress. The protocol checks also returned RTSP 200 for both methods on both endpoints. ONVIF `GetSystemDateAndTime`, `GetCapabilities`, `GetProfiles` and `GetStreamUri` returned HTTP 200 without SOAP faults after reboot; the single H.264 640×360 profile selected port 89 `/videoSub`. Add the camera manually at `http://<camera-ip>:5000/`: the bundled server has no WS-Discovery loop and this build does not package its separate discovery daemon. Audio, a separate power-off/on cycle, custom PTZ, long-term operation and multiple-client behavior remain outside these acceptance results. Local mode continues to replace Tuya app operation.

A post-reboot snapshot recorded 32,648 KiB total RAM, 8,128 KiB available (about 25%), application RSS 6,460 KiB and 26 threads. The kernel OOM count since this final reboot was zero. The old preload failure and these short successful checks do not establish long-term memory behavior; private firmware, settings, credentials, images and raw logs remain excluded from Git and release archives.

Final software verification exited zero: the host suite discovered 319 cases in 32.506 seconds (280 passed, 39 optional ARM cases skipped), and the ARM926-configured suite passed all 319 in 89.755 seconds without skips. The default build, backup kit and both archives succeeded. The artifact checker verified 146 current source files, 120 ELF32 ARM files, 23 packaged runtime checks, two static bootstrap ARM926 checks, two unrelated-program preload loader checks, and byte/hash equality for all 697 full-archive and 649 update-archive regular members. Additional synthetic checks with the recovered stock uClibc 1.0.28 loader verified constructor ordering and pass-through behavior without executing the proprietary camera application on the host. A final README-only archive rebuild and artifact check also exited zero; the software test results apply to the same final code.

These development archives supersede the previous hashes, retain the upstream version number and include the launcher/helper pair. No stable release was published.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `LSCamoflash-1.03.2412-uclibc.tar.gz` | 46,201,451 | `a155498e725db14af5f33d28a37488310ba187d1a8625393e221811043e3ab63` |
| `update-1.03.2412-uclibc.tgz` | 45,771,263 | `91481e0e8d8b3be295506bc1747aec35776e62895661e331ebe1825e590f68be` |

## Local audio limitation

Following the user's report of silence on the H.265 stream, live RTSP/TCP packet checks on 2026-10-13 examined both endpoints for approximately eight seconds of media each. Both advertised an 8 kHz mono PCMA track, but delivered zero audio packets while delivering 123 main-stream and 117 substream video packets. The two probes exited zero without diagnostics; only packet metadata was saved, with no audio recording or camera configuration change. Common stock startup initializes audio machinery before entering mode 2, but that mode bypasses the Tuya capture startup that installs audio forwarding callbacks. The current helper installs video callbacks only, so local audio forwarding remains unimplemented and silence is expected in this mode. These results do not test microphone hardware. The runtime guide and documentation index now distinguish this known audio limitation from unverified hardware behavior; this documentation-only checkpoint does not change the installed SD files or development archive hashes above.
