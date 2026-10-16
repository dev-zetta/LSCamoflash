# YYOS native RTSP and ONVIF investigation

**Public native RTSP/ONVIF enablement remains blocked after the observed 24-byte-password reboot loop. Do not bypass the block or retry configuration.** Recovery and one native-off normal boot passed. A separately controlled **15-byte-password trial** later passed short TCP/UDP media, RTSP Digest and ONVIF WSSE checks below. A native-enabled cold boot through the normal bootstrap has **not** been accepted; owner app checks and long-term stability remain pending; audible microphone sound was confirmed in a recorded sample. No public activation recipe is provided.

The host-side [native-media helper](../tools/yyos/native-media.py) targets only the backed-up **LSC 3225722 / SZ F26312 / V14.1.5** profile and exact `yy_cam` identity in the [camera guide](camera-3225722.md). Its production `configure` path is disabled by `NATIVE_ENABLEMENT_ALLOWED = False` and returns **`native_enablement_blocked_boot_loop` before opening a transport**. Offline credential recovery and read-only status remain available. The controlled trial's short authentication/media checks do not unblock that public path or establish normal enabled startup.

The helper is separate from the [read-only management dashboard](yyos-management.md). Dashboard credentials do not protect native RTSP or ONVIF. The native services' expected stock username is **`admin`**; this is not a claim about the current password. There is no default password supplied by this project. Earlier working HTTP checks preceded the native configuration attempt and do not establish current camera health.

## Prepare a private host environment

Run from a current source checkout on the host, using Python 3.11 or later. The [requirements file](../tools/yyos/requirements.txt) installs `cryptography` for offline credential recovery and pins **TinyTuya 1.20.0** for LAN operations. The helper refuses a different TinyTuya version because its write/retry behavior is checked against that implementation. It uses an explicit private IPv4 address, with no discovery or cloud account/API dependency.

```sh
VENV="/absolute/private/path/yyos-media-venv"
python3 -m venv "$VENV"
PYTHON="$VENV/bin/python"
"$PYTHON" -m pip install -r tools/yyos/requirements.txt
```

Credentials and password inputs must be regular files owned by the current host user, with no group/world permissions; use **mode `0600`** in a private directory. Symlinks, oversized files and unsafe permissions are refused. Create password files privately rather than putting passwords in command arguments, shell history or shared examples. Keep the environment, credential JSON, passwords and all recovered device files out of public source and release assets.

## Recover LAN credentials from the verified backup

The `credentials` command is offline. It reruns the complete backup verifier, requires the exact six-partition / 8 MiB profile, verifies the userspace archive and stock application hash, and reads only the required archive members without extracting or executing firmware. It validates the encrypted database structure, matching database copies, internal firmware version and Tuya 3.5 profile before creating a new private credential JSON.

```sh
"$PYTHON" tools/yyos/native-media.py credentials \
  --backup-run /absolute/private/path/firmware-backup/run-TIMESTAMP-PID \
  --output /absolute/private/path/yyos-native-credentials.json
```

`--output` must be absent; the helper creates it exclusively with mode `0600` and checked file/directory flushes. The JSON contains the device ID and local key alongside fixed profile/version/hash fields. Those values are never printed by the helper. Recovery from this camera's actual verified backup succeeded; keep that credential file and the proprietary backup private. No stock firmware or recovered configuration is distributed with the tool.

## Read native-media status

When the camera is independently confirmed reachable, set `CAMERA_IP` to its current address from your router's leases. Only RFC1918 IPv4 addresses are accepted. `status` authenticates with the recovered LAN credentials and returns a small redacted result; it is not a boot-loop recovery mechanism:

```sh
CAMERA_IP="<camera-lan-ip>"
"$PYTHON" tools/yyos/native-media.py status \
  --credentials /absolute/private/path/yyos-native-credentials.json \
  --host "$CAMERA_IP"
```

Before the failing configuration attempt, the actual read-only result was **`dp237: false` and `dp239: false`**. On the later short recovery boot it was **`dp237: false` and `dp239: true`**, with no native listeners observed. DP237 is the enable state and DP239 is a password-set indicator; it does not disclose or verify the password itself. Both must be boolean values for the helper to accept the response. Returned recovery output proves the exact flag edit and preservation of password bytes; the off state also persisted through one observed normal-bootstrap cold boot. This does not establish long-term stability or native authentication.

The status interface accepts `--timeout` from 1 to 10 seconds, default 3, and `--retries` from 0 to 2 additional connection attempts, default 0. These bounds do not authorize configuration writes. Credential material, raw status payloads and exception details are suppressed in normal CLI output; failures return fixed error codes and, when available, a bounded native error number.

## Why configuration is disabled

The blocked implementation requests a persistent native password change through DP238, requires an exact successful acknowledgement, then requests DP237 enablement and checks fresh status. The device attempt did not return a reliable final status and was followed by repeated reboots. The later recovery snapshot established that both configuration enable flags were 1 before recovery changed them to 0, preserving all password bytes. This does not verify the password through native authentication or establish the exact reboot cause. No executable activation recipe is provided while the block is in place.

Independent static review confirmed that this exact stock binary copies native RTSP and ONVIF passwords into **16-byte caches with unbounded `strcpy`**. Both password values in the preserved pre-recovery configuration were **24 bytes**, exceeding those caches including the terminating NUL. Later overlapping copies and forward-copy libc behavior provide a strong crash candidate. No captured crash program counter proves that this was the actual reboot path, so physical causality remains unconfirmed.

The host helper now limits new passwords to **8–15 non-space ASCII characters**, leaving room for the terminating NUL, with uppercase, lowercase and digit classes. The old-password input limit remains 63 bytes to handle existing values. This preventive validation does not unblock the public configuration path: its gate remains false. A separately controlled 15-byte trial has the bounded observations below; those results are not an activation recipe. The stock **DP238 handler logs the password request in plaintext**; raw logs must remain private.

Later diagnostic errors can include fixed `phase`, `password_change_acknowledged` and `media_enable_attempted` fields. An attempted write does not prove delivery or persistence, and an acknowledgement is not a complete media acceptance result. The failed device result predates that diagnostic improvement and remains ambiguous. Writes are not automatically replayed, and there is **no automatic rollback**. Do not edit the production gate to continue experimentation.

The exact trial endpoints were `rtsp://<camera-ip>:8554/stream0`, `rtsp://<camera-ip>:8554/stream1` and `http://<camera-ip>:5000/onvif/device_service`; their short authentication/decoding observations are recorded below. The separate [guarded recovery tool](yyos-recovery.md) passed 45 offline checks/review, the short physical recovery boot and private output verification. One native-off normal-bootstrap cold boot also passed short checks; the linked guide describes the bounded evidence without a generic deployment recipe.

## Current validation

The helper passed **37 focused offline tests**, including the 15-byte new-password ceiling, production block before transport, bounded final-status queries, verifier chain, secret-free output and synthetic protocol/write-order fixtures. The public gate remains false. The separate controlled device trial below establishes only short observations; an enabled cold boot through the normal bootstrap, owner app acceptance and long-term use remain pending. Recorded microphone sound was accepted by the owner. The [verified NOR backup](camera-3225722.md#observed-nor-geometry) still does not establish atomic capture, whole-chip coverage or restoration.

## Guarded 15-byte trial: bounded acceptance

One separately controlled native setup attempt used a **15-byte password**. Its retained result was **`invalid_status_response` at `final_status`**, with password acknowledgement true and enable attempt true. The actual final reply was not captured. A fresh, separate authenticated Tuya query subsequently returned **DP237 true / DP239 true**, while HTTP status showed uptime **239 seconds**, stock/management running, both native listeners present and **16,664 KiB available RAM**. A later sample reached **1,324 seconds**, with stock/management and both listeners still present, **16,504 KiB available RAM**, **648 KiB HTTP RSS** and **10,100 KiB stock RSS**. These independent checks establish enabled services despite the ambiguous command result; they do not turn the original result into a successful reply or justify replaying either write.

The helper's later final-status handling permits at most three read-only queries after known, well-formed partial notifications. It never combines separate partial responses into a complete success and never replays password/enable writes. Since the failing device reply was not captured, its cause cannot be attributed to those notifications from the available evidence.

All four five-second PyAV 19 decode checks passed. Main video was **H.264 2304×1296**, sub video **H.264 640×360**, with **PCMU 8 kHz mono** audio on every stream/transport:

| Stream / transport | Video frames | Audio frames | Nonzero audio samples |
| --- | ---: | ---: | --- |
| `/stream0` / TCP | 99 | 165 | 5,451 of 52,800; peak 0.009888. |
| `/stream1` / TCP | 99 | 150 | 0 |
| `/stream0` / UDP | 100 | 176 | 0 |
| `/stream1` / UDP | 99 | 174 | 0 |

Audio transport and decoding passed, with nonzero samples only in the first main-TCP capture. Zero samples in the other captures do not establish quiet surroundings, VAD behavior or a microphone fault. A later 30-second main-stream recording retained H.264 video and PCMU audio, and the owner confirmed audible microphone sound in its compatible MP4 copy on **2026-10-16**. This accepts the recorded microphone path; direct VLC live playback, detailed synchronization and app coexistence remain separate checks.

A separate read-only RTSP authentication check sent five DESCRIBE requests and completed successfully in **0.37 seconds**: anonymous access returned **401**, an incorrect password using the advertised **Digest MD5** scheme returned **401**, and the correct password returned **200** with video/audio SDP. This establishes the tested authentication exchange, not every native endpoint or long-term session behavior.

A 12-check read-only ONVIF report completed successfully in about **0.38 seconds**: correct WSSE authenticated time/capability/profile/stream-URI requests returned **HTTP 200**, exposing two profiles and addresses pointing to this camera's port 5000. Anonymous and incorrect-WSSE profile/URI requests returned **HTTP 400 / `ter:NotAuthorized`**. HTTP Digest alone was not accepted and produced no challenge; the time query also required authentication. The sampled clock offset was approximately −2.5 seconds. These are direct SOAP checks, not complete ONVIF conformance, discovery, PTZ or general client compatibility.

**Native-enabled normal cold-boot acceptance is pending.** On 2026-10-16, the returned card yielded 33 privately verified trial files totaling 26,797 bytes. The logs show one wrapper stock launch, recovery exit 3 for an already-off initial state, and an unchanged preserved initial configuration. The temporary trial startup was archived and the known normal management startup restored, preserving 6,926 existing files without a camera-configuration write. Recorded microphone sound was accepted by the owner; app coexistence and long-term behavior remain open. The public helper stays disabled, no activation recipe is provided, and the earlier 24-byte-password reboot loop/recovery history remains relevant.
