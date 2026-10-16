---
layout: default
---

# LSCamoflash documentation

Start with [v2.00.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.00.0000) and `SHA256SUMS`. Supported legacy **Anyka** profiles use `LSCamoflash-2.00.0000-uclibc.tar.gz`; the tested **Fullhan SZ B22705 / 7.6.23** uses the separate `LSCamoflash-2.00.0000-fullhan.tar.gz`. Its public folder needs private credentials and manual startup. The GitHub source ZIP is for development and is not ready to copy to a camera.

**Experimental YYOS 3225722 / SZ F26312 / V14.1.5 passed short native-enabled normal-cold-boot checks with authenticated management and optional key-only SSH. Public native configuration remains blocked pending separate write-path safeguards; do not bypass the gate.** The earlier 24-byte-password reboot loop, [verified recovery](yyos-recovery.md), [controlled 15-byte trial](yyos-native-media.md#guarded-15-byte-trial-bounded-acceptance) and [accepted enabled normal boot](yyos-native-media.md#native-enabled-normal-boot-short-acceptance) have separate evidence. Recorded microphone sound and owner-reported Tuya app connectivity passed; direct VLC live playback, detailed app/recording behavior, repeated boots and long-term stability remain unresolved. Neither release runtime above applies to this unit.

Its [verified identity and NOR backup](camera-3225722.md), [authenticated management](yyos-management.md), [credential recovery/read-only LAN status](yyos-native-media.md) and [key-only SSH/SD-file access](yyos-ssh.md#physical-normal-boot-acceptance) have bounded host/device evidence. Native runtime acceptance does not unblock public password/enable writes; no activation recipe is published.

## Set up your camera

1. Check the [compatibility and integration notes](integration.md) and your exact firmware revision.
2. Follow the [firmware backup guide](firmware-backup.md) before runtime installation where supported.
3. For supported legacy Anyka profiles, use the [installation guide](installation.md) and [configuration guide](configuration.md).
4. For Fullhan, follow its [download and private setup](camera-sz-b22705.md#prepare-the-private-payload); do not use the Anyka installers.
5. For 3225722 / SZ F26312, read the [camera evidence and configuration block](camera-3225722.md); short native-enabled normal startup, management and optional SSH passed, while public native configuration stays blocked.

The [LSC Smart PTZ 3007325.5 / SI L25502 guide](camera-3007325.5.md) covers firmware 6.2863.125.1348. Backup, Wi-Fi, web UI access, local H.265/H.264 video and PCMA microphone audio have been verified on that camera. ONVIF works through manual connection to its H.264 substream. Local mode replaces Tuya app operation; automatic discovery and toolkit PTZ are unavailable for this profile, and long-term stability remains unverified.

## Find a guide

| Guide | Contents |
| --- | --- |
| [Installation](installation.md) | Packages, checksum verification, SD layouts and first login. |
| [Configuration and everyday use](configuration.md) | Wi-Fi, passwords, services, streaming and updates. |
| [Troubleshooting](troubleshooting.md) | Offline camera, playback problems and useful logs. |
| [Firmware backup](firmware-backup.md) | Separate NOR backup kit and host verification. |
| [3007325.5 camera](camera-3007325.5.md) | Exact firmware identity, local mode, diagnostics and device evidence. |
| [Fullhan SZ B22705 camera](camera-sz-b22705.md) | Separate experimental management, recording downloads, authenticated ONVIF, manual startup and verified NOR backup. |
| [3225722 / SZ F26312 camera](camera-3225722.md) | Verified identity/NOR backup, failure/recovery history and short enabled normal-boot acceptance. |
| [YYOS management pilot](yyos-management.md) | Guarded read-only interface and authenticated HTTP acceptance alongside native streams/SSH. |
| [YYOS native-media helper](yyos-native-media.md) | Public configuration blocked; verified credential/status tools and bounded native authentication/decoding. |
| [Optional YYOS SSH](yyos-ssh.md) | Short accepted key-only root/PTY access and checked SD-file round trip. |
| [YYOS guarded recovery](yyos-recovery.md) | Verified two-byte configuration-off edit/private evidence, recovery/normal boots and trial safeguards. |
| [Building and testing](building.md) | Linux dependencies, cross-compilation, verification and regression tests. |
| [Integration and compatibility](integration.md) | Upstream PRs, issue disposition and historical validation. |
| [Release notes](release.md) | Published packages and release limitations. |

[Changelog](https://github.com/dev-zetta/LSCamoflash/blob/main/CHANGELOG.md) · [Report an issue](https://github.com/dev-zetta/LSCamoflash/issues) · [Source repository](https://github.com/dev-zetta/LSCamoflash) · [Contributing](https://github.com/dev-zetta/LSCamoflash/blob/main/CONTRIBUTING.md)
