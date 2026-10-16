---
layout: default
---

# LSCamoflash documentation

Start with [v2.00.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.00.0000) and `SHA256SUMS`. Supported legacy **Anyka** profiles use `LSCamoflash-2.00.0000-uclibc.tar.gz`; the tested **Fullhan SZ B22705 / 7.6.23** uses the separate `LSCamoflash-2.00.0000-fullhan.tar.gz`. Its public folder needs private credentials and manual startup. The GitHub source ZIP is for development and is not ready to copy to a camera.

**Known experimental YYOS block: 3225722 / SZ F26312 / V14.1.5 developed repeated reboots after a 24-byte-password native-media attempt. Public enablement remains blocked; do not bypass the gate.** The [recovery edit and native-off normal cold boot](yyos-recovery.md) passed short verification. A separate [guarded 15-byte trial](yyos-native-media.md#guarded-15-byte-trial-bounded-acceptance) later passed short TCP/UDP media decoding, RTSP Digest and ONVIF WSSE checks. Native-enabled normal cold boot, owner app checks and long-term stability remain pending; audible microphone sound was confirmed in a recorded sample. Neither release runtime above applies to this unit.

Its [verified identity and NOR backup](camera-3225722.md), short [authenticated management HTTP checks](yyos-management.md#short-live-http-acceptance), and [credential recovery/read-only LAN status](yyos-native-media.md) preceded the failing attempt. Recovery and the separate later trial have their own bounded evidence; the public configuration path stays disabled and no activation recipe is published.

## Set up your camera

1. Check the [compatibility and integration notes](integration.md) and your exact firmware revision.
2. Follow the [firmware backup guide](firmware-backup.md) before runtime installation where supported.
3. For supported legacy Anyka profiles, use the [installation guide](installation.md) and [configuration guide](configuration.md).
4. For Fullhan, follow its [download and private setup](camera-sz-b22705.md#prepare-the-private-payload); do not use the Anyka installers.
5. For 3225722 / SZ F26312, read the [known block and camera evidence](camera-3225722.md); short recovery and controlled trial checks passed, enabled normal startup remains pending, and public native activation stays blocked.

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
| [3225722 / SZ F26312 camera](camera-3225722.md) | Known reboot-loop block, earlier verified identity/NOR backup and recovery/runtime limits. |
| [YYOS management pilot](yyos-management.md) | Paused deployment, exact guarded implementation and historical pre-activation HTTP checks. |
| [YYOS native-media helper](yyos-native-media.md) | Production activation blocked; verified offline credential recovery and historical read-only status. |
| [Optional YYOS SSH](yyos-ssh.md) | Key-only LAN administration and SD-file access for the exact guarded experimental profile. |
| [YYOS guarded recovery](yyos-recovery.md) | Verified short recovery boot, two-byte flag edit and private evidence; one normal-bootstrap cold boot passed; long-term/native-media limits remain. |
| [Building and testing](building.md) | Linux dependencies, cross-compilation, verification and regression tests. |
| [Integration and compatibility](integration.md) | Upstream PRs, issue disposition and historical validation. |
| [Release notes](release.md) | Published packages and release limitations. |

[Changelog](https://github.com/dev-zetta/LSCamoflash/blob/main/CHANGELOG.md) · [Report an issue](https://github.com/dev-zetta/LSCamoflash/issues) · [Source repository](https://github.com/dev-zetta/LSCamoflash) · [Contributing](https://github.com/dev-zetta/LSCamoflash/blob/main/CONTRIBUTING.md)
