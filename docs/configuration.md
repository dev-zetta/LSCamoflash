# Configuration and everyday use

Complete the [installation guide](installation.md) first. Features and stream endpoints depend on the exact firmware; use your model's guide rather than settings copied from another camera.

## Open the web interface

Find the camera's current LAN address in your router and open `http://<camera-ip>:8080/`. The web UI provides system status, camera settings, stream-link generation and restart controls. Some controls depend on the selected firmware profile. A generated link does not prove that the corresponding service is running.

## Passwords and services

The fresh web UI account is `admin` with password `admin`. Change it through the web UI's **Password** page. This account is stored in the web UI database and is separate from the shell/FTP account.

The packaged shell and FTP defaults are `root` / `LSCamoflash`. On the camera, use the interactive `chpasswd` helper to change that account and persist its SD configuration; plain BusyBox `passwd` does not perform the same persistence step. Check access after reboot, especially on a newly configured card layout. Changing the web UI password does not change the root password or add RTSP authentication.

| Service | Default port | Setting |
| --- | ---: | --- |
| Web UI (HTTP) | 8080 | `service_http_enabled`, `port_http` |
| Telnet shell | 24 | `service_telnet_enabled`, `port_telnet` |
| FTP | 21 | `service_ftp_enabled`, `port_ftp` |
| ONVIF | 5000 | `service_onvif_enabled`, `port_onvif` |
| MQTT | 8883 | `service_mqtt_enabled`, `port_mqtt`; disabled by default |
| Cron | — | `service_crond_enabled`; disabled by default |

HTTP, Telnet and FTP use unencrypted connections. The tested local RTSP endpoints require no credentials. Keep these services on a trusted LAN and disable services you do not use.

## Change settings on the card

Put your overrides in `HACK/etc/hack_custom.conf` on the runtime card root. On a two-partition card, that means partition 2. This file is loaded after `HACK/etc/hack.conf`, which contains the defaults; keep custom settings out of the defaults file so updates can preserve them.

For example, to disable Telnet and FTP while keeping the web UI:

```sh
export service_telnet_enabled="0"
export service_ftp_enabled="0"
export service_http_enabled="1"
```

Use plain text with Unix line endings. The file is shell code, so preserve valid quoting and keep it private when it contains credentials. Power the camera off before removing the card, save your edits, safely eject it and cold-boot to apply startup settings.

## Wi-Fi and local streaming

Stock-managed mode on the verified 3007325.5 camera uses its existing Tuya pairing. Leave `local_rtsp_only` and `wifi_config_override` unset for that mode. Local RTSP mode bypasses Tuya networking startup and needs an explicit Wi-Fi override for a cold boot; see the complete [Wi-Fi example](camera-3007325.5.md#stock-tuya-or-local-rtsp).

For that exact profile, local mode replaces Tuya app operation. Its verified endpoints are:

| Connection | Address | Media |
| --- | --- | --- |
| Main RTSP | `rtsp://<camera-ip>:88/videoMain` | H.265, 2304×1296, 15 fps; mono PCMA audio at 8 kHz |
| Sub RTSP | `rtsp://<camera-ip>:89/videoSub` | H.264, 640×360, 15 fps; mono PCMA audio at 8 kHz |
| Manual ONVIF | `http://<camera-ip>:5000/` | Device/Media service advertising the H.264 substream |

Automatic ONVIF discovery is not bundled. Add the IP and port 5000 manually in your client. Toolkit PTZ remains disabled for this exact profile. Other firmware can use different paths and ports; older factory-mode profiles are described in the [integration notes](integration.md#local-rtsp-setup).

Cloud-assisted HLS/FLV link features are separate from local RTSP and depend on vendor services and configuration. They are not part of the verified local camera path.

## Read memory usage

The system-status page uses the kernel's `MemAvailable` estimate where available. Filesystem cache is not treated as entirely unavailable memory. The displayed cache, buffer and shared-memory details overlap, so do not add them together as separate allocations. See the [camera memory notes](camera-3007325.5.md#memory-reporting) for measurements and the remaining long-term stability checks.

## Updates

Download the update asset and `SHA256SUMS` from the [fork's releases](https://github.com/dev-zetta/LSCamoflash/releases/latest), verify the checksum and keep a private copy of the working card first. The update package excludes `HACK/etc/` and the root crontab; it is for an existing installation.

To stage a release update offline, power the camera off, mount the runtime card on the computer, and extract the update archive's `mmcblk0p1/` and `mmcblk0p2/` directories into a new `UPDATE/` directory beside `HACK/`. In the traditional layout, `UPDATE/` belongs on partition 2. Do not put the compressed archive there without extracting it. Review the archive listing before extraction and retain any existing failed update rather than merging over it.

On the next boot, the runtime updater copies the boot files to the boot card and the runtime files to its runtime root. Successful installation removes the staged update and rebuilds the overlay. A failed copy, mount or sync keeps the staged files and stops startup; preserve `HACK/var/log/update.log` when diagnosing it. Replace the supplied launcher and its helper together through the complete package.

Manual staging does **not** update `HACK/etc/version.txt`, because the update archive excludes configuration. After confirming successful installation (`UPDATE/` is gone and `HACK/var/log/update-last.log` records completion), power off, remount the card and set that single file to the exact installed release version, such as `1.03.2413`, followed by a newline. Safely eject and cold-boot again. Leave the metadata unchanged while an update is failed or pending, and do not replace the entire `HACK/etc/` directory. This describes the updater's current source behavior; a physical offline-update test remains separate.

The legacy automatic updater expects a configured server with `version.txt` and a matching `update-<version>.tgz`; its `%device_uid%` placeholder can select a per-device path. GitHub Releases is not configured as that server, and there is no published fork autobuild feed. Use verified release assets for manual updates. See [Building and testing](building.md) for creating packages and [release notes](release.md) for their contents.

## SD card layout and recovery

The traditional two-partition layout keeps `HACK/` on partition 2. The service loop can restore boot files after formatting partition 1, but formatting through the app and recovery are not verified for every profile. Do not treat this as a backup or format a working card casually. The verified single-FAT layout shares boot files, runtime and recordings; formatting it removes the runtime too.

Keep firmware backups, working-card copies and important recordings on the host. To stop the hook, power off and archive the root `_ht_ap_mode.conf` marker or remove the runtime card. Removing the card does not undo stock startup's persistent configuration changes. Check app access, Wi-Fi and recordings separately after returning to stock startup.

## Included tools

The default package supplies BusyBox, curl, OpenSSL, FFmpeg, ONVIF, Mosquitto clients/broker, joe, msmtp/msmtpd, SQLite/SQLCipher, strace, tcpdump and UPnP tools. Having a tool installed does not enable its service or establish support for a camera feature. The `motor` CLI is usable only where that profile's motor control is supported; it stays disabled for the tested 3007325.5 profile. Python and radare2 are optional build components.

For build options, runtime verification and source details, read [Building and testing](building.md). Bundled projects retain their [individual licenses](../SOURCE/3RD_PARTY_LICENSES.md).
