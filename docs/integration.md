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
