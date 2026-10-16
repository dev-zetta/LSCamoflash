# Optional YYOS SSH administration

This experimental kit adds a separate Ed25519-key-only Dropbear server on TCP2222 for the confirmed LSC3225722 / SZ F26312 / V14.1.5 / AK3918AV130 profile. It is independent of HTTP management, native RTSP/ONVIF and their passwords. Building a kit does not enable SSH, access a camera, write a card or change firmware. Camera SSH authentication, shell access, memory use and normal cold-boot acceptance remain pending until tested on the actual unit.

The runtime requires the exact stock `/appfs/bin/yy_cam` SHA256 `d76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7`, the confirmed CPU, root, one visible writable MMC/VFAT card at `/mnt/sdcard`, its expected `/mnt/sdcard/LSCamoflash-yyos-ssh` folder and an unchanged public payload. It binds one private IPv4 address rather than every interface. It never edits passwords, pairing, Wi-Fi, `/config`, startup scripts or root filesystem files, and never launches, kills or restarts `yy_cam`.

SSH grants a root shell to the owner of the authorized private client key. Commands entered through that shell can change the camera; the read-only HTTP dashboard's restrictions do not apply to an interactive root shell. Keep access on the trusted local network and protect the client key and private host-built kit. No password login, forwarding, agent forwarding, X11 forwarding, SCP program or SFTP subsystem is supplied. SSH command output can be copied to the host without an SFTP server.

## Offline build

Use a static ARMv5TE/ARMv5TEJ soft-float Dropbear2026.94 multicall executable containing the `dropbear` and `dropbearkey` applets, its matching portable build-provenance JSON and the hydrated upstream source archive. Build these with `python3 tools/yyos/build-dropbear.py --source /private/dropbear-2026.94.tar.bz2 --output /private/dropbear-build`; this retains matching source, configuration and relinkable objects. The output executable is `bin/dropbear`, with the copied source archive and `provenance.json` alongside it. The pinned source archive SHA256 is `e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81`. The build options compile out password/PAM authentication, forwarding and SFTP. Static linking avoids loading or replacing the stock uClibc1.0.31 libraries; it does not by itself establish camera acceptance.

Generate the owner's Ed25519 client key and a separate native Dropbear Ed25519 host key on the host. Supply only the client's public half as one bare `ssh-ed25519 BASE64` line without options or a comment. The host key must use Dropbear's native 83-byte format, not an OpenSSH client private-key file. The builder checks format and bounds without printing key contents, and optional ARM926 QEMU checks load the host key with the matching keytool. Retain the private client key on the host; it is never packaged onto the card.

Prepare the project's static BusyBox with `make -C SOURCE backup-kit` if necessary, then build into an absent or empty dedicated private host directory:

```sh
python3 tools/yyos/build-ssh-kit.py \
  --dropbear /private/dropbear-build/bin/dropbear \
  --dropbear-source /private/dropbear-build/dropbear-2026.94.tar.bz2 \
  --dropbear-provenance /private/dropbear-build/provenance.json \
  --client-public-key /private/owner_ed25519.pub \
  --host-key /private/dropbear_ed25519_host_key \
  --busybox SOURCE/backup-kit/card/busybox \
  --qemu /usr/bin/qemu-arm \
  --output /private/yyos-ssh-kit
```

The output contains `card/LSCamoflash-yyos-ssh/`, host instructions/manifests/checksums, `host-key.pub`, its SHA256 fingerprint, and two host boot-composition files. Public runtime checksums cover exactly `common.sh`, `start.sh`, `stop.sh`, `README.md`, `bin/busybox`, `bin/dropbear`, `LICENSE.MIT`, `COPYING.BusyBox`, `COPYING.Dropbear` and `manifest.json`. The site-owned `authorized_keys`, `dropbear_ed25519_host_key` and `ssh.enabled` files are deliberately outside that inventory; the runtime validates them independently. `ssh.enabled` must contain exactly `enabled` followed by one newline. The kit contains the private host key and must not be committed or published.

The runtime copies the validated keys into root-owned mode0700 `/run/lscamoflash-yyos-ssh`, with mode0600 key files, before starting Dropbear. Stock VFAT mode0777 cannot satisfy Dropbear's permissions checks, and a sticky mode1777 `/tmp` parent also fails those checks. The original checks remain enabled. State is held in RAM and records the owned daemon's PID, start time and selected address; startup checks ownership and the listener before reporting success. Stopping refuses unrelated or reused PIDs and refuses active child sessions rather than terminating an owner's shell unexpectedly.

## Guarded staging and connection

Stage only while the camera is powered off and its known card is mounted on the host. Preserve the existing root hook, checksums, marker, management credentials, logs, recordings and all diagnostic/recovery output first. Disarm the root normal marker before changing the hook. Copy the nested SSH folder separately; the existing `LSCamoflash-yyos` HTTP payload remains unchanged. Keep the native SD-root `telnetd` launcher and root BusyBox byte-identical. The filename `telnetd` remains a launcher and does not become a Telnet shell service.

The generated `boot/normal-http-boot.sh` is a byte-identical copy of the existing `tools/yyos/boot.sh`; its proposed SD-root name is `yyos-http-boot.sh`. The new `boot/boot.sh` is the proposed SD-root `dump.sh`: it verifies and executes the old HTTP entry in a separate bounded BusyBox shell, then starts the independently guarded SSH entry in the background with null standard input/output/error and a 150-second startup timeout. A missing or invalid optional SSH folder does not prevent the HTTP attempt. It never executes stock startup. Update root checksums with public files only, verify the entire staged payload and arm the empty normal `yy_telnet_start` marker last, then flush and safely eject. This builder intentionally supplies no automatic card-copying or formatting command.

Never add `yy_debug.ini` for this service or change debug mode live. The stock init script monitors mode changes and can reboot the camera. A previous controlled recovery or trial must be captured and cleaned up while powered off before this normal-hook composition is staged. See [YYOS recovery](yyos-recovery.md) and the [camera guide](camera-3225722.md) for their separate acceptance state.

Before connecting, pin the host public key from the trusted host kit in a dedicated `known_hosts` file for `[CAMERA_IP]:2222`; verify its fingerprint against `host-key-fingerprint.txt`. Use the owner client private key with `ssh -p 2222 -i /private/owner_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/private/camera-known-hosts root@CAMERA_IP`. Do not bypass host-key checks or transmit private keys in URLs or command-line password arguments. Confirm missing/wrong-key refusal, correct-key shell access, unchanged stock PID/app behavior, bounded RAM use and a normal cold boot before calling the deployment accepted.

Remove or archive only the SSH folder's `ssh.enabled` file to prevent SSH startup on the next boot; keep the normal marker if HTTP management is still wanted. After SSH acceptance this ordinary SD file can be removed remotely. A currently running SSH server requires its guarded `stop.sh`, with active sessions closed first. Removing a marker does not terminate an existing daemon.

## Remote maintenance

Once SSH has been verified on the camera, ordinary SD files and logs can be downloaded or uploaded through SSH command input/output without repeated card removal. Keep a rollback copy, validate exact paths and checksums, flush written files, use an atomic same-directory rename and flush the directory before replacing a reviewed payload. Startup changes require their own review and a subsequent normal cold-boot check; do not replace a running executable in place. Avoid live edits to the firmware-monitored `yy_debug.ini`; recovery or an unavailable network can still require a powered-off physical card procedure. Remote access does not bypass the native configuration gate or authorize firmware, raw MTD or factory-reset operations.

## Source and license provenance

`LICENSE.MIT` covers project-authored runtime and packaging code. `COPYING.BusyBox` retains BusyBox GPLv2 terms; `COPYING.Dropbear` includes the pinned upstream and bundled cryptography notices. The manifest binds the static binaries, runtime sources and supplied build options/source hashes. These checks bind the supplied build report to its binary; they are not an independent attestation of an arbitrary caller-supplied binary. Preserve corresponding BusyBox source/configuration and static toolchain runtime licenses, sources and relinkable build materials before redistributing binaries; see [third-party licenses](../SOURCE/3RD_PARTY_LICENSES.md). This optional private kit is separate from published release assets.

## Current verification

On 2026-10-16, the source builder passed 14 focused tests and three fresh builds produced the same 260,076-byte ARMv5TEJ static executable, SHA256 `9326889739e2094e206605b4530cc344a7a678d64fc63bb224a18d6fff6518dc`. Seven bounded ARM926-emulated SSH controls accepted the provisioned key and rejected wrong-key authentication, password-method availability, forwarding and unsafe authorization-directory permissions. These used a synthetic host account and do not establish the camera's root login or PTY behavior.

The runtime passed ten host fixtures and the same ten with ARM926 BusyBox ash; packaging and boot composition passed nine further tests. A real ARM926 package smoke check loaded the supplied host key, checked the server/BusyBox and shell entry points, verified all public checksums and confirmed the original HTTP entry was byte-identical. These are 43 focused offline test executions plus the seven authentication controls, with no skips.

The known card was then prepared while the camera was powered off: the temporary native trial was privately captured and archived, normal startup restored, and the optional SSH folder and composed hook staged with key readback and the normal marker last. All 6,929 pre-existing files were preserved, all 14 SSH files passed readback, and the card was safely unmounted. No camera configuration, passwords or raw flash were written. The owner has been asked for a normal cold boot; actual camera SSH authentication, PTY, memory and native-enabled normal startup remain pending.
