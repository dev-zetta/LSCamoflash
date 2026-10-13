# LSCamoflash SD card package

This is the full runtime package. Use its generated files to prepare a compatible camera's microSD card; a source checkout still needs to be built.

1. Check your exact camera and firmware against the [compatibility notes](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/integration.md).
2. Back up existing recordings and, where supported, [stock firmware](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/firmware-backup.md).
3. Follow the [installation guide](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/installation.md) to choose the single-FAT or two-partition layout and configure Wi-Fi.
4. Safely eject the card, insert it while the camera is off, and boot. First startup can take several minutes.
5. Open `http://<camera-ip>:8080/`; a fresh web UI uses `admin` / `admin`. Change the password through its **Password** page.

The package contains `mmcblk0p1/`, `mmcblk0p2/`, `install.sh`, `install.ps1` and `disk_prepare.sh`. The partitioning scripts erase the selected disk. An already prepared single-FAT card only needs the correct payload copy; `disk_prepare.sh` is optional and does not install the runtime.

For the tested **LSC Smart PTZ 3007325.5 / SI L25502, firmware 6.2863.125.1348**, follow its [camera guide](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-3007325.5.md). Local RTSP replaces Tuya app operation and requires explicit Wi-Fi configuration. Main video is H.265 on port 88 `/videoMain`; sub video is H.264 on port 89 `/videoSub`. Both carry PCMA microphone audio. Add ONVIF manually at HTTP port 5000; automatic discovery is not bundled and toolkit PTZ is disabled for this profile.

[Configuration and everyday use](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/configuration.md) · [Troubleshooting](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/troubleshooting.md) · [Latest release](https://github.com/dev-zetta/LSCamoflash/releases/latest) · [Report an issue](https://github.com/dev-zetta/LSCamoflash/issues)

[Deutsch](README_DE.md)
