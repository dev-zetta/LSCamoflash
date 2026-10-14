---
layout: default
---

# LSCamoflash documentation

Start with a published package from the [fork's latest release](https://github.com/dev-zetta/LSCamoflash/releases/latest). For a new installation, choose the full `LSCamoflash-<version>-uclibc.tar.gz` runtime archive and `SHA256SUMS`. The GitHub source ZIP is for development and is not ready to copy to a camera.

## Set up your camera

1. Check the [compatibility and integration notes](integration.md) and your exact firmware revision.
2. Follow the [firmware backup guide](firmware-backup.md) before runtime installation where supported.
3. Use the [installation guide](installation.md) to choose a card layout and complete the first boot.
4. Read [configuration and everyday use](configuration.md) for passwords, services and streaming.

The [LSC Smart PTZ 3007325.5 / SI L25502 guide](camera-3007325.5.md) covers firmware 6.2863.125.1348. Backup, Wi-Fi, web UI access, local H.265/H.264 video and PCMA microphone audio have been verified on that camera. ONVIF works through manual connection to its H.264 substream. Local mode replaces Tuya app operation; automatic discovery and toolkit PTZ are unavailable for this profile, and long-term stability remains unverified.

## Find a guide

| Guide | Contents |
| --- | --- |
| [Installation](installation.md) | Packages, checksum verification, SD layouts and first login. |
| [Configuration and everyday use](configuration.md) | Wi-Fi, passwords, services, streaming and updates. |
| [Troubleshooting](troubleshooting.md) | Offline camera, playback problems and useful logs. |
| [Firmware backup](firmware-backup.md) | Separate NOR backup kit and host verification. |
| [3007325.5 camera](camera-3007325.5.md) | Exact firmware identity, local mode, diagnostics and device evidence. |
| [Fullhan SZ B22705 camera](camera-sz-b22705.md) | Stock RTSP, diagnostic access, exact hardware and verified manual NOR backup; separate runtime required. |
| [Building and testing](building.md) | Linux dependencies, cross-compilation, verification and regression tests. |
| [Integration and compatibility](integration.md) | Upstream PRs, issue disposition and historical validation. |
| [Release notes](release.md) | Published packages and release limitations. |

[Changelog](https://github.com/dev-zetta/LSCamoflash/blob/main/CHANGELOG.md) · [Report an issue](https://github.com/dev-zetta/LSCamoflash/issues) · [Source repository](https://github.com/dev-zetta/LSCamoflash) · [Contributing](https://github.com/dev-zetta/LSCamoflash/blob/main/CONTRIBUTING.md)
