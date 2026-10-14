# Troubleshooting

Fullhan SZ B22705 / 7.6.23 uses a separate package and private accounts with no default password. Follow its [manual HTTP/ONVIF startup and diagnostics](camera-sz-b22705.md#start-and-use-it); the Anyka defaults and local-mode instructions below do not apply to it.

Start with your camera's exact firmware identity and the [installation guide](installation.md). For LSC Smart PTZ 3007325.5 / SI L25502, the [camera guide](camera-3007325.5.md) contains detailed boot diagnostics and device evidence.

## The camera is offline or has no DHCP lease

Allow several minutes for the first initialization. In local RTSP mode, the Tuya app being offline is expected; look for the camera's current LAN address and try its web UI instead.

If there is no LAN connection, check that local mode has the explicit Wi-Fi settings required by the profile. On the tested 3007325.5 firmware, Tuya pairing alone does not supply a cold local-mode boot with its plaintext Wi-Fi configuration. Use the [complete Wi-Fi example](camera-3007325.5.md#stock-tuya-or-local-rtsp).

If startup still fails, power off, retrieve the card and save its logs before another boot rotates them. Verify that you copied the built/released payload and used the correct card layout. Test normal startup without the runtime card separately; an init exit status of zero alone does not prove successful networking.

## The web UI asks for a password

A fresh web UI uses `admin` / `admin`. An existing card can retain a changed account. The root shell/FTP account is separate; changing one does not change the other. See [passwords and services](configuration.md#passwords-and-services).

## A stream link is generated but does not play

The web UI's link button does not enable local mode. Check that the profile supports the selected mode and that the camera has booted with its required Wi-Fi settings.

For the tested 3007325.5 profile, use port 88 `/videoMain` for H.265 or port 89 `/videoSub` for H.264. Older `554/main_ch` instructions do not apply. If a player cannot decode H.265, test the H.264 substream. Keep the launcher and `libcamoflash_rtsp.so` from the same release together; this firmware needs the helper to forward video and audio.

Both streams provide mono G.711 A-law audio at 8 kHz. Confirm the player has selected the audio track and is not muted. Earlier development helpers forwarded video only; install a complete release containing audio support before diagnosing microphone hardware.

## ONVIF does not find the camera automatically

Automatic WS-Discovery is not bundled. For the tested 3007325.5 profile, add `http://<camera-ip>:5000/` manually. Its ONVIF profile advertises the H.264 substream. Toolkit PTZ is disabled for this exact firmware, even though the camera has motors and performs stock calibration.

## The card cannot be unmounted

Close file-manager windows, terminals and programs using files on the card, then safely eject it through the operating system. Do not remove it while a copy or update is in progress. The Linux installer deliberately stops after a failed unmount.

## Which logs should I keep?

Paths below are relative to the runtime root: the single-FAT card root, or partition 2 in the traditional layout.

| File | What it records |
| --- | --- |
| `HACK/var/log/boot.log` | Bootstrap progress and init exit status. |
| `HACK/var/log/init.log`, `init.err` | Init output and errors. |
| `HACK/var/log/services-startup.log` | Initial service output, capped at 64 KiB. |
| `HACK/var/log/update.log` | A staged or failed update. |

Keep the `*.previous.*` / `*.previous.log` files too. The camera clock can be wrong, so timestamps alone do not identify the newest attempt. For opt-in handoff/Wi-Fi diagnostics and stock logs, follow [First boot and diagnostics](camera-3007325.5.md#first-boot-and-diagnostics).

Firmware dumps, configuration and raw logs can contain Wi-Fi credentials and device/account identifiers. Keep complete copies privately and redact before posting. Open a [fork issue](https://github.com/dev-zetta/LSCamoflash/issues) with the model, exact stock firmware, LSCamoflash version, layout, startup behavior and relevant redacted errors. See the [support guide](../SUPPORT.md).
