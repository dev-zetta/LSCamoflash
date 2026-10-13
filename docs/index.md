---
layout: default
---

# 👁️‍🗨️ LSCamoflash

For this fork's current evidence and setup, read the [verified NOR backup procedure](./firmware-backup.md), [experimental 3007325.5 runtime guide](./camera-3007325.5.md) and [integration notes](./integration.md). The documented camera has accepted firmware backup, network/web access, both local RTSP video streams and manual ONVIF substream selection. Local RTSP audio is currently unavailable; microphone hardware, custom PTZ and long-term operation remain separate device tests. Automatic ONVIF discovery is not bundled. The release notes below describe legacy upstream features, and upstream release downloads do not include this fork's changes.

LSCamoflash is a modified firmware package for LSC Tuya based IP cameras that adds powerful features like local-only operation, cloud-free RTSP streaming, camera control via web UI, and more.

🚀 Now with PHP & Python CLI/Web support, FFMPEG integration, ONVIF PTZ control, SD card auto-recovery and optional `radare2` for advanced tinkering.

## 🔧 Highlights

- WebUI with settings and controls (incl. camera restart)
- Cloud-independent streaming (RTSP, HLS, FLV)
- Anyka IPC auto-patching for RTSP
- ONVIF PTZ support
- Automatic SD-card reinitialization after format
- Configurable WLAN (independent from Tuya)
- CLI/Web integration via PHP & Python
- Optional `radare2` installation

## 📦 Download Latest Release Version

👉 [Download Latest Release](https://github.com/Bunkerschild/LSCamoflash/releases/latest)

## 📚 Full Release Notes

See the full [Release Notes](./release.md)

## 🛠 Latest Autobuild

⚠️ This is the latest development build. It is not tested as thoroughly as stable releases.

👉 [Download LSCamoflash Autobuild](./autobuild/LSCamoflash-Autobuild.tar.gz)

👉 [Download Update Package](./autobuild/update-autobuild.tgz)
