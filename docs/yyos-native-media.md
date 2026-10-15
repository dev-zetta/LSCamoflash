# YYOS native RTSP and ONVIF investigation

**Native RTSP/ONVIF enablement is blocked for this profile after an observed reboot loop. Do not bypass the block or retry configuration.** After an owner-approved native configuration attempt returned `invalid_status_response`, the dashboard and Tuya LAN service disappeared. The owner confirmed repeated reboots; the returned card contained 11 successful management-start records with the same cold-boot PID, consistent with that report. The [guarded recovery attempt](yyos-recovery.md) is tested and staged, with its physical result pending. Current native enable flags and password persistence are unknown.

The host-side [native-media helper](../tools/yyos/native-media.py) targets only the backed-up **LSC 3225722 / SZ F26312 / V14.1.5** profile and exact `yy_cam` identity in the [camera guide](camera-3225722.md). Its production `configure` path is disabled by `NATIVE_ENABLEMENT_ALLOWED = False` and returns **`native_enablement_blocked_boot_loop` before opening a transport**. Offline credential recovery and read-only status remain available. Neither successful activation nor native authentication, playback or recovery has been established.

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

Before the failing configuration attempt, the actual read-only result was **`dp237: false` and `dp239: false`**. DP237 is the native RTSP/ONVIF enable state; DP239 reports whether a native password is set. Both must be boolean values for the helper to accept the response. The dashboard also observed no native listeners on ports 8554 and 5000 at that earlier sample. These historical results do not establish current flag or password persistence; a recovery snapshot is still needed.

The status interface accepts `--timeout` from 1 to 10 seconds, default 3, and `--retries` from 0 to 2 additional connection attempts, default 0. These bounds do not authorize configuration writes. Credential material, raw status payloads and exception details are suppressed in normal CLI output; failures return fixed error codes and, when available, a bounded native error number.

## Why configuration is disabled

The blocked implementation requests a persistent native password change through DP238, requires an exact successful acknowledgement, then requests DP237 enablement and checks fresh status. The device attempt did not return a reliable final status and was followed by repeated reboots. Whether the password change or enable flag persisted, and the exact reboot cause, remain unknown. No executable activation recipe is provided while this block is in place.

The retained synthetic protocol tests check the intended **8–32 non-space ASCII character** password policy with uppercase, lowercase and digit classes, the DP239 current-password guard, and password acknowledgement before enablement. They do not authorize using that path on a physical camera. The stock **DP238 handler logs the password request in plaintext**, even though the host helper suppresses secrets; raw logs from the attempted change must remain private.

Later diagnostic errors can include fixed `phase`, `password_change_acknowledged` and `media_enable_attempted` fields. An attempted write does not prove delivery or persistence, and an acknowledgement is not a complete media acceptance result. The failed device result predates that diagnostic improvement and remains ambiguous. Writes are not automatically replayed, and there is **no automatic rollback**. Do not edit the production gate to continue experimentation.

The candidate endpoints remain `rtsp://<camera-ip>:8554/stream0`, `rtsp://<camera-ip>:8554/stream1` and `http://<camera-ip>:5000/onvif/device_service`. Password enforcement, codecs, decoded video, audio, SOAP operations and app coexistence are unverified. The separate [guarded recovery tool](yyos-recovery.md) passed 45 offline checks and review, and its private payload is staged. Physical recovery remains pending; the linked guide describes its limits and evidence without a generic deployment recipe.

## Current validation

The helper passed **29 focused offline tests**, including the production block before transport, verifier chain, unsafe/tampered input refusal, secret-free output, diagnostic phase fields and synthetic-only protocol/write-order fixtures. Actual backup credential recovery and authenticated read-only LAN status succeeded before the failed activation attempt. The current camera awaits recovery; native RTSP/ONVIF operation is not accepted. The [verified NOR backup](camera-3225722.md#observed-nor-geometry) still does not establish atomic capture, whole-chip coverage or restoration.
