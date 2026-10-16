---
layout: default
---

# LSCamoflash documentation

Start with [v2.00.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.00.0000) and `SHA256SUMS`. Supported legacy **Anyka** profiles use `LSCamoflash-2.00.0000-uclibc.tar.gz`; the tested **Fullhan SZ B22705 / 7.6.23** uses the separate `LSCamoflash-2.00.0000-fullhan.tar.gz`. Its public folder needs private credentials and manual startup. **v2.00.0000 does not contain YYOS.** The separate YYOS source-built pilot is described below; its release is pending. The GitHub source ZIP is for development and is not ready to copy to a camera.

**YYOS LSC 3225722 / SZ F26312 / firmware 14.1.5 uses its own source-built pilot.** Its [authenticated management interface](yyos-management.md) provides status and completed recording downloads, with a separate [host recording converter](yyos-recordings.md). Short device checks accepted native H.264/PCMU streams, manual ONVIF, optional key-only SSH and owner-reported Tuya app connectivity. Optional [indicator/timestamp controls and short PTZ steps](yyos-controls.md) are installed and passed bounded checks; repeated boots, detailed app/recording behavior and long-term stability remain separate checks. The [VLC playback investigation](yyos-vlc.md) remains unresolved.

Read the [exact camera identity and verified NOR backup](camera-3225722.md) before using the pilot. Native streaming acceptance does not establish the safety of new configuration writes: the [native-media guide](yyos-native-media.md) separates the blocked legacy path, SSH-guarded setup with short device acceptance, earlier recovery and short enabled normal-boot evidence. Neither published Anyka nor Fullhan runtime applies to this unit.

## Set up your camera

1. Check the [compatibility and integration notes](integration.md) and your exact firmware revision.
2. Follow the [firmware backup guide](firmware-backup.md) before runtime installation where supported.
3. For supported legacy Anyka profiles, use the [installation guide](installation.md) and [configuration guide](configuration.md).
4. For Fullhan, follow its [download and private setup](camera-sz-b22705.md#prepare-the-private-payload); do not use the Anyka installers.
5. For YYOS 3225722 / SZ F26312, follow the [separate source build and private setup](yyos-management.md#build-a-private-kit), then read its [camera evidence](camera-3225722.md) and [native-media safeguards](yyos-native-media.md). Its release is pending; do not use the other platforms’ installers.

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
| [YYOS 3225722 / SZ F26312 camera](camera-3225722.md) | Exact identity/NOR backup, separate source-built pilot, failure/recovery history and short normal-boot acceptance. |
| [YYOS management pilot](yyos-management.md) | Source build, private credentials, separate SD startup, status and authenticated recording downloads. |
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
