# Install the separate YYOS management kit

This guide is only for the confirmed LSC 3225722 / SZ F26312 / V14.1.5 / AK3918AV130 camera with stock `/appfs/bin/yy_cam` SHA256 `d76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7`. It does not install the Anyka overlay or Fullhan runtime. Establish the exact identity and preserve a verified firmware/configuration backup first; see the matching public camera and backup guides. The installer never formats, partitions, mounts, writes raw disks/MTD, changes firmware configuration or contacts a camera.

The YYOS release is pending; v2.00.0000 does not contain this package. Build from current source using the commands below. When a release supplies `LSCamoflash-VERSION-yyos.tar.gz`, verify its exact SHA256 against that release's `SHA256SUMS` before extracting it on the host. The archive contains the fixed `LSCamoflash-yyos-kit/` host folder. Its `card/` tree contains a normal YYOS background hook, lightweight HTTP management, optional native controls and an optional isolated SSH runtime. The public package contains no web credentials, local control key, SSH owner/host keys or SSH enable marker. It cannot start HTTP or SSH without private provisioning. No native RTSP/ONVIF configuration is performed during installation.

## Build from current source

Use the dependencies in [Building and testing](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/building.md), including the project's hydrated ARM toolchain, static BusyBox and QEMU. Download the pinned musl 1.2.6 and Dropbear 2026.94 archives from their official project sites; the builders verify the exact hashes before extraction. Run from the repository root into new output directories:

```sh
make -C SOURCE backup-kit
python3 tools/yyos/build-musl.py --source /private/musl-1.2.6.tar.gz --output /private/yyos-musl
python3 tools/yyos/build-dropbear.py --source /private/dropbear-2026.94.tar.bz2 \
  --musl-build /private/yyos-musl --output /private/yyos-dropbear
python3 tools/yyos/build-controls.py --source /private/dropbear-2026.94.tar.bz2 \
  --musl-build /private/yyos-musl --output /private/yyos-controls
python3 tools/yyos/build-kit.py --output /private/yyos-management \
  --busybox SOURCE/backup-kit/card/busybox --qemu /usr/bin/qemu-arm \
  --controls-build /private/yyos-controls --controls-musl-build /private/yyos-musl
python3 tools/yyos/build-ssh-kit.py --credential-free \
  --dropbear /private/yyos-dropbear/bin/dropbear \
  --dropbear-source /private/yyos-dropbear/dropbear-2026.94.tar.bz2 \
  --dropbear-provenance /private/yyos-dropbear/provenance.json \
  --musl-build /private/yyos-musl --busybox SOURCE/backup-kit/card/busybox \
  --qemu /usr/bin/qemu-arm --output /private/yyos-ssh
python3 tools/yyos/package-kit.py --management-kit /private/yyos-management \
  --ssh-kit /private/yyos-ssh --dropbear-build /private/yyos-dropbear \
  --musl-build /private/yyos-musl --controls-build /private/yyos-controls \
  --output /private/LSCamoflash-yyos-kit
```

These commands assemble public code and provenance without accessing the camera or card. Use the combined output as `LSCamoflash-yyos-kit` in the following steps. Controls are inactive until their optional private key is provisioned; see [Controls](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/yyos-controls.md). Omit both controls options from the management builder and `--controls-build` from the packager for a status/recordings-only kit.

## Provision privately on the host

Run the packaged installer with Python3. Provisioning needs host OpenSSL for the web password hash; optional SSH key generation needs `python3-cryptography`. Choose an absent or empty private output directory outside the extracted public package:

```sh
python3 LSCamoflash-yyos-kit/install-kit.py provision \
  --kit LSCamoflash-yyos-kit \
  --output /private/yyos-site-kit \
  --generate-ssh-keys
```

The command prompts twice for a web password without echoing it. For unattended use, supply `--password-file /private/web-password.txt` containing one password line of at least eight bytes; the password is passed to OpenSSL through standard input and is never put in a command argument or build log. The default username is `admin`; `--username` changes it. Only its salted hash enters `card/LSCamoflash-yyos/httpd.conf`, outside the web root and public checksum inventory.

SSH is optional. Omit `--generate-ssh-keys` for HTTP-only use, or provide `--client-public-key /private/owner.pub --host-key /private/dropbear-host-key` instead. The public key must be one bare Ed25519 key without a comment/options; the host key must use native Dropbear's 83-byte Ed25519 format. Generated `owner_ssh_ed25519` and its public half are stored at the private host kit's top level, outside `card/`; the unencrypted private client key is mode 0600 and must stay on the host. The separate host private key and explicit `ssh.enabled` marker enter only the nested SSH runtime. Protect the private output and never publish or commit it. Private kit checksums still cover public code and licenses; authentication files are validated separately.

The kit's `host-key.pub` and `host-key-fingerprint.txt` let you pin SSH before the first connection. Create a dedicated known_hosts entry for `[CAMERA_IP]:2222` using that trusted host public key; keep strict host-key checking enabled. The root SD filename `telnetd` remains a bounded native launcher, not a Telnet shell server.

To enable the optional Controls tab, add `--native-credentials /private/yyos-native-credentials.json` to provisioning, using this camera's exact-profile file recovered from its verified backup. Only its 16-byte local key enters `LSCamoflash-yyos/native-control.key`, outside the served directory. No local key is included by default. The [controls guide](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/yyos-controls.md) explains the switches, short PTZ steps and their safeguards; streaming enablement remains a separate host operation.

## Review and install on the existing card

Power the camera off, retrieve its already compatible FAT32 card and mount it normally on a Linux host. Preserve another private host copy of important recordings, backups and configuration before installation. The installer requires an exact writable VFAT partition on a removable disk, a FAT UUID and matching visible filesystem/block-device identity. A whole-device FAT layout, read-only card, ambiguous mount, internal disk, symlink path or unknown boot/debug/update marker is refused. It provides no override for these checks.

Identify the actual mount, block partition and UUID with the host's disk utility or `findmnt`/`lsblk`. Substitute those exact values below; the paths and UUID are placeholders, not a device-selection suggestion:

```sh
python3 LSCamoflash-yyos-kit/install-kit.py plan \
  --kit /private/yyos-site-kit \
  --mount /run/media/USER/CARD_UUID \
  --device /dev/READER_PARTITION \
  --uuid CARD_UUID

python3 LSCamoflash-yyos-kit/install-kit.py install \
  --kit /private/yyos-site-kit \
  --mount /run/media/USER/CARD_UUID \
  --device /dev/READER_PARTITION \
  --uuid CARD_UUID
```

`plan` performs validation without changing the card. `install` repeats validation under a host lock, disarms any existing normal marker first, preserves recognized previous root files/runtime directories/authentication/logs under a unique `diagnostic-archive/yyos-install-*` directory, stages and flushes new files, checks every public checksum and private-file readback, then arms the empty root `yy_telnet_start` marker last. Recordings, existing diagnostic archives and unrelated card files are left in place. A failed write or final flush retains the preserved files and leaves the normal marker disabled; inspect the failure and archive rather than repeatedly retrying or formatting.

Recognized upgrades preserve existing web authentication by default; use `--replace-web-auth` only when intentionally replacing it with the privately provisioned account. Existing SSH owner/host keys and their enabled/disabled state are preserved, so an upgrade does not silently change a trusted host key or disable existing remote access. Unknown, partial, recovery/debug or independently modified boot compositions require separate review and are refused. Keep all preserved archives until the next normal boot has been accepted.

Flush and safely eject the card using the host, return it to the powered-off camera and boot normally. Confirm the vendor app stays online, HTTP 8080 rejects missing/wrong credentials and accepts your account, and the dashboard reports the stock application running. If SSH was provisioned, connect as root on TCP2222 with the owner client key, a pinned host key and strict checking; verify wrong-key refusal, memory use and normal cold-boot behavior. SSH grants an unrestricted root shell, unlike the read-only portions of the dashboard. Native media configuration and other writes remain separately guarded; first establish SSH before an authorized native-media trial.

## Later maintenance

A later public kit can be planned/installed without reprovisioning when recognized existing authentication is retained. Once SSH itself has been accepted, ordinary SD logs/files can be transferred through SSH command input/output without repeatedly retrieving the card. Keep rollback copies and use checksum/readback, file fsync, atomic same-directory replacement and directory fsync for reviewed updates. Never edit firmware-monitored `yy_debug.ini` live or treat SSH as a bypass for firmware/native configuration safeguards. Recovery after a network or boot failure can still require a powered-off physical card procedure.

The dedicated package includes source/build provenance and notices for its static BusyBox, Dropbear and musl components; project code is MIT, but the entire package is not solely MIT-licensed. Retain all component source/configuration and license notices when redistributing it. Installer fixture success establishes host-side behavior on synthetic files; it does not establish installation acceptance on an additional camera or firmware revision.

The package's `RECORDINGS.md` explains authenticated raw recording downloads and the included host-only converter; the source guide is `docs/yyos-recordings.md`. Private provisioning must use a host filesystem that actually enforces current-user-owned mode0700 directories and mode 0600 files. FAT is suitable for the card payload, but is refused as the private host output. Password and native Dropbear host-key input files must be owned by the invoking user with mode 0600 before provisioning.
