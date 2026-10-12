# LSCamoflash Release

These are legacy upstream release notes, not a statement of compatibility or physical acceptance for every camera supported by this fork. Follow the current [firmware backup procedure](firmware-backup.md), [3007325.5 camera guide](camera-3007325.5.md) and [integration notes](integration.md) for verified results, experimental features and remaining device tests. Upstream release packages do not include this fork's changes.

The SD runtime does not establish that camera configuration remains untouched. On the verified 3007325.5 firmware, stock startup copies the AP marker to persistent `/etc/config/hostapd.conf` before invoking the SD hook and performs its normal configuration maintenance. Removing the card stops the SD hook but does not undo those persistent effects or establish normal-mode recovery; verify app, Wi-Fi and recording behavior separately.

## 📌 Highlights
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

## 🔧 Changes & New Features

### 🛠 System Services
- Now, LSCamoflash supports autopatch, which automatically detects anyka version and patches it for RTSP support.
- Runtime programs are supplied from the SD card; stock startup can still change persistent configuration.
- **Manufacturer update routine disabled**, preventing cloud-based removal of the hack.
- RTSP only mode can be enabled for direct streaming, without cloud.
- **TUYA cloud can be completely blocked** via offline mode.
- Otherwise, the TUYA functionality remains fully operational.

### 📡 Web Server & Remote Access
- Web server available on **port 8080** with username 'admin' and password 'admin' by default.
- Telnet service runs on **port 24** with username 'root' and password 'LSCamoflash' by default.
- FTP server provides **direct SD card access** with username 'root' and password 'LSCamoflash' by default.
- **chpasswd** as replacement for passwd to make passwordchanges permanent, otherwise it gets overwritten after reboot.

### 🔄 Update & SD Card Persistence
- The **hack is not removed** even after formatting via the TUYA app (just wait **one minute** post-formatting).
- The SD card **can be formatted without affecting modifications**.

---

## 🔜 Planned Features for Future Versions
- **Building own kernel** to add swap and z-ram support and also ext2 modules.
- **Optimized monitoring script** for quicker system checks.
- **Anti-Tampering** support to detect foreign SD cards.
- **Additional MQTT and ONVIF enhancements** for improved integration.

---

## 📥 Download & Installation

The legacy installation below uses two FAT32 partitions, with the runtime on `mmcblk0p2`. This fork also implements an experimental single-FAT runtime layout described in the [3007325.5 guide](camera-3007325.5.md#build-and-stage); its physical runtime acceptance remains pending. The separate verified backup kit does not require runtime installation or destructive partitioning.

### Partition Requirements:
- **Partition 1 (`mmcblk0p1`)**: At least **14GB**, formatted as **FAT32**.
  - Stores video recordings as well as `hostapd` and `_ht_ap_mode.conf`.
- **Partition 2 (`mmcblk0p2`)**: At least **1GB**, formatted as **FAT32**.
  - Stores the hack files.

After building this fork, `SOURCE/build/` contains the generated card contents, including the native launcher, static BusyBox and compiled services:
- `mmcblk0p1/` - Contents for the first partition.
- `mmcblk0p2/` - Contents for the second partition.

## Automatic Installation (Recommended)
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

## Manual SD Card Partitioning
If the scripts cannot be used, the SD card can be partitioned manually.

The copy paths below assume commands run from the source repository root after a successful build. An unpacked full release instead has `mmcblk0p1/` and `mmcblk0p2/` directly at its root.

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
    - Copy the contents of `SOURCE/build/mmcblk0p1/` to the **first partition** (`mmcblk0p1`).
    - Copy the contents of `SOURCE/build/mmcblk0p2/` to the **second partition** (`mmcblk0p2`).

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
   
   sudo cp -a SOURCE/build/mmcblk0p1/. /mnt/mmcblk0p1/
   sudo cp -a SOURCE/build/mmcblk0p2/. /mnt/mmcblk0p2/
   
   sudo umount /mnt/mmcblk0p1
   sudo umount /mnt/mmcblk0p2
   ```

---

The **recommended method** is the **automatic installation with `install.ps1` (Windows) or `install.sh` (Linux)**, as it avoids errors and simplifies the process.

---

🚀 Enjoy LSCamoflash! If you have feedback or find any issues, feel free to create an issue on GitHub. 😊
