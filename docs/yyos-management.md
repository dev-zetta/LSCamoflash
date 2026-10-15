# Experimental YYOS management dashboard

This isolated pilot adds an authenticated, read-only dashboard for **LSC 3225722 / SZ F26312**, app-reported firmware **V14.1.5**, with the exact AK3918AV130 and `yy_cam` identity recorded in the [camera investigation](camera-3225722.md). It is implemented and passes offline software checks; **physical dashboard startup, resource use, repeated boots and native media acceptance remain pending**. The verified firmware backup is separate evidence. Do not use the existing Anyka runtime or Fullhan installers for this camera.

## What the pilot provides

| Page | Capabilities |
| --- | --- |
| Dashboard | RAM used/available, SD capacity, CPU load averages, uptime and observed service state. |
| Streams | Candidate stock RTSP main/sub and ONVIF addresses, explicitly labelled unverified. |
| Diagnostics | Backend identity, memory counters and observed dashboard/stock-application resident memory. |

The HTTP service uses port **8080** and refreshes visible status every 15 seconds. CPU load is not a CPU utilization percentage. The stock `yy_cam` process retains control of camera settings, networking and media. The pilot does not change those settings, restart the stock application, program flash or install an overlay. It has no PTZ, recording browser, shell endpoint, reboot, firmware-update or camera-setting controls, and starts no extra RTSP, ONVIF or discovery daemon.

The [source README](../SOURCE/src/yyos/README.md), [builder](../tools/yyos/build-kit.py) and [bounded boot wrapper](../tools/yyos/boot.sh) describe the isolated payload. Startup checks root access, the CPU hardware field `AK3918AV130`, the exact `/appfs/bin/yy_cam` SHA-256 from the camera guide, and one visible writable VFAT mount from `/dev/mmcblk0p1` at `/mnt/sdcard`. The folder must be named **`LSCamoflash-yyos`** at that mount. Public payload checksums, allowed files, authentication, available HTTP port and owned-process state are also checked. Another application binary or card layout requires investigation; do not bypass these guards.

## Build a private kit

Use a current source checkout and the Linux tools in [Building and testing](building.md), including Python, host OpenSSL, the ARM uClibc toolchain and QEMU ARM. Create a private host file containing one nonempty password line without control characters; keep it outside public source and release assets. The username defaults to **`admin`**, with an optional `--username` override. **There is no default password.**

From the repository root, prepare the toolchain/static BusyBox if needed, then build into a dedicated absent or empty private host directory:

```sh
make -C SOURCE backup-kit
KIT_DIR="/absolute/private/path/yyos-management-kit"
python3 tools/yyos/build-kit.py \
  --busybox "$PWD/SOURCE/backup-kit/card/busybox" \
  --qemu /usr/bin/qemu-arm \
  --password-file /absolute/private/path/dashboard-password.txt \
  --output "$KIT_DIR"
(cd "$KIT_DIR" && sha256sum --check SHA256SUMS)
(cd "$KIT_DIR/card" && sha256sum --check SHA256SUMS)
```

The intermediate `SOURCE/backup-kit/card/` belongs to the legacy AP-hook kit and must stay on the host. Only its BusyBox is an input here; copy only the new management kit described below. Adjust the absolute QEMU path for your host. The management builder requires `--output`, refuses nonempty outputs and supports `--cc`, `--busybox`, `--readelf` and `--qemu` overrides. It never formats, copies to or contacts a camera.

`--password-file` is optional for producing a credential-free kit, but such a kit cannot start. When supplied, host OpenSSL receives the password through stdin and creates a salted MD5-crypt account in `LSCamoflash-yyos/httpd.conf`, outside `www/`. The plaintext password is not copied into the kit. The private authentication file is excluded from public manifests/checksums; keep the complete private kit and credentials out of published assets. The startup guard refuses missing, malformed or unsupported authentication.

The generated `card/` contains **`LSCamoflash-yyos/` plus five root files: `telnetd`, `busybox`, `dump.sh`, empty `yy_telnet_start` and `SHA256SUMS`**. The native `telnetd` filename invokes the project's launcher and starts no shell or Telnet daemon. For this management kit, **root `dump.sh` is the bounded management boot wrapper, not the NOR firmware dumper or identity collector**. Those kits share root filenames and must not be mixed.

## Stage the card

Keep the verified firmware backup, identity output and existing recordings in private host storage. Use the accepted writable FAT32 first-partition layout from the camera guide; this procedure provides no formatting or repartitioning commands. Power the camera off before retrieving or changing the card.

Before replacing a known diagnostic payload, disable the card-root `yy_telnet_start` marker. Archive only the known old root `telnetd`, `busybox`, `dump.sh`, `SHA256SUMS` and marker into an ordinary nested diagnostic directory after checking their identity. If replacing a previous management copy, also preserve its complete `LSCamoflash-yyos/` folder, including private credentials and startup log. Do not overwrite unknown files or erase `DCIM`, `firmware-backup/`, `yyos-identity/` or other user data; use a separate clean spare card if the existing payload is uncertain.

Copy the new kit's entire **`card/LSCamoflash-yyos/`** folder to the card root, keeping its name exactly. Copy the new `telnetd`, `busybox`, `dump.sh` and root `SHA256SUMS`, then copy the empty **`yy_telnet_start` last**. Do not copy the host package directory or mix in legacy `_ht_ap_mode.conf`, `_ht_get_log.conf`, `yy_debug.ini`, `hack.sh`, factory/recovery markers or firmware-update images. Before booting, check the staged bytes and flush them:

```sh
CARD_MOUNT="/media/your-user/CAMERA"
(cd "$CARD_MOUNT" && sha256sum --check SHA256SUMS)
(cd "$CARD_MOUNT/LSCamoflash-yyos" && sha256sum --check SHA256SUMS)
sync
```

Continue only if both checksum checks pass and the private `LSCamoflash-yyos/httpd.conf` is present. Close card windows and use the operating system's safe-eject action before removing it. The normal-boot marker requests the guarded startup wrapper; the persistent HTTP service is not limited to the wrapper's startup timeout. Physical acceptance of this management payload remains pending.

## Open and manage the dashboard

Insert the card while the camera is off, power it on and allow normal startup. Find its current address in your router's leases and open **`http://<camera-ip>:8080/`**, using your provisioned web account. HTTP Basic authentication does not encrypt traffic; keep this experimental service on the intended trusted LAN. The account protects this dashboard only and is independent of stock app, RTSP, ONVIF or diagnostic-shell authentication.

The owned HTTP lifecycle checks PID, executable, complete arguments and process start time before signalling a process. Existing state, an occupied port or an ownership mismatch causes refusal; do not delete state merely to force startup. In an existing authenticated diagnostic shell, these commands manually start or stop only the pilot's HTTP service:

```sh
/mnt/sdcard/LSCamoflash-yyos/bin/busybox sh /mnt/sdcard/LSCamoflash-yyos/start.sh
/mnt/sdcard/LSCamoflash-yyos/bin/busybox sh /mnt/sdcard/LSCamoflash-yyos/stop.sh
```

Run the needed command separately. This kit creates no diagnostic shell. Remove or archive only the root `yy_telnet_start` marker, while the camera is off, to stop requesting dashboard startup on later boots. Preserve the payload, credentials, logs, backups and recordings; flush and safely eject after card changes. A failed start leaves bounded lifecycle messages in `LSCamoflash-yyos/startup.log`; retain that log and root `backup-launcher.log` privately for diagnosis.

## Native media and acceptance limits

The Streams page displays candidate `rtsp://<camera-ip>:8554/stream0`, `rtsp://<camera-ip>:8554/stream1` and `http://<camera-ip>:5000/onvif/device_service` addresses. A listening TCP port does not establish decoding, audio, authentication or SOAP operation. The dashboard never enables native services or automatically requests media. No native-media activation procedure is provided here; those paths remain unverified on this firmware.

The management builder passed **10 offline checks including ARM926 execution**, and the runtime passed **12 offline checks**, including authenticated loopback HTTP and owned-process lifecycle, with no skips. These fixture results establish software behavior, not physical camera acceptance. Live authenticated UI/status access, stock-app/recording coexistence, memory use, repeated cold boots, local media and long-term use remain separate gates. The existing [verified NOR backup](camera-3225722.md#observed-nor-geometry) does not establish whole-chip coverage, atomicity or restoration.
