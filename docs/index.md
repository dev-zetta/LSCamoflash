---
layout: default
---

# LSCamoflash documentation

Download [v2.01.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.01.0000) and verify the matching archive with `SHA256SUMS`. Supported legacy **Anyka** profiles use `LSCamoflash-2.01.0000-uclibc.tar.gz`; **Fullhan SZ B22705 / 7.6.23** uses `LSCamoflash-2.01.0000-fullhan.tar.gz`; experimental **YYOS 3225722 / SZ F26312 / V14.1.5** uses the separate `LSCamoflash-2.01.0000-yyos.tar.gz`. Fullhan and YYOS require private provisioning. The GitHub source ZIP is for development and is not ready to copy to a camera.

The [YYOS setup guide](yyos-setup.md) covers its credential-free release, private installer and separate SD entry. Its [management interface](yyos-management.md) provides status and completed recording downloads, with a [host recording converter](yyos-recordings.md), optional [indicator/timestamp controls and short PTZ steps](yyos-controls.md), and optional [key-only SSH](yyos-ssh.md). Short device checks accepted native H.264/PCMU streams, manual ONVIF and Tuya app connectivity; the owner confirmed working rotation. The public musl SSH replacement passed temporary-port checks, with normal boot still unverified. Repeated boots, detailed app/recording behavior, [VLC playback](yyos-vlc.md) and long-term stability remain open.

Read the [exact camera identity and verified NOR backup](camera-3225722.md) before using the pilot. Native streaming acceptance does not establish the safety of new configuration writes: the [native-media guide](yyos-native-media.md) separates the blocked legacy path, SSH-guarded setup with short device acceptance, earlier recovery and short enabled normal-boot evidence. Use only the separate YYOS package for this unit.

## Set up your camera

1. Check the [compatibility and integration notes](integration.md) and your exact firmware revision.
2. Follow the [firmware backup guide](firmware-backup.md) before runtime installation where supported.
3. For supported legacy Anyka profiles, use the [installation guide](installation.md) and [configuration guide](configuration.md).
4. For Fullhan, follow its [download and private setup](camera-sz-b22705.md#prepare-the-private-payload); do not use the Anyka installers.
5. For YYOS 3225722 / SZ F26312, follow the [release download and private setup](yyos-setup.md), then read its [camera evidence](camera-3225722.md) and [native-media safeguards](yyos-native-media.md). Anyka and Fullhan installers do not apply.

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
| [YYOS 3225722 / SZ F26312 camera](camera-3225722.md) | Exact identity/NOR backup, separate experimental package, failure/recovery history and bounded device acceptance. |
| [YYOS setup](yyos-setup.md) | Release package, private provisioning, optional controls/SSH and guarded SD installation. |
| [YYOS management](yyos-management.md) | Separate SD startup, status and authenticated recording downloads. |
| [YYOS controls](yyos-controls.md) | Optional private-key provisioning, indicator/timestamp switches, short manual PTZ steps and Stop safeguards. |
| [YYOS recordings](yyos-recordings.md) | Completed raw/metadata downloads, host conversion of the supported unencrypted format and verified packet/timestamp preservation. |
| [YYOS VLC playback](yyos-vlc.md) | Software-decoding controls and unresolved player behavior, separate from verified media decoding. |
| [YYOS native-media helper](yyos-native-media.md) | Blocked legacy configuration, guarded setup with short device acceptance, credential/status tools and bounded native authentication/decoding. |
| [Optional YYOS SSH](yyos-ssh.md) | Short accepted key-only root/PTY access and checked SD-file round trip. |
| [YYOS guarded recovery](yyos-recovery.md) | Verified two-byte configuration-off edit/private evidence, recovery/normal boots and trial safeguards. |
| [Building and testing](building.md) | Linux dependencies, cross-compilation, verification and regression tests. |
| [Integration and compatibility](integration.md) | Upstream PRs, issue disposition and historical validation. |
| [Release notes](release.md) | Published packages and release limitations. |

[Changelog](https://github.com/dev-zetta/LSCamoflash/blob/main/CHANGELOG.md) · [Report an issue](https://github.com/dev-zetta/LSCamoflash/issues) · [Source repository](https://github.com/dev-zetta/LSCamoflash) · [Contributing](https://github.com/dev-zetta/LSCamoflash/blob/main/CONTRIBUTING.md)
