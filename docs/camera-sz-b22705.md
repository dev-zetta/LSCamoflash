# LSC Indoor 1080p SZ B22705: experimental Fullhan support

This camera already provides local RTSP video through its stock firmware. Its hardware, diagnostic shell and software backup were verified on **2026-10-14**. An earlier, manually started status-only dashboard passed live authentication, startup/shutdown and stock-stream coexistence checks on that date. The richer management interface, recording browser and optional authenticated ONVIF service subsequently passed short live checks, including recording Range downloads and a standard ONVIF client. This remains experimental Fullhan support rather than a complete camera-management runtime. Use the stock stream addresses below; do not install the Anyka runtime package or reuse the [3007325.5 camera profile](camera-3007325.5.md).

The observations apply to the tested **SZ B22705 running firmware 7.6.23**. Other cameras sold as “LSC Indoor 1080p” can use different hardware and firmware, including a later Anyka platform.

## What works so far

| Feature | Current evidence |
| --- | --- |
| Main and sub RTSP video | Both stock streams decoded over TCP without RTSP credentials. |
| Diagnostic Telnet | Port 23 opened after booting with the minimal `product.cof` configuration and its FAT read-only attribute. |
| Hardware and flash identification | CPU, kernel, libc, application identity, mounts and six NOR partitions inspected through the stock shell. |
| Firmware backup | All six exposed NOR partitions collected with paired matching reads; the private host copy passed verification of 109 checksummed files. Physical SD remount and restoration remain untested. |
| RTSP audio | Neither tested stream advertised an audio track. Microphone hardware and other audio paths have not been tested. |
| Fullhan management interface | Expanded Dashboard, Recordings, Streams and Diagnostics pages and authenticated status/API access passed short live checks. |
| Recording browser and downloads | Finalized-MP4 listing, authenticated HEAD and a verified 32-byte HTTP 206 Range response passed live checks. Browser codec/player compatibility remains client-dependent. |
| Optional ONVIF | Direct port-5000 service passed WSSE, HTTP Digest and standard-client profile/stream-URI checks. Use `--no-discovery` and manual client setup; stock `dgiot` owns UDP 3702. |
| Stock WS-Discovery | Response observed on UDP 3702 advertising port 835; an authenticated native SOAP control path there is unverified. |
| Camera settings, PTZ, audio forwarding and automatic SD startup | Not implemented for this Fullhan profile. |

Stock RTSP operation does not establish independence from Tuya services, successful operation with internet access blocked, or long-term stability. Those remain separate tests.

## Watch the stock video streams

Find the camera's current address in your router's DHCP leases and open one of these addresses in an RTSP-capable player:

| Stream | Address | Observed video |
| --- | --- | --- |
| Main | `rtsp://<camera-ip>:8554/main` | H.264, 1920×1080, 15 fps |
| Sub | `rtsp://<camera-ip>:8554/sub` | H.264, 640×360, 15 fps |

Each TCP check finished successfully after decoding 76 frames covering five seconds of media, with no RTSP authentication requested. No recording was retained. Their session descriptions contained video only, so the absence of sound in these RTSP tests does not establish a defective microphone.

[Guino's reference](https://github.com/guino/LSC1080P#review) also describes these paths on port 80. Port 80 streaming has not been verified on this exact camera. Use the tested port 8554 endpoints first; the Anyka profile's ports 88/89 and `/videoMain`/`/videoSub` paths do not apply here.

## Diagnostic access through the SD card

The stock `product.cof` setting documented by [guino/LSC1080P](https://github.com/guino/LSC1080P#root-access) enabled Telnet on the tested camera. This provides a diagnostic shell; it does not install LSCamoflash or start its services.

Use a spare card and preserve existing recordings before changing it. The first attempt used FAT32 on the whole card without a partition table. The camera reformatted that card to an MBR layout with a first FAT partition, removing the diagnostic file. On the subsequent attempt, the file was placed on the camera-formatted partition with the FAT read-only attribute set. Telnet then opened on port 23, and the file remained after the second boot. A whole-device FAT layout working on the Anyka camera therefore does not establish suitability here.

With the camera powered off, mount that camera-formatted card on the computer and put a plain-text file named **`product.cof`** directly at its root. The accepted minimal contents were:

```ini
[DEFAULT_SETTING]
telnet=1

```

Use Unix line endings, retaining a blank line after `telnet=1`. Set the file's **FAT read-only attribute (`R`)** before safely ejecting the card. A Unix `chmod` command on a mounted FAT filesystem does not establish that this DOS/FAT attribute is set; use a FAT-aware attribute tool and inspect the result. Do not make the entire card read-only, because stock recording and backup output require writable storage.

Insert the card while the camera is off, power it on, and check its current LAN address. Connect to **Telnet port 23** using the stock login documented in [the reference's root-access section](https://github.com/guino/LSC1080P#root-access). The LSCamoflash web UI and shell defaults for Anyka installations are separate and do not apply to this stock firmware.

Keep this access on a trusted LAN: Telnet sends its session without encryption, and this firmware family has publicly documented credentials. Copying the reference repository's complete toolkit is unnecessary for this minimal diagnostic step. In particular, do not add `[STATION]` Wi-Fi settings or replace startup scripts merely to open the shell; those select other operating modes in related projects.

To stop requesting diagnostic access, power off, retrieve the card, clear the file's FAT read-only attribute if needed, and move `product.cof` away from the card root or remove it. Safely eject and cold-boot, then check whether port 23 is closed and normal camera functions still work. Disabling Telnet and persistence of this setting after marker removal have not yet been physically verified.

## Exact identity

| Item | Observed value |
| --- | --- |
| Product label | LSC Indoor 1080p, SZ B22705 |
| App firmware / MCU version | 7.6.23 / 7.6.23 |
| SoC / kernel hardware field | Fullhan FH8626V100 |
| CPU | ARM1176 family; ARMv6-compatible processor, `armv6l` |
| Linux kernel | 4.9.129 |
| Stock C library | uClibc 0.9.33.2 |
| Stock BusyBox | 1.26.2 |
| Kernel-reported total RAM | 31,320 KiB |
| Stock application | `/usr/bin/dgiot`, 5,807,124 bytes |
| Root filesystem | SquashFS, mounted read-only |
| Persistent configuration | `/etc/conf`, JFFS2, mounted read-write |
| SD mount | `/mnt`, VFAT from `/dev/mmcblk0p1` |

The tested `dgiot` executable has this SHA-256:

```text
ef9545b2f4fce419d71dadf7723a9cb010500c994a87a325a8c325b51648c8b2
```

This identity is a compatibility boundary. An application with a different hash requires its own inspection; settings, binary offsets and runtime hooks from another firmware must not be assumed compatible. The stock binary and recovered configuration remain private and are not included in this repository.

## NOR layout and backup status

The live proc/sysfs inventory exposed six NOR partitions. Their reported offsets and sizes form a contiguous 8 MiB address range:

| MTD | Name | Offset in bytes | Size in bytes |
| --- | --- | ---: | ---: |
| `mtd0` | `bootstrap` | 0 | 262,144 |
| `mtd1` | `uboot-env` | 262,144 | 65,536 |
| `mtd2` | `uboot` | 327,680 | 262,144 |
| `mtd3` | `kernel` | 589,824 | 1,900,544 |
| `mtd4` | `rootfs` | 2,490,368 | 5,570,560 |
| `mtd5` | `config` | 8,060,928 | 327,680 |
| **Total** | | | **8,388,608** |

The inventory reports 65,536-byte erase blocks, a one-byte write unit and no OOB data. These observations identify the exposed layout; they do not establish physical chip coverage or a working restoration procedure. Do not concatenate partition files into a guessed flash image or apply another device's recovery image.

The manual collection completed on this exact camera, producing two matching reads of each of the six partitions, totaling **8,388,608 partition bytes**, and a **12,785,664-byte stock userspace archive**. After transfer to private host storage, the verifier checked the complete manifest, partition lengths and read pairs, and **109 checksummed files**. The recovered `dgiot` executable also matched the live application's SHA-256 above. The earlier failed attempt was retained separately.

Additional checked file and directory `fsync` calls, including the SD root, returned success before transfer. They used BusyBox `sync FILE` without `-f`. The completed backup was transferred through an authenticated FTP service restricted to the camera and verified on the host; this was a temporary transfer arrangement, not a Fullhan runtime FTP service. A fresh physical SD remount/readback and a restore have not been performed.

Writable stock configuration can change while the camera runs, so matching reads do not establish an atomic snapshot of the entire device. Keep partition images, userspace archives, credentials and raw logs in private host storage. This guide intentionally provides no flash erase, write or restore procedure.

## Manual backup through the stock shell

The repository's [NOR backup tools](../tools/firmware-backup/README.md) separate the reusable collector from the Anyka-specific SD launcher. On this Fullhan camera, collection is started manually through the existing authenticated diagnostic shell. Use only the collector script and its compatible static BusyBox in a dedicated directory on the writable, camera-formatted SD card. Do not install the Anyka `hostapd` launcher or its `_ht_ap_mode.conf` / `_ht_get_log.conf` markers.

Before collection, confirm the exact application/hardware identity, the live NOR inventory and the writable VFAT mount at `/mnt`. The collector checks the visible mount and device, bounds each operation, retains independent read pairs and writes each attempt into a new `firmware-backup/run-*/` directory. Its optional process-map collection now tolerates a stock process exiting during inspection; this correction passed 66 focused host and ARM tests before the successful device capture.

Keep the complete run directory and its metadata together when transferring it to the host, then run the [host verifier](../tools/firmware-backup/verify-backup.py). Check its exit status and `verified: true` result before treating the copy as a verified backup. Preserve failed attempts for diagnosis, and keep the additional checked file/directory flush and physical remount limits above separate from host checksum verification. Preparing the runtime or modifying startup files is unnecessary for this software backup path.

## Experimental Fullhan management interface

This isolated interface has **Dashboard**, **Recordings**, **Streams** and **Diagnostics** tabs. It reports the model, firmware, LAN address, uptime, RAM used/available, CPU load averages, SD capacity and service/process status. A bounded recording browser lists finalized MP4 files by day and supports authenticated downloads and optional browser playback. The stock `dgiot` application continues to own the camera and network configuration. There are no settings, PTZ, reboot, firmware-update or recording-deletion controls.

The expanded interface, recording endpoints and direct ONVIF service passed the short live checks recorded below. The earlier status-only pilot’s measurements are retained separately as historical evidence. The additional discovery helper remains fixture-tested only and is not enabled on this unit.

### Prepare the private payload

Complete and verify an independent firmware backup first. Download **`LSCamoflash-2.01.0000-fullhan.tar.gz`** and `SHA256SUMS` from [v2.01.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.01.0000), verify the archive, and extract it into private host storage. It contains the required top-level **`LSCamoflash-fullhan/`** folder, static ONVIF, helpers, notices and payload checksums. Check the extracted public files with `sha256sum -c SHA256SUMS` from inside that folder.

The public archive contains no `httpd.conf`, `onvif.auth` or `onvif.uuid`. **Authentication is mandatory, and there is no default dashboard password.** Provision private credentials on the host before copying the folder to the camera. Published binaries require no compilation; a source build remains available through [Building and testing](building.md#build-the-separate-fullhan-pilot).

#### Provision downloaded credentials

Use host Python 3 and OpenSSL from a terminal. In the example below, replace the folder path with your freshly extracted private folder. It prompts for two independent passwords without echoing them, requires 1–128 printable ASCII characters, and refuses existing credential/UUID files, including symlinks. No password is passed in a command argument. Save the example outside the payload folder if you prefer running it as a file.

```python
from pathlib import Path
import getpass
import os
import re
import subprocess
import uuid

folder = Path("/absolute/private/path/LSCamoflash-fullhan")
if folder.name != "LSCamoflash-fullhan" or folder.is_symlink() or not folder.is_dir():
    raise SystemExit("Choose the freshly extracted LSCamoflash-fullhan directory")
paths = [folder / name for name in ("httpd.conf", "onvif.auth", "onvif.uuid")]
if any(os.path.lexists(path) for path in paths):
    raise SystemExit("Existing site credentials or UUID must be preserved")

def password(label):
    value = getpass.getpass(label + ": ")
    confirmation = getpass.getpass("Confirm " + label + ": ")
    if value != confirmation or not 1 <= len(value) <= 128 or any(not 32 <= ord(c) <= 126 for c in value):
        raise SystemExit("Use matching, nonempty printable ASCII passwords of at most 128 characters")
    return value

web = password("Dashboard password")
onvif = password("Independent ONVIF password")
if web == onvif:
    raise SystemExit("Choose different dashboard and ONVIF passwords")
result = subprocess.run(["openssl", "passwd", "-1", "-stdin"],
                        input=(web + "\n").encode("ascii"), capture_output=True, check=True, timeout=10)
hashed = result.stdout.decode("ascii").strip()
if not re.fullmatch(r"\$1\$[A-Za-z0-9./]{1,8}\$[A-Za-z0-9./]{22}", hashed):
    raise SystemExit("OpenSSL did not return the expected salted password hash")
contents = ["I:index.html\n/:admin:" + hashed + "\n", "admin\n" + onvif + "\n", str(uuid.uuid4()) + "\n"]
created = []
old_mask = os.umask(0o077)
try:
    for path, content in zip(paths, contents):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        identity = os.fstat(fd)
        created.append((path, identity.st_dev, identity.st_ino))
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
except BaseException:
    for path, device, inode in reversed(created):
        try:
            current = path.lstat()
            if (current.st_dev, current.st_ino) == (device, inode):
                path.unlink()
        except FileNotFoundError:
            pass
    raise
finally:
    os.umask(old_mask)
print("Private credentials created for username admin. Keep this folder private.")
```

The resulting web password is stored only as a salted MD5-crypt hash in `httpd.conf`; ONVIF needs its own two-line plaintext `onvif.auth` for its authentication protocols. `onvif.uuid` gives the service a private endpoint identity. All three stay at the payload root outside `www/` and are intentionally absent from public checksums. Preserve them across replacements instead of regenerating credentials or endpoint identity. The example only writes local host files and does not contact a camera.

For a private source build instead of downloaded binaries, use the builder options below.

Use the builder's `--password-file` option with a private host file containing one password line. The username defaults to `admin` and can be changed with `--username`. The builder produces `httpd.conf` with a salted MD5-crypt password hash; it does not store the plaintext password in the payload. Keep both the host password file and generated private payload out of the repository and public artifacts. The strict runtime configuration accepts one hashed account and rejects plaintext passwords or arbitrary HTTP/interpreter directives.

The dashboard account is separate from the stock Telnet login, Anyka web UI account and optional ONVIF account. HTTP Basic authentication protects the interface and recording endpoints but does not encrypt network traffic. Use it only on the intended trusted LAN. ONVIF needs the independently provisioned credentials described below.

### Place it on the existing card

Power the camera off and mount its existing camera-formatted FAT partition on the computer. Copy only the complete, privately provisioned **`LSCamoflash-fullhan/` folder** to the card root, preserving its name and contents. On the camera this must become **`/mnt/LSCamoflash-fullhan/`**, with `start.sh`, `stop.sh`, `common.sh`, `httpd.conf`, `bin/` and `www/` inside. Authentication stays outside the served `www/` directory.

Use an absent destination for a new installation. For a replacement, stop both owned services first, archive the prior payload privately, and preserve `httpd.conf`, `onvif.auth` and `onvif.uuid` as applicable before staging the complete new folder. Do not merge over a running directory or replace service state to get past a failed check. Preserve recordings, the diagnostic `product.cof` file and firmware backups. Do not run the Anyka installer, copy `HACK/`, or install its `hostapd` launcher and boot markers. The Fullhan pilot does not require repartitioning or formatting.

Safely eject the card, insert it while the camera is off, and boot normally. The pilot has no SD autostart hook. Log into the existing stock diagnostic shell after each camera reboot to start it manually.

### Start and use it

From the camera's root diagnostic shell, run:

```sh
/mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/start.sh
```

The launcher requires FH8626V100 hardware, the exact stock `dgiot` SHA-256 recorded above, a unique writable first FAT MMC partition mounted at `/mnt`, matching payload checksums and a valid hashed account. It also refuses a busy port 8080 or existing pilot state. Do not bypass these checks for a different camera or firmware.

After a successful start, open **`http://<camera-ip>:8080/`** and use the username/password provisioned for this private payload. Dashboard status refreshes every 15 seconds while the page is visible; CPU load is an average, not CPU usage percent. RAM used is total minus available, and both are displayed in MiB. The stream links still select the stock video-only RTSP endpoints on port 8554; enabling the interface does not add microphone audio or RTSP authentication.

The **Recordings** tab loads metadata only when opened or refreshed. It browses the stock `DCIM/YYYY/MM/DD/` layout through ISO day selections and pages of at most 100 entries. Only nonempty finalized `<start-timestamp>-<end-timestamp>.mp4` files are exposed; temporary recordings and unrelated log/configuration files are excluded. The list reports when a safety scan limit makes the inventory incomplete.

Use **Download** for an authenticated file transfer or **Play** to open the native browser player. No recording is fetched automatically on page load, and playback depends on the browser’s codec support. The recording endpoint implements GET, HEAD and a single byte Range for seeking/resume. Its complete HTTP path requires the isolated Fullhan BusyBox build: a live request showed that the shared BusyBox consumed the Range header before invoking CGI. Use the Fullhan-only patched binary from the build guide; its on-camera HTTP retest returned the requested 32 bytes with status 206 and a valid MP4 header. It provides no upload, delete or write operation; a busy recording being finalized may require refreshing the list.

If startup fails, preserve the shell's error and any `LSCamoflash-fullhan/startup.log` on the card. That log contains bounded lifecycle messages, not request traces or credential contents. A generated page or successful build alone is not proof that the pilot has started on the camera.

### Stop the management interface

If optional ONVIF was started, stop it separately using the command below before replacing the payload or powering off. To stop HTTP and the recording endpoints, run from the same diagnostic shell:

```sh
/mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/stop.sh
```

Stop only signals the HTTP process when its PID, start time, executable and command line match the pilot's saved state. If it reports an ownership mismatch, preserve the evidence rather than deleting state or signalling an unrelated process. Successful stop removes the private PID state under `/tmp/lscamoflash-fullhan`; it does not stop `dgiot` or its RTSP service.

Power the camera off before removing the card or archiving the pilot directory. Removing the pilot is not firmware restoration. Reboot clears its running service and RAM state; start it manually again after boot. Repeatable cold-boot persistence and normal-app acceptance remain user/device checks.

### Optional ONVIF with manual client setup

ONVIF is a separately built, opt-in service in the Fullhan package. It advertises the existing H.264 main/sub RTSP streams without transcoding them. Build it with [the Fullhan ONVIF options](building.md#build-the-separate-fullhan-pilot); a dashboard-only payload does not provide an ONVIF service. Ten focused ARM authentication/profile tests passed, including stale timestamp and replay rejection. Direct on-camera WSSE, HTTP Digest and standard-client checks also passed. The camera’s existing `dgiot` process owns UDP 3702, so this unit must use the new service without an additional discovery process.

ONVIF credentials are mandatory for service startup and protected Device/Media operations, and are independent of the dashboard password. Its private `onvif.auth` contains exactly two lines: username, then plaintext password. The private `onvif.uuid` contains a UUIDv4 used as the discovery endpoint identity. Both are kept outside `www/`. Preserve both files across replacements so credentials and client registrations remain stable; do not publish them or move them into the recording/web directories.

The only anonymous ONVIF operation is the read-only `GetSystemDateAndTime` query, which lets clients synchronize WSSE authentication timestamps with the camera’s clock. Device capabilities and media information still require WSSE UsernameToken or HTTP Digest authentication. Timestamp and replay checks remain enforced; this exception does not change the camera’s clock or settings.

From the camera's root diagnostic shell, start this optional service separately:

```sh
/mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/onvif-start.sh --no-discovery
```

Use **`--no-discovery`** on this camera. Startup checks the exact firmware, payload, credentials, unique LAN address, free port 5000 and process state while leaving stock UDP 3702 untouched. It requires at least **8 MiB (`8192 kB`) of kernel-reported `MemAvailable`** before starting the ONVIF process. This is a startup guard, not a guarantee of sustained memory headroom or multiple-client stability. If it refuses to start, retain the error rather than lowering the threshold or bypassing ownership checks.

| Service | Address / port | Authentication |
| --- | --- | --- |
| Management and recordings | `http://<camera-ip>:8080/` | Dashboard HTTP Basic account |
| Optional ONVIF Device/Media | `http://<camera-ip>:5000/` | Independent WSSE / HTTP Digest account; only the read-only clock query is anonymous |
| Stock WS-Discovery | UDP 3702, owned by `dgiot` | Observed XAddr `http://<camera-ip>:835/onvif/device_service`; authenticated native SOAP control path unverified |
| Stock RTSP | TCP 8554, `/main` and `/sub` | No RTSP credentials requested in the stock video checks |

After a successful start, the **Streams** tab reports the ONVIF service address and **Dashboard** reports its service state. Add **`http://<camera-ip>:5000/` manually** in the client using the independent ONVIF account. Stock discovery advertises the separate port-835 address above; that announcement does not identify or validate the new port-5000 service. The optional bounded Probe/Resolve helper passed fixtures but is not live-enabled on this unit because UDP 3702 is already occupied. Do not stop stock discovery to make room for it. The ONVIF service provides read-only Device/Media information and native H.264 stream profiles, not PTZ, audio, camera settings, reboot or firmware update.

Stop the owned ONVIF service separately:

```sh
/mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/onvif-stop.sh
```

The stop path requires matching executable paths, process start times and complete arguments before signalling owned processes; `--no-discovery` mode owns no discovery process. It does not stop the stock application or RTSP service. HTTP and ONVIF have separate lifecycle state; stopping the dashboard does not itself stop ONVIF. Both services must be started manually again after a camera reboot: `start.sh`, then `onvif-start.sh --no-discovery` if the optional ONVIF service is used.

### Expanded management and ONVIF live validation

On **2026-10-14**, the expanded payload passed all **20 on-camera payload checksum entries** and checked file/directory flushes, with deployment exiting zero. The Fullhan-only patched BusyBox was used; the stock and Anyka binaries were not changed, and this deployment issued no flash writes.

**Seventeen HTTP checks** passed, covering authentication, served management assets/status, finalized-recording lists, HEAD handling and a **32-byte HTTP 206 Range response** with the expected MP4 header. This exercised the complete HTTP-to-CGI path that failed with the shared BusyBox, rather than only calling the recording helper directly. Unauthorized and unsupported requests were rejected; private configuration and backup paths were excluded.

**Fourteen on-camera SOAP checks** passed against the direct service on port 5000: HTTP Digest, WSSE UsernameToken, the anonymous clock-bootstrap query, capabilities and both native media profiles/stream URIs. Stale timestamps and replayed tokens were rejected, and unsupported mutations returned faults. An independent **python-onvif-zeep 0.2.12 / Zeep 4.3.3** client then used automatic camera-clock offset handling and completed five SOAP calls with HTTP 200: `GetSystemDateAndTime`, `GetCapabilities`, `GetProfiles`, and `GetStreamUri` for each profile. It found the main 1920×1080 and sub 640×360 H.264 profiles. The same standard-client calls passed again after the owned services were independently stopped and restarted.

Both stock RTSP endpoints remained usable with HTTP and ONVIF running. Main H.264 at 1920×1080 and sub H.264 at 640×360 each reported 15 fps and decoded **45 frames over TCP**, with probe and decoder exit status zero and completed progress. Neither stream advertised audio. The streaming checks saved no footage.

Duplicate starts were refused, and independent HTTP/ONVIF stop/restart checks preserved the stock application’s original PID and process start time. Stock UDP 3702 discovery remained in place; the new service ran with `--no-discovery`. Automatic discovery of the new service was not live-tested, and the stock port-835 SOAP path remains unverified.

With both services running, sampled `MemAvailable` ranged from **12,940 to 13,468 KiB (about 12.6–13.2 MiB)** out of 31,320 KiB total. The HTTP daemon measured up to **640 KiB resident memory**, with a 640 KiB high-water mark; ONVIF measured **1,044 KiB resident memory**, with a **5,204 KiB high-water mark**. The stock application’s sampled resident memory ranged from 7,872 to 8,952 KiB. These varying request-time samples do not isolate each service’s marginal cost or guarantee sustained headroom. No matching OOM entry was found in the sampled kernel log.

The complete host/ARM regression run finished with **440 tests passed, no skips, in 122.457 seconds**, including ARM1176/ARM926 paths and real HTTP Range/SOAP fixtures. These automated checks complement the separate live camera evidence above. Long-term and multiple-client operation, normal app/recording acceptance, internet-blocked operation, repeatable cold-boot startup, microphone audio, physical backup-card remount/readback and restoration remain unverified. Firmware-specific camera controls and automatic startup are not implemented.

### Earlier status-only pilot validation

On **2026-10-14**, the dedicated SD payload passed its on-camera checksums and checked file/directory flushes. Twelve HTTP checks verified mandatory login, authenticated HTML/JavaScript/status responses, read-only method handling, invalid-host rejection and exclusion of private configuration. A duplicate start was refused; owned shutdown closed port 8080, and manual restart succeeded. The original `dgiot` PID and process start time remained unchanged through the cycle.

With the pilot running, both stock RTSP endpoints decoded 45 frames over TCP, each with exit status zero and completed progress. The dashboard daemon reported **648 KiB resident RAM**, with **13,456 KiB available out of 31,320 KiB total RAM** at the final sample. No OOM message was found in the sampled kernel log. These are short measurements under the tested workload, not a long-term resource or app-connectivity guarantee. No footage was retained.

For that earlier status-only payload, the complete local regression suite passed **356 tests**, including the 14 Fullhan fixtures and optional ARM checks; its credential-free and private builds also passed ARM1176 emulation. These counts and live measurements predate the richer interface, recording browser and optional ONVIF candidate. Proprietary firmware, diagnostic output and site credentials remain private. The user subsequently confirmed the dashboard works. Fresh physical SD-remount verification, restoration, stock-app acceptance, internet-blocked operation and cold-boot automatic startup have not been established.

## Shared interface and remaining capability gates

The camera has a nominal 32 MB of RAM; the kernel exposes **31,320 KiB (30.6 MiB)**. The current HTTP/ONVIF samples above show about 12.6–13.2 MiB available during the bounded checks. Available memory includes reclaimable memory and is headroom for applications; it is not RAM already consumed by LSCamoflash. Peak usage and request-time variation matter, so additional resident services and media operations still require their own measurements.

The richer interface now follows the project’s navbar, cards and tab navigation while using dependency-free browser code. Its static HTML, CSS and JavaScript live on the SD card and execute mainly in the user’s browser. BusyBox HTTP and dedicated CGI/helpers serve the interface without adding PHP or Python. Anyka-specific CGI handlers are not reused for camera control because their settings, session storage, paths and process assumptions differ.

| Management area | Implementation and remaining gate |
| --- | --- |
| Status, network information, CPU/SD/RAM and RTSP links | Implemented; authenticated management assets/status and stock-stream coexistence passed short live checks. |
| Authentication and recordings | Mandatory dashboard authentication, bounded finalized-MP4 lists and HTTP HEAD/Range passed live checks. Private backup/configuration paths are not served; native browser playback varies by codec support. |
| ONVIF media profiles and discovery | Direct port-5000 WSSE/Digest and standard-client profile/URI checks passed. The new discovery helper remains fixture-only on this unit; stock port-835 discovery is untouched and its SOAP path unverified. |
| Image settings, night vision, motion, audio and camera restart | Need validated `dgiot` configuration, IPC or driver adapters. Function-name strings in the binary are investigation clues, not callable or tested APIs. |
| Motor controls | Require applicable motor hardware and its verified Fullhan interface; Anyka process offsets do not apply. |
| Automatic startup | Still unresolved on the stock SD boot path; the pilot currently requires a manual start after reboot. |

The richer interface, recording endpoints and direct ONVIF service now have bounded live evidence, including resource samples and stock-stream coexistence. Longer and multiple-client tests are still needed; the additional discovery helper remains disabled on this unit. Audio and snapshots can require substantially more transient media processing than serving the management page. Firmware-specific controls remain unimplemented until their individual adapters and device behavior have been validated.

## What a Fullhan port still needs

This camera starts `dgiot` rather than the Anyka `anyka_ipc` application. The Anyka native `hostapd` hook, SD overlay assumptions and RTSP callback preload were developed for another startup path and binary ABI. They are not compatible Fullhan components.

No automatic custom-script startup from the stock SD card has been established. Guino's non-flashing customization uses an external host to start tools after reboot; that is a separate design from a self-starting LSCamoflash runtime. The isolated management interface and direct ONVIF service have passed the bounded checks above. A broader Fullhan port still needs a validated persistent startup method, its own camera-service and configuration integration, longer resource measurements, and repeatable reboot/app/streaming acceptance. Stock Telnet and RTSP working are useful investigation results, not full runtime support.

## Related primary references

- [guino/LSC1080P](https://github.com/guino/LSC1080P) documents the `product.cof` Telnet setting and stock RTSP paths on a related device running firmware 7.6.32. Its exact-version evidence is separate from the 7.6.23 observations above.
- [berobloom/LSCIndoorCameraLocal1080p](https://github.com/berobloom/LSCIndoorCameraLocal1080p) explicitly targets the 2021 Fullhan variant and describes a different TUTK development mode. Its flash-modifying setup is not a verified installation procedure for this camera.
- [berobloom/LSC-1080p-Anyka-Decloud](https://github.com/berobloom/LSC-1080p-Anyka-Decloud) targets a separate 2025 Anyka variant. A similar housing or product name does not make that platform's instructions applicable to the identified FH8626V100 unit.

When reporting another unit, include its label, app/MCU versions, observed hardware identity and stream behavior through this fork's [issue tracker](https://github.com/dev-zetta/LSCamoflash/issues). Redact network credentials, serial numbers and account identifiers before sharing diagnostics.
