# LSCamoflash

Give compatible LSC / Tuya Anyka cameras a local web interface, RTSP streaming and more control over their settings. LSCamoflash runs an extension from a microSD card; available features depend on the camera's exact stock firmware.

[![Release](https://img.shields.io/github/v/release/dev-zetta/LSCamoflash)](https://github.com/dev-zetta/LSCamoflash/releases/latest)
[![Build-Test](https://github.com/dev-zetta/LSCamoflash/actions/workflows/makefile.yml/badge.svg)](https://github.com/dev-zetta/LSCamoflash/actions/workflows/makefile.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**[Download the latest release](https://github.com/dev-zetta/LSCamoflash/releases/latest)** · **[Setup guide](docs/installation.md)** · **[Documentation](docs/index.md)** · [Deutsch](README_DE.md)

## What you can do

- Watch supported cameras through local RTSP and connect an ONVIF client.
- Use a browser to view system status, change settings and restart the camera.
- Configure Wi-Fi and optional services through files on the SD card.
- Back up stock firmware with the separate, documented NOR backup kit.

Streaming, audio and motor control vary by firmware. Check compatibility before preparing a card.

## Is my camera supported?

The **LSC Smart PTZ Camera, SI L25502 / article 3007325.5**, has been tested with stock firmware **6.2863.125.1348**, displayed in the app as V1.0.0 (6.2863.125). Verified functions include firmware backup, Wi-Fi, web UI login, H.265 main video, H.264 sub video and microphone audio. Manual ONVIF connection selects the H.264 substream.

For this camera, local streaming mode replaces Tuya app operation and needs explicit Wi-Fi settings. Automatic ONVIF discovery is not bundled, toolkit PTZ control is disabled, and long-term stability remains unverified. Follow the [camera guide](docs/camera-3007325.5.md) for the exact firmware identity and setup.

Other Anyka camera profiles are inherited from upstream, including IPC-XC-C323 support. Their evidence and remaining checks are listed in the [compatibility and integration notes](docs/integration.md). A matching product name alone does not establish compatibility.

The [Fullhan SZ B22705 / firmware 7.6.23 guide](docs/camera-sz-b22705.md) covers verified stock RTSP, firmware backup and a separate experimental status dashboard built from current source. The dashboard starts manually and keeps the stock camera application running. This platform requires its own package; the Anyka package above must not be installed on it.

## Get started

1. **Check your camera and firmware.** Read the [compatibility notes](docs/integration.md) and any guide for your model.
2. **Make a backup.** Save existing SD recordings and follow the [stock firmware backup guide](docs/firmware-backup.md) where supported. Keep firmware dumps and credentials private.
3. **Download the full runtime package** from the [fork's releases](https://github.com/dev-zetta/LSCamoflash/releases/latest). Choose `LSCamoflash-<version>-uclibc.tar.gz` and `SHA256SUMS` for a new installation.
4. **Prepare the SD card and boot the camera** using the [installation guide](docs/installation.md). It covers both card layouts and first startup.
5. **Open `http://<camera-ip>:8080/`.** A fresh web UI uses `admin` / `admin`; change it through the **Password** page. See [configuration and everyday use](docs/configuration.md).

The release also contains an update package for existing installations and a separate backup kit. The installation guide explains which one to use. You can install a published package without compiling the project.

Use a spare card and back up before changing it: the partitioning scripts erase the selected disk. Stock startup can change persistent camera configuration, so removing the SD card does not guarantee a complete rollback. Use the software only on devices you own or may modify; see the [usage policy](USAGE_POLICY.md).

## Guides

| I want to… | Read this |
| --- | --- |
| Install a release | [Installation](docs/installation.md) |
| Set passwords, services or streaming | [Configuration and everyday use](docs/configuration.md) |
| Back up the original firmware | [Firmware backup](docs/firmware-backup.md) |
| Set up the tested 3007325.5 camera | [Camera guide](docs/camera-3007325.5.md) |
| Troubleshoot startup or playback | [Troubleshooting](docs/troubleshooting.md) |
| Build or test the project | [Building and testing](docs/building.md) |
| See what changed | [Changelog](CHANGELOG.md) and [release notes](docs/release.md) |

## Get help or contribute

Report bugs and compatibility results in this fork's [issue tracker](https://github.com/dev-zetta/LSCamoflash/issues). Include the camera model, exact firmware, LSCamoflash version and steps to reproduce; redact credentials and device identifiers from logs. Read the [support guide](SUPPORT.md) or [contributing guide](CONTRIBUTING.md) for more details. Report vulnerabilities through the [security policy](SECURITY.md).

## Credits and licenses

This fork builds on [Bunkerschild/LSCamoflash](https://github.com/Bunkerschild/LSCamoflash), preserves contributor attribution and integrates upstream PRs #5, #6, #8 and #9. See the [integration notes](docs/integration.md) for their original references.

Original project code uses the [MIT License](LICENSE). Bundled third-party components retain their own licenses; see the [third-party notices](SOURCE/3RD_PARTY_LICENSES.md).
