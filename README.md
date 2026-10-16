# LSCamoflash

Local camera tools for compatible LSC / Tuya cameras: a web interface, RTSP integration and firmware backup utilities running from a microSD card. **Anyka, Fullhan and YYOS cameras use separate packages**, with features determined by the exact stock firmware.

[![Release](https://img.shields.io/github/v/release/dev-zetta/LSCamoflash)](https://github.com/dev-zetta/LSCamoflash/releases/latest)
[![Build-Test](https://github.com/dev-zetta/LSCamoflash/actions/workflows/makefile.yml/badge.svg)](https://github.com/dev-zetta/LSCamoflash/actions/workflows/makefile.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**[Download v2.01.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.01.0000)** · **[Setup guide](docs/installation.md)** · **[Documentation](docs/index.md)** · [Deutsch](README_DE.md)

## What you can do

- Watch supported cameras through local RTSP and connect an ONVIF client.
- View camera status, CPU, memory and SD information in a browser.
- Browse and download finalized recordings with the experimental Fullhan and YYOS interfaces.
- Use optional indicator/timestamp switches and short PTZ steps on the experimental YYOS profile.
- Change settings and configure Wi-Fi/services on supported Anyka profiles.
- Back up stock firmware with the separate, documented NOR tools.

Streaming, audio, motor control and startup differ between platforms. Check the guide for your exact camera before preparing a card.

## Choose the package for your camera

| Tested camera | Package or availability | Setup |
| --- | --- | --- |
| **Anyka LSC Smart PTZ**, SI L25502 / article 3007325.5, firmware `6.2863.125.1348` | `LSCamoflash-2.01.0000-uclibc.tar.gz` | [3007325.5 guide](docs/camera-3007325.5.md) |
| **Fullhan LSC Indoor 1080p**, SZ B22705 / FH8626V100, firmware `7.6.23` | `LSCamoflash-2.01.0000-fullhan.tar.gz` | [Fullhan guide](docs/camera-sz-b22705.md) |
| **YYOS LSC 3225722**, SZ F26312, firmware `14.1.5` | `LSCamoflash-2.01.0000-yyos.tar.gz` | [YYOS setup](docs/yyos-setup.md) |
| **Firmware backup only** | `LSCamoflash-2.01.0000-backup-kit.tar.gz` | [Anyka SD backup](docs/firmware-backup.md) or [Fullhan manual collector](docs/camera-sz-b22705.md#manual-backup-through-the-stock-shell) |

Download `SHA256SUMS` too and verify your chosen archive. v2.01.0000 adds the separate experimental YYOS package alongside Anyka and Fullhan. The Anyka update package is for an existing Anyka runtime; it does not install or update Fullhan or YYOS. The backup kit’s SD boot launcher applies to supported Anyka cameras, while Fullhan uses its separate manual entry.

**Anyka 3007325.5:** verified functions include Wi-Fi, web UI login, H.265 main video, H.264 sub video and PCMA microphone audio. Manual ONVIF selects the H.264 substream. Local streaming replaces Tuya app operation and requires explicit Wi-Fi settings; automatic ONVIF discovery and toolkit PTZ are unavailable on this profile.

**Fullhan SZ B22705:** the experimental interface provides Dashboard, Recordings, Streams and Diagnostics tabs while keeping the stock application running. Short live checks verified authenticated recording HEAD/Range downloads, native H.264 profiles and independent ONVIF clients. It requires private credentials and a manual start after reboot. Add ONVIF at port 5000 manually; stock discovery stays untouched. Camera settings, PTZ, audio forwarding and automatic startup are not implemented.

Other Anyka profiles are inherited from upstream, including IPC-XC-C323 support. See the [compatibility and integration notes](docs/integration.md). A matching product name alone does not establish compatibility, and short live checks do not establish long-term stability.

**YYOS 3225722 / SZ F26312 / V14.1.5:** the separate experimental [management package](docs/yyos-management.md) provides authenticated status and recording downloads, a [host recording converter](docs/yyos-recordings.md), optional [key-only SSH](docs/yyos-ssh.md) and privately enabled [indicator/timestamp controls and short PTZ steps](docs/yyos-controls.md). Short checks accepted native H.264/PCMU streaming, manual ONVIF and Tuya app connectivity; the owner confirmed working camera rotation. The public musl SSH replacement passed temporary-port checks, with normal boot still unverified. Repeated boots, detailed app behavior, [VLC playback](docs/yyos-vlc.md) and long-term operation remain open. Follow the [native-media safeguards](docs/yyos-native-media.md) when configuring streams.

## Get started

1. **Check your camera and firmware.** Choose its platform-specific guide above.
2. **Make a backup.** Save existing SD recordings and follow the applicable firmware backup procedure. Keep dumps and credentials private.
3. **Download and verify the matching package.** Choose your platform’s archive from [v2.01.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.01.0000) and verify `SHA256SUMS`. Fullhan and YYOS require private provisioning before installation.
4. **Prepare the card using your camera guide.** The [Anyka installation guide](docs/installation.md) covers its layouts and installers. The [Fullhan setup](docs/camera-sz-b22705.md#prepare-the-private-payload) uses its own named folder, private credentials and manual startup. The [YYOS setup guide](docs/yyos-setup.md) covers its private installer, separate SD entry and optional controls/SSH.
5. **Open `http://<camera-ip>:8080/`.** A fresh **Anyka** web UI uses `admin` / `admin`; change it through **Password**. **Fullhan and YYOS have no default web password** and use the account you provisioned. Media and SSH credentials are separate from the web account.

Published packages need no compilation. Fullhan still requires private credentials and manual service startup. The YYOS archive contains no web password, control key, SSH keys or SSH enable marker; provision the features you need on your computer before staging its private card files.

Use a spare card and back up before changing it: the Anyka partitioning scripts erase the selected disk. Stock startup can change persistent camera configuration, so removing an SD card does not guarantee complete rollback. Use the software only on devices you own or may modify; see the [usage policy](USAGE_POLICY.md).

## Guides

| I want to… | Read this |
| --- | --- |
| Choose a release or install Anyka | [Release notes](docs/release.md) and [installation](docs/installation.md) |
| Set Anyka passwords, services or streaming | [Configuration and everyday use](docs/configuration.md) |
| Set up Fullhan management and recordings | [Fullhan SZ B22705 guide](docs/camera-sz-b22705.md) |
| Set up YYOS, controls and recordings | [YYOS setup](docs/yyos-setup.md), [controls](docs/yyos-controls.md), [recording conversion](docs/yyos-recordings.md) and [VLC checks](docs/yyos-vlc.md) |
| Back up the original firmware | [Firmware backup](docs/firmware-backup.md) |
| Troubleshoot startup or playback | [Troubleshooting](docs/troubleshooting.md) |
| Build, test or publish the project | [Building and testing](docs/building.md) |
| See what changed | [Changelog](CHANGELOG.md) |

## Get help or contribute

Report bugs and compatibility results in this fork’s [issue tracker](https://github.com/dev-zetta/LSCamoflash/issues). Include the camera model, exact firmware, LSCamoflash version and steps to reproduce; redact credentials and device identifiers from logs. Read the [support guide](SUPPORT.md) or [contributing guide](CONTRIBUTING.md). Report vulnerabilities through the [security policy](SECURITY.md).

## Credits and licenses

This fork builds on [Bunkerschild/LSCamoflash](https://github.com/Bunkerschild/LSCamoflash), preserves contributor attribution and integrates upstream PRs #5, #6, #8 and #9. See the [integration notes](docs/integration.md) for their original references.

Original project code uses the [MIT License](LICENSE). Bundled third-party components retain their own licenses; see the [third-party notices](SOURCE/3RD_PARTY_LICENSES.md).
