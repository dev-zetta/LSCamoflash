# Install LSCamoflash

This guide covers the **Anyka runtime**. Fullhan SZ B22705 / 7.6.23 uses the separate [Fullhan download and setup](camera-sz-b22705.md#prepare-the-private-payload), without these installers or card layouts. Use a published platform-specific package for installation. Building from source is optional and covered in [Building and testing](building.md). Check the [compatibility notes](integration.md) and the guide for your exact camera first; the verified [3007325.5 / SI L25502 profile](camera-3007325.5.md) has different streaming and Wi-Fi requirements from older cameras.

## Before you start

You need a compatible camera, a spare microSD card, a card reader and a computer that can read FAT32. Save the card's recordings and your camera configuration before changing anything. Where supported, make and verify a [stock firmware backup](firmware-backup.md) first. The backup kit is separate from the runtime installation.

The partitioning scripts erase the entire selected disk. Removing the SD card stops its runtime hook, but stock startup may already have changed persistent configuration; it does not guarantee a complete rollback.

## Choose a download

Open [v2.00.0000](https://github.com/dev-zetta/LSCamoflash/releases/tag/v2.00.0000) in this fork and expand **Assets**.

| File | When to use it |
| --- | --- |
| `LSCamoflash-2.00.0000-uclibc.tar.gz` | A new **Anyka** runtime installation. Contains generated card files and installers. |
| `LSCamoflash-2.00.0000-fullhan.tar.gz` | Separate **Fullhan** management folder, private credentials and manual startup. Follow its [camera guide](camera-sz-b22705.md#prepare-the-private-payload). |
| `update-2.00.0000-uclibc.tgz` | Updating an existing **Anyka** runtime while retaining its configuration. See [updates](configuration.md#updates). |
| `LSCamoflash-<version>-backup-kit.tar.gz` | Backing up stock firmware without installing the runtime. See the [backup guide](firmware-backup.md). |
| `SHA256SUMS` | Verifying downloaded files. |
| `LSCamoflash-<version>-source.tar.gz` | Developer source and declared build inputs; not a camera installation. |

The automatically generated GitHub **Source code** ZIP and TAR downloads also require a build. Use the full runtime asset when preparing a card.

Download the full runtime and `SHA256SUMS` into the same directory. On Linux, check the files you downloaded:

```sh
sha256sum --ignore-missing --check SHA256SUMS
```

Confirm that the runtime archive is listed as `OK`. On Windows, use `Get-FileHash -Algorithm SHA256 .\LSCamoflash-<version>-uclibc.tar.gz` and compare the result with its entry in `SHA256SUMS`.

For Anyka, extract the full `-uclibc.tar.gz` runtime archive into a new folder. Its top level contains `mmcblk0p1/`, `mmcblk0p2/`, `install.sh`, `install.ps1` and `disk_prepare.sh`. The paths below refer to that extracted folder.

## Choose the SD card layout

| Layout | How it works | When to use it |
| --- | --- | --- |
| Single FAT32 | Boot files and `HACK/` share the card root. | The verified 3007325.5 setup; follow its [camera guide](camera-3007325.5.md#build-and-stage). |
| Two FAT32 partitions | Boot files are on partition 1; `HACK/` is on partition 2. | Traditional LSCamoflash installation, when supported by your camera. |

Use the built or released files. Copying `SOURCE/src/sdcard/` directly omits the compiled launcher, BusyBox and camera services.

### Single FAT32 card

Start with a clean FAT32 card. With the camera off and the card mounted on your computer:

1. Copy the **contents** of `mmcblk0p2/` to the card root, so the card contains `HACK/` directly.
2. Copy the **contents** of `mmcblk0p1/` to the same root, including `hostapd`, `busybox`, `bootstrap.sh` and the supplied markers.
3. Configure the mode and Wi-Fi in `HACK/etc/hack_custom.conf` as described in the [3007325.5 camera guide](camera-3007325.5.md#stock-tuya-or-local-rtsp).

Do not copy the enclosing `mmcblk0p1` and `mmcblk0p2` directory names onto the card. Keep the backup kit on a separate card or archive its root payload first: it also uses the name `hostapd`.

### Two-partition installer

The Linux installer creates a 1 GiB FAT32 second partition and uses the remaining aligned space for the first FAT32 partition. Its card-size check reserves at least 64 MiB for partition 1; allow additional capacity for recordings and your camera's requirements. It lists removable devices, asks for the whole device name twice and then formats and copies the runtime files.

On Debian/Ubuntu, install its host utilities:

```sh
sudo apt-get install dosfstools fdisk parted udev util-linux
```

Run from the extracted full runtime folder:

```sh
sudo bash ./install.sh
```

Select the SD card by its model and size. Close file-manager windows that hold it open before continuing. The installer refuses active layered devices and failed unmounts. Its `--use-sd-config` option attempts to preserve selected settings from an existing card; keep your own complete backup regardless.

The package also includes `install.ps1` for **Windows PowerShell 5.1**, run as Administrator from the extracted folder. It uses DiskPart to erase and repartition the selected removable disk. Windows FAT32 formatting can limit usable partition sizes; if it fails, use a suitable FAT32 formatting method or prepare the card on Linux. The Linux installer has automated fixture coverage; the Windows installer has not been physically validated in this fork.

`disk_prepare.sh` is an optional destructive card benchmark/format utility. It creates a single FAT32 partition and does not copy the runtime. It is unnecessary for an already prepared card, and running it before `install.sh` duplicates formatting. It cannot repair physically failing storage.

## Configure, eject and boot

For stock-managed Tuya mode on the verified 3007325.5 camera, leave `local_rtsp_only` and `wifi_config_override` unset. Local streaming requires the explicit Wi-Fi configuration in its [camera guide](camera-3007325.5.md#stock-tuya-or-local-rtsp); generating a stream link in the web UI does not enable that mode.

Safely eject the card, insert it into the powered-off camera, and power the camera on. First initialization can take several minutes and may restart the camera. Look for its current address in your router's DHCP leases; its IP can change after a mode switch.

Open `http://<camera-ip>:8080/`. A newly created web UI account is **admin / admin**; change it through the **Password** page. Shell and FTP accounts are separate; see [passwords and services](configuration.md#passwords-and-services).

If the camera stays offline, power it off before retrieving the card and preserve the logs. Follow [Troubleshooting](troubleshooting.md) before retrying, resetting or overwriting the installation.
