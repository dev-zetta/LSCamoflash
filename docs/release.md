# LSCamoflash releases

## Version 2.01.0000 - 2026-10-16

This minor release adds a separate experimental **YYOS LSC 3225722 / SZ F26312 / V14.1.5** package while retaining the Anyka and Fullhan packages. Download the archive for your platform, `SHA256SUMS` and notices from [v2.01.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.01.0000). See the [2.01.0000 changelog](https://github.com/dev-zetta/LSCamoflash/blob/v2.01.0000/CHANGELOG.md) for changes.

| Release asset | Intended use |
| --- | --- |
| `LSCamoflash-2.01.0000-uclibc.tar.gz` | Full **Anyka** runtime, generated card files and installers. |
| `update-2.01.0000-uclibc.tgz` | Existing **Anyka** runtime update, excluding `HACK/etc/` and the local root crontab. |
| `LSCamoflash-2.01.0000-fullhan.tar.gz` | Separate experimental **Fullhan SZ B22705 / 7.6.23** management folder with static ONVIF; credential-free and manually started. |
| `LSCamoflash-2.01.0000-yyos.tar.gz` | Separate experimental **YYOS 3225722 / SZ F26312 / V14.1.5** management, controls, host recording tools and optional SSH; requires private provisioning. |
| `LSCamoflash-2.01.0000-backup-kit.tar.gz` | Separate stock NOR backup tools; supported legacy Anyka SD hook and generic collector. YYOS uses its own documented kit. |
| `LSCamoflash-2.01.0000-source.tar.gz` | Public source and declared build inputs; not a camera installation. |
| `SHA256SUMS` | Hashes for the other **nine** files; this release has **ten** assets in total. |
| `THIRD_PARTY_NOTICES.md`, `LICENSE.MIT`, `COPYING.BusyBox` | Component/source notices and license texts; platform archives retain additional component notices and sources. |

### YYOS setup and verified scope

Follow the [YYOS setup guide](yyos-setup.md) for the exact supported stock application identity, download verification, private provisioning and guarded SD installation. The archive contains the fixed host folder `LSCamoflash-yyos-kit/`, its platform-specific `card/` files, installer, source/build provenance and notices. It contains no web credentials, local control key, SSH owner/host keys or SSH enable marker. Provision the web account on your computer; provision optional controls and SSH only when wanted. This kit uses the normal YYOS SD entry, starts management alongside the stock application and does not install the Anyka overlay or Fullhan runtime.

The [management interface](yyos-management.md) provides authenticated status and completed raw recording/metadata downloads. The [host recording converter](yyos-recordings.md) preserves encoded H.264/PCMU packets and their relative timing for the supported unencrypted recording format. Optional [Controls](yyos-controls.md) provides indicator/timestamp switches, fixed short cardinal PTZ steps and Stop, protected by the private local key and authenticated same-origin requests. The owner confirmed working camera rotation after deployment. Optional [SSH](yyos-ssh.md) uses Ed25519 keys, with password login and forwarding disabled.

Short device checks accepted authenticated management, native H.264 main/sub video with PCMU audio, manual ONVIF, owned HTTP restart, recording downloads and bounded horizontal controls. The owner confirmed recorded microphone sound, Tuya app connectivity and camera rotation. The SSH-guarded native setup passed a separate retaining-password trial; legacy unguarded configuration remains blocked. Follow the [native-media safeguards](yyos-native-media.md) rather than assuming that installing management enables streams.

The public static musl SSH replacement passed a temporary-port root/PTY and authorization check; its normal cold boot remains unverified. The earlier normal-boot SSH evidence used a different private build. The rotation confirmation is separate from a new cold boot, vertical/combined app-control behavior and repeated-boot endurance. Detailed app/recording behavior, [VLC playback](yyos-vlc.md), synchronization and long-term stability remain open. A firmware backup does not establish atomic capture, whole-chip coverage or a working restore.

### Existing platforms and publication

For **Anyka 3007325.5 / 6.2863.125.1348**, use [Installation](installation.md) and the [camera guide](camera-3007325.5.md). Local H.265 main/H.264 sub video with PCMA audio and manual ONVIF remain the verified profile behavior. Local mode replaces Tuya app operation and requires explicit Wi-Fi settings; toolkit PTZ and automatic discovery remain unavailable.

For **Fullhan SZ B22705 / 7.6.23**, use the [separate private setup](camera-sz-b22705.md#prepare-the-private-payload). Management and static ONVIF require private credentials and manual startup; camera controls, PTZ, microphone forwarding and automatic startup remain unavailable. The Anyka update archive applies only to an existing Anyka runtime and updates neither Fullhan nor YYOS.

Published archives contain no proprietary camera firmware, device credentials, private logs or actual backups. The backup tools are separate from runtime installation and are not recovery images. The [publication workflow](building.md#publish-a-github-release) publishes checksummed assets from the successful CI build for the exact release commit.

## Version 2.00.0000 - 2026-10-14

This major release adds a separate experimental Fullhan management package alongside the Anyka runtime. Download the platform-specific archives, `SHA256SUMS` and notices from [v2.00.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.00.0000). The project retains its custom `major.minor.revision` format. See the [2.00.0000 changelog](https://github.com/dev-zetta/LSCamoflash/blob/v2.00.0000/CHANGELOG.md) for changes.

| Release asset | Intended use |
| --- | --- |
| `LSCamoflash-2.00.0000-uclibc.tar.gz` | Full **Anyka** runtime, generated card files and installers. |
| `update-2.00.0000-uclibc.tgz` | Existing **Anyka** runtime update, excluding `HACK/etc/` and the local root crontab. |
| `LSCamoflash-2.00.0000-fullhan.tar.gz` | Separate experimental **Fullhan SZ B22705 / 7.6.23** management folder with static ONVIF; credential-free and manually started. |
| `LSCamoflash-2.00.0000-backup-kit.tar.gz` | Separate stock NOR backup tools; its SD boot launcher applies to supported Anyka cameras. Fullhan uses the generic collector through its stock shell. |
| `LSCamoflash-2.00.0000-source.tar.gz` | Public source and declared build inputs; not a camera installation. |
| `SHA256SUMS` | Hashes for the other eight release files. |
| `THIRD_PARTY_NOTICES.md`, `LICENSE.MIT`, `COPYING.BusyBox` | Component/source notices and license texts; the Fullhan archive also retains its ONVIF notices. |

For **Anyka 3007325.5 / firmware 6.2863.125.1348**, follow [Installation](installation.md) and the [camera guide](camera-3007325.5.md). Its verified local H.265 main/H.264 sub streams include PCMA audio, and manual ONVIF selects the H.264 substream. Local streaming replaces Tuya app operation and requires explicit Wi-Fi settings; toolkit PTZ and automatic discovery remain unavailable on this exact profile.

For **Fullhan SZ B22705 / FH8626V100 / firmware 7.6.23**, follow the [separate guide](camera-sz-b22705.md#prepare-the-private-payload). The archive contains `LSCamoflash-fullhan/`, whose name and placement at `/mnt/LSCamoflash-fullhan/` must be preserved. It contains no `httpd.conf`, `onvif.auth` or `onvif.uuid`: provision private credentials before starting. Do not run Anyka installers or install their `hostapd` boot hooks on this platform.

Fullhan short live checks verified authenticated status and recording HEAD/Range, WSSE and HTTP Digest ONVIF, native H.264 main/sub profiles, standard-client stream URIs and independent stop/restart without replacing the stock application. Start HTTP manually after each reboot; optional ONVIF additionally uses `onvif-start.sh --no-discovery` and a manually added port-5000 address. Stock UDP 3702 discovery stays untouched. Only the read-only ONVIF clock query is anonymous for WSSE synchronization; protected Device/Media data requires authentication.

Fullhan camera controls, PTZ, microphone forwarding and automatic startup are not implemented. Neither profile’s short checks establish long-term or multiple-client stability, every stock-app/recording function, atomic firmware capture or successful restore. Published packages contain no proprietary firmware, device credentials, private logs or actual firmware backups. The backup kit is separate from both runtime packages and is not a recovery image.

The publication procedure is [Building and testing → Publish a GitHub release](building.md#publish-a-github-release). The workflow publishes checksummed assets from the successful CI build for the exact release commit.

## Fork 1.03.2413 - 2026-10-13

This is the first release of the `dev-zetta/LSCamoflash` fork. Download packages, checksums and source from the [v1.03.2413 release page](https://github.com/dev-zetta/LSCamoflash/releases/tag/v1.03.2413). Read the [changelog](https://github.com/dev-zetta/LSCamoflash/blob/v1.03.2413/CHANGELOG.md) for the complete change summary.

The fork integrates all four originally open upstream pull requests: build and USB-reader installation fixes, RTSP/ONVIF configuration, Wi-Fi association before DHCP, and IPC-XC-C323 detection/PTZ with valid motor JSON responses. Further work repairs ARM builds, checks packaged executables and archives, bounds runtime startup, preserves stock settings and network tools, improves update replacement and corrects memory/SD status reporting. Host and ARM926 fixtures cover these paths; pinned Node 24-compatible actions and the release workflow require validation before publication.

On the exact LSC Smart PTZ Camera 3007325.5 / SI L25502 firmware 6.2863.125.1348, physical checks verified SD firmware backup, normal-mode Wi-Fi and web UI login, and local H.265 main/H.264 sub video with PCMA audio on both streams over TCP and UDP after reboot. The user confirmed audible microphone sound. ONVIF Device/Media SOAP requests worked through manual connection and returned the H.264 substream. Follow the [camera guide](camera-3007325.5.md) for the verified binary identity, configuration and single-FAT layout; this result does not establish compatibility for another firmware merely sharing the same model or app version.

The release page provides the following separate packages and their checksums. The backup kit collects stock firmware through an SD hook and does not require installing the runtime.

| Package | Purpose |
| --- | --- |
| `LSCamoflash-1.03.2413-uclibc.tar.gz` | Full runtime with generated card contents and installation scripts. |
| `update-1.03.2413-uclibc.tgz` | Runtime update payload; excludes `HACK/etc` and the user's root crontab. |
| Separate NOR backup kit | Native launcher, dumper, host verifier and instructions; copy only its `card/` contents to the SD root. |
| Checksums, third-party notices and corresponding source | Identify the published files and retain the bundled components' license/source information. |

Local RTSP mode replaces Tuya app operation and requires the camera-specific Wi-Fi setup for a cold boot. Its main stream is `rtsp://<camera-ip>:88/videoMain` (H.265), and its substream is `rtsp://<camera-ip>:89/videoSub` (H.264). Add ONVIF manually at `http://<camera-ip>:5000/`; automatic WS-Discovery is not bundled, and this server advertises only the H.264 substream. Toolkit PTZ remains disabled on this exact profile. Long-term memory stability, detailed audio/video synchronization, multiple-client behavior, recording and all Tuya functions remain separate acceptance tests.

The [backup procedure](firmware-backup.md) verified all eight exposed NOR partitions totaling 8 MiB, with matching repeated reads and host checks. It does not establish whole-chip coverage or a working restore. The kit itself does not program flash, but stock startup can change persistent configuration before calling the SD hook. Backups and raw logs can contain credentials and must remain private; they are not release assets. Issues #4 and #10 still require their exact stock binaries and device tests; see the [issue disposition](integration.md#open-issue-disposition).

## Legacy upstream notes

The following historical upstream notes are retained for reference. They are not compatibility claims for every fork profile, and upstream download packages do not contain this fork's changes. Current setup and device evidence are in the [firmware backup procedure](firmware-backup.md), [3007325.5 camera guide](camera-3007325.5.md) and [integration notes](integration.md).

The SD runtime does not establish that camera configuration remains untouched. On the verified 3007325.5 firmware, stock startup copies the AP marker to persistent `/etc/config/hostapd.conf` before invoking the SD hook and performs its normal configuration maintenance. Removing the card stops the SD hook but does not undo those persistent effects or establish normal-mode recovery; verify app, Wi-Fi and recording behavior separately.

### 📌 Highlights

- **SD-based runtime**. Removing the card stops its hook; persistent stock configuration effects require separate checks.
- **New Webinterface** with Stream-Control, PTZ, Cam-Settings, Reboot and optional HLS-Player.
- **Autopatch** for anyka to enable RTSP Streams on Port 554 (/main_ch), supporting most LSC models.
- **Telnet server** available on port 24 by default.
- **Web server** running on port 8080 by default.
- **FTP server** with direct access to the SD card.
- **ONVIF server** for network camera integration and optional PTZ control.
- **Cron service** for scheduled tasks.
- **Customizable WiFi settings** via configuration file (not possible with default TUYA firmware).
- **BusyBox enhanced** with additional useful tools.
- **TCPDump and extended shell tools** included for debugging and analysis.
- **FFMPEG** e.g. to extract snapshots from live stream or transcode cameras H264 stream files.
- **Mosquitto Server, Pub and Sub**
- **Radare2** debugging suite.
- **MSMTP Server and Client** e.g. for sending status mails or ip address of the camera.
- **UPNPC Support** e.g. for opening ports on UPNP enabled routers and firewalls.
- **Sqlite3 and Sqlcipher** e.g. used for the WebUI authorization. 
- **joe as editor** with syntax highlighting.
- **PHP 8.4** usable within the cli or the webserver.
- **Python 3.13** also usable within the cli or the webserver.
- **CGI** for the internal webserver supports php, python and shell scripts. 

---

### 🔧 Changes & New Features

#### 🛠 System Services

- Now, LSCamoflash supports autopatch, which automatically detects anyka version and patches it for RTSP support.
- Runtime programs are supplied from the SD card; stock startup can still change persistent configuration.
- **Manufacturer update routine disabled**, preventing cloud-based removal of the hack.
- RTSP only mode can be enabled for direct streaming, without cloud.
- **TUYA cloud can be completely blocked** via offline mode.
- Otherwise, the TUYA functionality remains fully operational.

#### 📡 Web Server & Remote Access

- Web server available on **port 8080** with username 'admin' and password 'admin' by default.
- Telnet service runs on **port 24** with username 'root' and password 'LSCamoflash' by default.
- FTP server provides **direct SD card access** with username 'root' and password 'LSCamoflash' by default.
- **chpasswd** as replacement for passwd to make passwordchanges permanent, otherwise it gets overwritten after reboot.

#### 🔄 Update & SD Card Persistence

- The **hack is not removed** even after formatting via the TUYA app (just wait **one minute** post-formatting).
- The SD card **can be formatted without affecting modifications**.

---

### 🔜 Planned Features for Future Versions

- **Building own kernel** to add swap and z-ram support and also ext2 modules.
- **Optimized monitoring script** for quicker system checks.
- **Anti-Tampering** support to detect foreign SD cards.
- **Additional MQTT and ONVIF enhancements** for improved integration.

---

### 📥 Download & Installation

The legacy installation below uses two FAT32 partitions, with the runtime on `mmcblk0p2`. The single-FAT layout in the [3007325.5 guide](camera-3007325.5.md#build-and-stage) has physically verified Wi-Fi, web UI and local audio/video streaming on the exact documented firmware. Other revisions and layouts still require their own device checks. The separate verified backup kit does not require runtime installation or destructive partitioning.

#### Partition Requirements:

- **Partition 1 (`mmcblk0p1`)**: At least **14GB**, formatted as **FAT32**.
  - Stores video recordings as well as `hostapd` and `_ht_ap_mode.conf`.

- **Partition 2 (`mmcblk0p2`)**: At least **1GB**, formatted as **FAT32**.
  - Stores the hack files.

After building this fork, `SOURCE/build/` contains the generated card contents, including the native launcher, static BusyBox and compiled services:

- `mmcblk0p1/` - Contents for the first partition.
- `mmcblk0p2/` - Contents for the second partition.

### Automatic Installation (Recommended)

To simplify partitioning and file copying, installation scripts are provided for Windows and Linux:

- **Windows**: From `SOURCE/build/` or an unpacked full release root, run `install.ps1` in powershell as Administrator.
  ```powershell
  Set-ExecutionPolicy Bypass -Scope Process -Force
  .\install.ps1
  Set-ExecutionPolicy Default -Scope Process -Force
  ```

- **Linux**: From `SOURCE/build/` or an unpacked full release root, run `install.sh` with root privileges:
  ```bash
  sudo ./install.sh
  ```

These scripts will automatically handle partitioning and copying the files to the SD card.

---

### Manual SD Card Partitioning

If the scripts cannot be used, the SD card can be partitioned manually.

The copy paths below assume commands run from the source repository root after a successful build. An unpacked full release instead has `mmcblk0p1/` and `mmcblk0p2/` directly at its root.

#### **Windows (Using Diskpart)**

1. **Insert the SD card into the computer**.
2. **Open the command prompt as Administrator** (`Win + R`, type `cmd`, then press `Ctrl + Shift + Enter`).
3. **Start Diskpart**:
   ```
   diskpart
   ```
4. **List available disks**:
   ```
   list disk
   ```
5. **Select the SD card** (replace `X` with the correct disk number):
   ```
   select disk X
   ```
6. **Clean the SD card**:
   ```
   clean
   ```
7. **Create the first partition (`mmcblk0p1`)**:
   ```
   create partition primary
   shrink desired=1024
   format fs=fat32 quick
   assign letter=E
   ```
8. **Create the second partition (`mmcblk0p2`)**:
   ```
   create partition primary
   format fs=fat32 quick
   assign letter=F
   ```
9. **Exit Diskpart**:
   ```
   exit
   ```
10. **Copy files**:
    - Copy the contents of `SOURCE/build/mmcblk0p1/` to the **first partition** (`mmcblk0p1`).
    - Copy the contents of `SOURCE/build/mmcblk0p2/` to the **second partition** (`mmcblk0p2`).

#### **Linux (Manual Method)**

1. **Identify the SD card**:
   ```bash
   lsblk
   ```
   Example output:
   ```
   mmcblk0      14.9G
   ├─mmcblk0p1  14G  
   └─mmcblk0p2  1G  
   ```
2. **Unmount the SD card (if mounted)**:
   ```bash
   sudo umount /dev/mmcblk0p1
   sudo umount /dev/mmcblk0p2
   ```
3. **Start `fdisk` to partition the SD card**:
   ```bash
   sudo fdisk /dev/mmcblk0
   ```
   - Press `d` to delete existing partitions.
   - Press `n` to create a new partition:
     - Select `p` for primary partition.
     - Partition **1**, size **+14G**.
     - Press `t`, then enter `b` for FAT32.
   - Press `n` again to create the second partition:
     - Partition **2**, size **+1G** (or more).
     - Press `t`, select partition **2**, enter `b` for FAT32.
   - Press `w` to save changes and exit `fdisk`.
4. **Format the partitions**:
   ```bash
   sudo mkfs.vfat -F32 /dev/mmcblk0p1
   sudo mkfs.vfat -F32 /dev/mmcblk0p2
   ```
5. **Copy files**:
   ```bash
   sudo mount /dev/mmcblk0p1 /mnt/mmcblk0p1
   sudo mount /dev/mmcblk0p2 /mnt/mmcblk0p2
   
   sudo cp -a SOURCE/build/mmcblk0p1/. /mnt/mmcblk0p1/
   sudo cp -a SOURCE/build/mmcblk0p2/. /mnt/mmcblk0p2/
   
   sudo umount /mnt/mmcblk0p1
   sudo umount /mnt/mmcblk0p2
   ```

---

The **recommended method** is the **automatic installation with `install.ps1` (Windows) or `install.sh` (Linux)**, as it avoids errors and simplifies the process.

---

🚀 Enjoy LSCamoflash! If you have feedback or find any issues, feel free to create an issue on GitHub. 😊
