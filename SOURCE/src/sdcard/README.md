# LSCamoflash - SD Card Setup Guide

## Introduction

The traditional LSCamoflash layout uses two FAT32 partitions, with the runtime on the second partition (`mmcblk0p2`). This fork also implements a single FAT32 card layout with `HACK/` at its root; see the [3007325.5 camera notes](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-3007325.5.md) for its current acceptance status. Always copy built card contents, which include the native `hostapd`, `busybox` and `bootstrap.sh` boot files. For a firmware backup alone, use the separate [backup procedure](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/firmware-backup.md); its verified path does not require this runtime installation or destructive partitioning.

Run the commands below from the generated `SOURCE/build/` directory or an unpacked full release root. The `mmcblk0p1/` and `mmcblk0p2/` copy paths are relative to that directory.

For the exact 3007325.5 profile, leave `local_rtsp_only` and `wifi_config_override` unset to test stock-managed Tuya pairing. Local RTSP requires the separate explicit Wi-Fi configuration in the camera guide. Three physical runtime attempts failed to provide app access or a DHCP lease; pairing without the SD card worked. The second card matched all 745 built payload files and init returned status 0 in roughly one minute, with no observed reboot. During the third test, the stock application PID persisted and the camera tracked motion, while WLAN disappeared after init and WPA appeared only transiently. Stock logging reported an all-zero MAC value; this does not establish a change to the stored hardware MAC.

The third test exposed a concrete overlay defect: init removed the stock PATH aliases `/sbin/ifconfig` and `/sbin/udhcpc`. The recovered stock BusyBox ash returned status 127 for both bare commands when their aliases were absent; it does not supply an applet fallback. The exact profile now retains those stock aliases, while other profiles keep their previous behavior. The fourth test below verifies network recovery after this correction.

The fourth test confirmed normal-mode network recovery after this correction: WPA completed, `wlan0` acquired an IPv4 address and default route, and the user logged into the web UI on port 8080. Direct local RTSP and ONVIF still require the separately configured local mode and a camera streaming test. The link-generation buttons do not switch firmware mode; local mode replaces Tuya app access and needs explicit Wi-Fi configuration for a cold boot.

In local mode, the exact profile uses `rtsp://<camera-ip>:88/videoMain` for H.265 main video and `rtsp://<camera-ip>:89/videoSub` for H.264 sub video. Its ONVIF service address is `http://<camera-ip>:5000/`, advertising the H.264 substream after its listener starts. The web UI returns this HTTP service address rather than a custom `onvif://` URI. The IP may change through DHCP. Live tests decoded video and 8 kHz mono PCMA audio from both streams over TCP and UDP, and the user confirmed audible microphone sound. ONVIF Device/Media SOAP requests and the H.264 substream URI were also verified. Add the camera manually at port 5000: automatic WS-Discovery requires a separate daemon that this build does not package. Long-term operation and detailed audio/video synchronization remain unverified.

The first local-mode camera test opened both RTSP ports but neither answered protocol requests. This exact stock binary skips the callbacks that forward video and encoded audio and service those requests. The build now includes `HACK/lib/libcamoflash_rtsp.so`, required by its local-mode launcher after the full stock SHA-256 check. The helper installs video and encoded audio forwarding after both servers and sessions are ready, and drains both through a shared guard before stock shutdown frees them. It reuses the existing G.711 A-law encoder and leaves the raw Tuya audio callback unset. Upgrade the launcher and helper together using the generated package; the helper is scoped to this firmware's local-mode application process. See the camera guide for the binary evidence and remaining physical acceptance.

The RAM bar now uses the kernel's `MemAvailable` estimate rather than treating all cache as used memory, with an explicitly labelled fallback if that counter is unavailable. Hover over its label for the overlapping cache/buffer/shared-memory breakdown. A high value on the old bar alone did not establish memory pressure. Opt-in handoff logs include memory counters and selected process footprints for checking actual headroom after the next boot.

First initialization can take several minutes to create backups and the overlay, and setup changes can request a reboot after a 60-second delay. Init has a 600-second deadline with a five-second forced-kill grace period; the first services readiness wait is limited to 45 nominal seconds. The init deadline starts after station reload, staged updates and custom pre-init hooks, and does not guarantee termination of stuck kernel I/O. These bounds are software checks, not physical acceptance.

For a failed boot, power off before removing the card and preserve `HACK/var/log/boot.log`, `init.log`, `init.err`, their `*.previous.*` counterparts and `services-startup.log` before retrying or overwriting the card. Service startup output is capped at 64 KiB; boot and init logs retain one previous boot without a byte cap. The service log reader now writes short reads immediately with `dd iflag=count_bytes`, fixing the previous `head` buffering gap when background daemons kept a pipe writer open. That diagnostic fix does not establish the cause of the offline state.

To opt in to stock logging and post-init handoff diagnostics, place an **empty `_ht_get_log.conf` on the boot card root**, beside `hostapd` and `_ht_ap_mode.conf`. Use partition 1 for the traditional layout, or the shared root for single FAT. Stock firmware copies the flag to `/tmp`, keeps `/mnt` mounted and writes `ht_log/` on that boot card; its 5 MB rotation threshold is not a total storage cap. After init returns status 0, a bounded background sampler records filtered process/memory/network/WPA states at nominal 0/5/15/30/60-second offsets in runtime-root `HACK/var/log/handoff.log`, retaining `handoff.previous.log`. Opt-in `wrapper-status.log` and `wrapper-status.previous.log` record wrapper phases with the same exec PID; `exec-stock` means an exec attempt is about to occur, not that the stock application successfully started. The third physical test exercised these diagnostics and the fourth confirmed normal-mode network recovery; local-mode startup and streaming still require a camera test.

Preserve private host copies of these logs, boot-root `ht_log/`, `HACK/backup/` and generated configuration before another attempt. Raw stock logs may include credentials and device/account identifiers; review and redact evidence before sharing. Remove `_ht_get_log.conf` from the boot root and cold-boot to disable opt-in diagnostics. See the [camera diagnostics guide](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-3007325.5.md#first-boot-and-diagnostics) for exact file names and best-effort failure cleanup; no full rollback is guaranteed.

### Partition Requirements:
- **Partition 1 (`mmcblk0p1`)**: At least **14GB**, formatted as **FAT32**.
  - Stores video recordings as well as `hostapd` and `_ht_ap_mode.conf`.
- **Partition 2 (`mmcblk0p2`)**: At least **1GB**, formatted as **FAT32**.
  - Stores the hack files.

The generated build directory or unpacked full release root contains:
- `mmcblk0p1/` - Contents for the first partition.
- `mmcblk0p2/` - Contents for the second partition.

## SD Card Preparation (available only for Linux)
Before installing LSCamoflash, it is recommended to prepare the SD card using the `disk_prepare.sh` script. This utility:

- **Erases all data** on the SD card irreversibly
- **Performs read/write tests** to detect card damage and measure performance
- **Rates the card's suitability** for use with the cameras based on capacity and read/write speeds (using school grades)
- **Performs secure clearing** using `blkdiscard` and FAT32 formatting to remove any residual data that could slow down read/write access
- **Helps restore** partially damaged cards to a working state

### Capacity Requirements
- **Recommended**: At least **32 GB** SD card
- **Maximum**: **128 GB** SD card

⚠️ **Warning**: Running this script will **permanently delete all data** on the selected SD card. Ensure you have selected the correct device.

### Basic Usage
To run the script on Linux:
```bash
chmod +x ./disk_prepare.sh
sudo ./disk_prepare.sh
```

### Advanced Command-Line Options (For Experts)
The script supports the following CLI switches:

```bash
Usage:
  disk_prepare.sh                        # interactive disk selection + confirmation
  disk_prepare.sh -D /dev/mmcblk0        # non-interactive with confirmation
  disk_prepare.sh -D /dev/mmcblk0 -F     # skip confirmation prompt
  disk_prepare.sh -D /dev/mmcblk0 -f     # faster test (count=128)
  disk_prepare.sh -D /dev/mmcblk0 -u     # ultra-fast test (count=64)
```

**Options:**
- `-D, --disk <device>`: Select disk non-interactively (e.g., `/dev/mmcblk0`, `/dev/sdb`)
- `-F, --force`: Skip the destructive confirmation prompt (use with caution)
- `-f, --fast`: Faster test with reduced write operations. Only applicable for SD cards >= 8 GiB. Trades thoroughness for speed.
- `-u, --ultra`: Ultra-fast test with minimal write operations. Only applicable for SD cards >= 8 GiB. Provides the quickest result but least precise speed measurement.
- `-h, --help`: Display the help message

**Speed vs. Accuracy**: The `--fast` and `--ultra` options are only recommended when you need results quickly. The standard mode (default) provides the most accurate performance measurement. Faster modes reduce the amount of data written to the card and therefore provide less precise speed measurements.

## Automatic Installation (Recommended)
To simplify partitioning and file copying, installation scripts are provided for Windows and Linux:

- **Windows**: Run `install.ps1` in powershell as Administrator.
  ```powershell
  Set-ExecutionPolicy Bypass -Scope Process -Force
  .\install.ps1
  Set-ExecutionPolicy Default -Scope Process -Force
  ```
- **Linux**: Run `install.sh` with root privileges:
  ```bash
  chmod +x ./install.sh
  sudo ./install.sh
  ```

These scripts will automatically handle partitioning and copying the files to the SD card.

---

## Manual SD Card Partitioning
If the scripts cannot be used, the SD card can be partitioned manually.

### **Windows (Using Diskpart)**

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
    - Copy the contents of `./mmcblk0p1/` to the **first partition** (`mmcblk0p1`).
    - Copy the contents of `./mmcblk0p2/` to the **second partition** (`mmcblk0p2`).

### **Linux (Manual Method)**

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
   
   sudo cp -a ./mmcblk0p1/. /mnt/mmcblk0p1/
   sudo cp -a ./mmcblk0p2/. /mnt/mmcblk0p2/
   
   sudo umount /mnt/mmcblk0p1
   sudo umount /mnt/mmcblk0p2
   ```

---

The **recommended method** is the **automatic installation with `install.ps1` (Windows) or `install.sh` (Linux)**, as it avoids errors and simplifies the process.
