# Fullhan management pilot

This separate experimental payload targets **LSC SZ B22705, firmware 7.6.23, Fullhan FH8626V100**, with the exact stock `dgiot` SHA-256 recorded in its manifest. It leaves the stock application, RTSP server, networking, libraries and camera settings in place. It is manually started from the SD card; it is not an Anyka installer or automatic SD boot hook.

The interface has Dashboard, Recordings, Streams and Diagnostics tabs. It shows model/firmware, LAN address, uptime, CPU load averages, RAM used/available, SD capacity and service/process status. The recording browser exposes only finalized nonempty MP4 files from the stock `DCIM/YYYY/MM/DD/` layout, with ISO day filtering, pages of at most 100 entries and authenticated downloads. The recording endpoint implements GET/HEAD and a single byte Range; its complete HTTP path requires the separate patched Fullhan BusyBox described below. There are no upload, deletion or recording-write endpoints. Playback/download begins only when requested by the user.

Stock RTSP uses `rtsp://<camera-ip>:8554/main` and `/sub`. Both have verified H.264 video; neither advertised microphone audio in the stock checks. This payload adds no audio forwarding, image settings, PTZ, reboot or firmware update controls.

The expanded interface passed short live authentication, recording-list/download/Range and independent service restart checks on the test camera. A standard ONVIF client retrieved both native profiles, and both stock streams decoded while the original camera process remained running. Additional discovery was not live-enabled because stock discovery owns UDP 3702. These checks and the 440-test regression run do not establish long-term resource, stock-app or cold-boot acceptance. Follow the [camera guide](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-sz-b22705.md) for exact identity, verified backup evidence and remaining limits.

## Build and authentication

Use [Building and testing](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/building.md#build-the-separate-fullhan-pilot) for the dedicated BusyBox, ONVIF and payload builders. They require absent or empty output directories and refuse to replace previous outputs or site credentials. The credential-free CI payload cannot start until authentication is provisioned. Private builds and password files must remain outside public artifacts and source control.

Dashboard authentication is mandatory, with no default password. The builder's `--password-file` reads one private password line and creates a salted MD5-crypt hash in `httpd.conf`; `--username` selects the account name, defaulting to `admin`. The file stays at the payload root outside `www/`. Its strict grammar accepts one hashed account and rejects plaintext passwords and arbitrary path/interpreter directives. BusyBox HTTP Basic authentication does not encrypt the session; use this interface on a trusted LAN.

Optional ONVIF is assembled from a separately built static candidate using `--onvif-kit`. Provision an independent password with `--onvif-password-file`. Its `onvif.auth` contains exactly two plaintext lines, username then password, for WSSE UsernameToken / HTTP Digest authentication of protected Device/Media operations. `onvif.uuid` is a private UUIDv4 endpoint identity. Keep both outside `www/`, retain them across updates, and protect the physical card and private host outputs. A freshly provisioned build generates a new UUID; preserve the existing one when replacing the same camera's payload.

The only anonymous ONVIF operation is the read-only `GetSystemDateAndTime` query, which lets clients synchronize WSSE authentication timestamps with the camera’s clock. Device capabilities and media information still require WSSE UsernameToken or HTTP Digest authentication. Timestamp and replay checks remain enforced; this exception does not change the camera’s clock or settings.

The Fullhan-only BusyBox build carries a small HTTP patch to pass the request Range header to the recording CGI. A live request showed that the shared BusyBox 1.36.1 consumed that header before invoking CGI, preventing correct partial responses. Use `SOURCE/fullhan-busybox/bin/busybox` when assembling this payload; the stock and Anyka BusyBox binaries are not modified. The replacement passed authenticated live HTTP Range checks; emulated HTTP fixtures also cover partial responses, invalid ranges and unchanged static-file seeking.

## Place and start manually

After obtaining a verified independent backup, place only the complete named `LSCamoflash-fullhan/` folder on the camera-formatted FAT first partition. The camera must mount it at `/mnt/LSCamoflash-fullhan`. Do not install `HACK/`, Anyka `hostapd`, or Anyka boot markers. Do not repartition a working card for this pilot. For replacement, stop owned services first and preserve the previous payload and site-owned authentication/UUID files privately; do not merge over a running service directory.

From the camera's authenticated root diagnostic shell:

```sh
/mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/start.sh
```

Open `http://<camera-ip>:8080/` and use the privately provisioned dashboard account. The launcher checks exact hardware/application identity, a unique writable FAT MMC first partition at `/mnt`, public payload checksums, mandatory authentication, free port and absent lifecycle state. It refuses mismatches instead of replacing an existing service. Status refreshes every 15 seconds while visible; recording lists are loaded only when requested, and native browser playback is optional.

If the optional ONVIF candidate is included and provisioned, start it separately:

```sh
/mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/onvif-start.sh --no-discovery
```

On this camera, use **`--no-discovery`** because stock `dgiot` already owns UDP **3702**. Its observed discovery response advertises `http://<camera-ip>:835/onvif/device_service`; a working authenticated SOAP control path on port 835 has not been verified. The new service leaves stock discovery untouched and must be added manually at **`http://<camera-ip>:5000/`**, using the independent ONVIF account. It advertises the existing H.264 main/sub streams.

The optional bounded Probe/Resolve helper is fixture-tested but is not enabled on this unit. Do not stop stock discovery or assume its port-835 announcement refers to the new port-5000 service. Startup requires at least **8192 kB (8 MiB) `MemAvailable`**, one usable local IPv4 address, valid independent credentials/UUID and a free port 5000. This headroom gate is not a sustained-memory guarantee; live SOAP/client acceptance remains a separate check.

## Stop and preserve state

Stop optional ONVIF first if it is running, then stop the management interface:

```sh
/mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/onvif-stop.sh
/mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/stop.sh
```

The two services have separate state under `/tmp/lscamoflash-fullhan-onvif` and `/tmp/lscamoflash-fullhan`. Stop signals only processes whose stored start times, exact executable paths and complete arguments match; direct mode owns no discovery process. Preserve ownership-mismatch evidence instead of deleting state or signalling unrelated processes. Stopping HTTP does not implicitly stop ONVIF; neither stop command controls the stock camera application or RTSP server.

Fixed lifecycle messages are bounded in `startup.log`; HTTP requests and configuration contents are not logged there. Power off before removing the card. Reboot clears the running services and RAM state; run `start.sh` and, if using ONVIF, `onvif-start.sh --no-discovery` manually again. Removing this payload is not firmware restoration, and a physical backup-card remount/readback and restore remain unverified.

## Licenses

Project-authored files use `LICENSE.MIT`. Included BusyBox is GPL version 2 only; retain `COPYING.BusyBox`. Optional static ONVIF includes modified onvif_srvd, gSOAP authentication code, OpenSSL, zlib and toolchain runtime components; retain `COPYING.ONVIF` and consult the project's [third-party notices](https://github.com/dev-zetta/LSCamoflash/blob/main/SOURCE/3RD_PARTY_LICENSES.md) for component terms and source references. The project MIT license does not replace those component licenses.
