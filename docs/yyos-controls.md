# YYOS camera controls

The optional Controls tab in the separate [v2.01.0000 YYOS kit](yyos-setup.md) targets only LSC 3225722 / SZ F26312 / V14.1.5 and the exact running application recorded in the [camera guide](camera-3225722.md). It uses the stock Tuya LAN service on localhost, keeping the stock camera application responsible for the hardware. It supplies indicator LED and timestamp switches, four short manual pan/tilt steps and Stop. Native ONVIF on this firmware exposes no usable PTZ configuration; these dashboard buttons use a separate narrow helper.

## Enable privately

Build or obtain a complete YYOS kit containing the controls helper and CGI adapter. Recover the camera's own LAN credential file from its verified backup using the [native-media guide](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/yyos-native-media.md#recover-lan-credentials-from-the-verified-backup). During private host provisioning, supply that mode 0600 file to the [installer](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/yyos-setup.md):

```sh
python3 LSCamoflash-yyos-kit/install-kit.py provision \
  --kit LSCamoflash-yyos-kit \
  --output /private/yyos-site-kit \
  --native-credentials /private/yyos-native-credentials.json
```

Provisioning validates the exact firmware/profile and writes only the 16-byte local key to `card/LSCamoflash-yyos/native-control.key`, outside the web root and public checksum inventory. It does not configure native streaming, change the key or contact the camera. The entire private kit must remain private. Public archives contain no local key, and a missing key leaves Controls disabled while status, recording downloads and other management functions remain available. Recognized upgrades preserve an existing key. FAT card permissions do not protect a removed card from its holder; dashboard authentication protects network requests, not physical access.

## Use the dashboard

Sign in to HTTP 8080 with the separate dashboard account and open Controls. Refresh reads only indicator, timestamp and tracking booleans. The two switches send one fixed native setting request and verify its value through an independent read-only session. They never change Wi-Fi, pairing, streaming credentials, recording settings or firmware. An uncertain result is displayed as a failure and is not automatically repeated.

Manual steps require stock motion tracking already off. Use the stock app to change tracking intentionally; the dashboard does not change it on your behalf. Each direction click requests a fixed 200 ms step, with no held-button or adjustable-duration interface. A detached guardian prepares a separate authenticated Stop session before movement is armed, owns the disposable movement worker and sends Stop at its logical deadline or when its caller disappears. Only Stop can be retried within a bounded budget. Overlapping helper operations are refused. Stop controls manual movement; it does not disable tracking, patrol or unrelated commands issued by another client.

This is a software stop safeguard, not a physical hard-real-time guarantee. Stock SDK queues, a stalled kernel and concurrent app commands are outside the helper's control. Do not interpret an acknowledged Stop as a motor-position measurement. Calibration, presets, patrol, arbitrary DP commands, reboot, formatting and firmware updates are unavailable.

## Implementation and validation

The [core source](https://github.com/dev-zetta/LSCamoflash/blob/main/SOURCE/src/contrib/yyos-controls/yyos_controls.c) accepts only status, the two boolean settings, four cardinal steps and Stop. It verifies root, the exact CPU, one matching running stock executable and its hash before controls. It reads the local key through stdin, authenticates Tuya 3.5 AES-GCM/HMAC sessions to `127.0.0.1:6668`, and exposes no arbitrary address, payload, duration or DP selector. Sensitive or unknown native values are excluded from output.

The [CGI adapter](https://github.com/dev-zetta/LSCamoflash/blob/main/SOURCE/src/contrib/yyos-controls/yyos_controls_cgi.c) requires dashboard authentication, a canonical private IPv4 Host on port 8080, exact same-origin POSTs, a fixed custom header, bounded JSON and the action allowlist. It executes a fixed checked helper descriptor without a shell, supplies the key through a pipe, and bounds output and elapsed time. It exposes no cross-origin permissions. Tests include synthetic host and ARM926 fixtures, malformed requests/keys/helper responses, termination, timeouts and frontend no-replay behavior. Synthetic success and a reproducible production build do not establish physical movement or long-term reliability; live observations belong in the camera guide.

The [production builder](https://github.com/dev-zetta/LSCamoflash/blob/main/tools/yyos/build-controls.py) uses the pinned Dropbear 2026.94 LibTomCrypt sources and validated static musl 1.2.6 build. It retains exact allocator/wipe integration patches, compiled sources, relinkable objects, upstream archives, clock-adapter provenance and component notices. Fixture keys/hooks are excluded from the production binary. The combined package validates those materials against current project sources before distribution.

## Bounded device observations

On 2026-10-16, an initial indicator setter acknowledged its write but failed readback on the same connection. A separate query confirmed the indicator was off; the write was not repeated. After the helper was corrected to use a fresh authenticated read session, the indicator was restored and both indicator/timestamp off/on round trips passed, with their original values restored. Manual Stop also acknowledged successfully; tracking remained off.

One rightward and one leftward command each reported armed=true, a movement acknowledgement and one Stop acknowledgement at the logical 200 ms deadline. Private ten-second captures retained H.264 video and PCMU audio; inspected frames showed the corresponding view changes. A separate 30-second capture after the rightward command showed a settled view. This accepts short horizontal movement/Stop behavior on the tested unit. It does not establish a physical 200 ms motor duration, exact position restoration, vertical movement, simultaneous app control, caller-loss behavior on real hardware or long-term safety. Caller-loss/ambiguous-response cases have synthetic fixtures only.

The controls-enabled HTTP runtime was then deployed over pinned SSH with the previous runtime, authentication and startup log preserved. Sixteen live HTTP checks passed, including missing/wrong credentials, key isolation outside the web root, same-origin/custom-header checks, malformed/calibration action refusal, filtered status, an unchanged-setting request and manual Stop. Headless Chromium accepted the actual desktop/mobile Controls page and indicator off/on buttons, with exactly two POSTs, the original value restored, no JavaScript errors and no document-width overflow. Stock PID 446 remained unchanged; HTTP RSS was 648 KiB and available RAM 16,008 KiB at the status sample. These are short automated checks, not repeated-boot or long-term acceptance.

The owner subsequently confirmed **camera operation and rotation** on 2026-10-16. This accepts the observed manual behavior alongside the short horizontal tests above; it does not establish every axis, an exact physical 200 ms stop deadline, a new cold boot, simultaneous app commands or endurance.
