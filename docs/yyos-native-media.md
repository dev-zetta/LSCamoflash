# YYOS native RTSP and ONVIF investigation

**Native RTSP/ONVIF enablement is blocked for this profile after an observed reboot loop. Do not bypass the block or retry configuration.** The [short guarded recovery boot and returned evidence](yyos-recovery.md) now passed after that failure: the owner reported steady Online operation, and private host verification proved both enable flags changed from 1 to 0 with all other bytes preserved. Status observed DP237 false / DP239 true. One subsequent normal-bootstrap cold boot also passed owner/read-only checks, with native enablement still off. Native-password authentication and long-term stability remain unverified.

The host-side [native-media helper](../tools/yyos/native-media.py) targets only the backed-up **LSC 3225722 / SZ F26312 / V14.1.5** profile and exact `yy_cam` identity in the [camera guide](camera-3225722.md). Its production `configure` path is disabled by `NATIVE_ENABLEMENT_ALLOWED = False` and returns **`native_enablement_blocked_boot_loop` before opening a transport**. Offline credential recovery and read-only status remain available. Native authentication/playback and long-term stability have not been established; short recovery and normal-startup checks passed.

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

The host helper now limits new passwords to **8–15 non-space ASCII characters**, leaving room for the terminating NUL, with uppercase, lowercase and digit classes. The old-password input limit remains 63 bytes to handle existing values. This preventive validation does not unblock activation: the production gate remains false, protocol writes are tested only with synthetic transports, and no further guarded device trial is prepared. The stock **DP238 handler logs the password request in plaintext**; raw logs must remain private.

Later diagnostic errors can include fixed `phase`, `password_change_acknowledged` and `media_enable_attempted` fields. An attempted write does not prove delivery or persistence, and an acknowledgement is not a complete media acceptance result. The failed device result predates that diagnostic improvement and remains ambiguous. Writes are not automatically replayed, and there is **no automatic rollback**. Do not edit the production gate to continue experimentation.

The candidate endpoints remain `rtsp://<camera-ip>:8554/stream0`, `rtsp://<camera-ip>:8554/stream1` and `http://<camera-ip>:5000/onvif/device_service`. Password enforcement, codecs, decoded video, audio, SOAP operations and app coexistence are unverified. The separate [guarded recovery tool](yyos-recovery.md) passed 45 offline checks/review, the short physical recovery boot and private output verification. One normal-bootstrap cold boot also passed short checks; the linked guide describes the bounded evidence without a generic deployment recipe.

## Current validation

The helper passed **32 focused offline tests with no skips**, including the 15-byte new-password ceiling, production block before transport, verifier chain, unsafe/tampered input refusal, secret-free output, diagnostic phase fields and synthetic-only protocol/write-order fixtures. Actual backup credential recovery and read-only LAN status succeeded, including the later false/true recovery/normal-boot results. Native RTSP/ONVIF operation is not accepted; short normal-bootstrap acceptance passed, while long-term recovery stability remains unverified. The [verified NOR backup](camera-3225722.md#observed-nor-geometry) still does not establish atomic capture, whole-chip coverage or restoration.
