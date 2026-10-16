# Download and convert YYOS recordings

The authenticated YYOS recording browser reads the stock `DCIM/CHAN0/YYYY/MM/DD/EPOCH_DURATION/NNNN.media` layout. It lists days, sessions and raw segments and offers the same session's private `.info` metadata as an attachment. It does not parse that metadata on the camera, delete recordings, alter stock recording settings or promise browser/VLC playback of the proprietary `.media` container. The stock application continues recording independently. Download completed segments; a growing or truncated active file can change during transfer and must be retried later.

The separate public YYOS package includes the host-only `tools/convert-recording.py` and pinned `tools/recording-requirements.txt`. The converter accepts unencrypted version 5 H.264 video with 8 kHz mono mu-law audio, verifies bounded headers and strictly increasing per-stream timestamps, and copies both encoded streams into a new timestamped NUT file without re-encoding. Unsupported/encrypted metadata, missing audio/video, corrupt or incomplete frames, changed input and existing output are refused. Keep the original `.media` and matching `.info`; conversion does not rewrite them.

Download one completed segment and its `.info` through the authenticated browser and preserve both privately on the host. Install the converter dependency in an isolated environment, then invoke the packaged host tool:

```sh
python3 -m venv /private/yyos-converter-env
/private/yyos-converter-env/bin/python -m pip install -r LSCamoflash-yyos-kit/tools/recording-requirements.txt
/private/yyos-converter-env/bin/python LSCamoflash-yyos-kit/tools/convert-recording.py \
  /private/0000.media --info /private/session.info --output /private/recording.nut
```

When using the repository instead of the downloaded kit, the corresponding paths are `tools/yyos/convert-recording.py` and `tools/yyos/recording-requirements.txt`. The JSON result reports frame counts, original timeline duration and source/output byte information; it contains no recording payload or credentials. This host tool opens no network connection and never runs on the camera.

NUT preserves the captured H.264 and G.711 audio. Player support varies; FFmpeg can produce a separate H.264/AAC MP4 for broader playback compatibility. Validate the complete converted recording and audio before relying on that derivative, and retain the original timing/data. The converter does not merge multiple sessions or create missing audio. Downloaded recordings and `.info` may contain private footage, audio and identifiers; do not publish them as bug-report fixtures.

```sh
ffmpeg -n -i /private/recording.nut -c:v copy -c:a aac -ar 48000 \
  -movflags +faststart /private/recording.mp4
```

This keeps the original H.264 video and converts microphone audio to AAC. Some clients can still struggle with this camera's high-resolution H.264 stream; MP4 packaging alone does not change its video profile. See the [VLC investigation](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/yyos-vlc.md) for the separate player issue.

## Format and validation

The verified camera sample has a 24-byte little-endian frame header: `uint32 type`, `uint32 payload_bytes`, `uint64 wall_clock_ms`, `uint64 monotonic_pts_us`. Observed types are 1 for an H.264 keyframe, 0 for an H.264 inter frame and 3 for G.711 mu-law audio. This implementation was derived independently from verified camera bytes; the [SmartLife recording extractor](https://github.com/slott/smartlife) is a related community format reference, with no code copied from it.

One completed 705,164-byte camera segment retained all **150 video packets and 262 audio packets / 83,840 samples**. Independent packet comparison verified every payload hash and relative timestamp exactly; the NUT decoded with FFmpeg exit 0 and no error output. Twelve live HTTP checks also accepted authentication controls, directory lists, HEAD, byte-identical raw/metadata downloads and malformed-request rejection. These checks cover this narrow unencrypted format; user browser interaction, encrypted formats, joined sessions and long-term retention remain separate. See the [camera guide](https://github.com/dev-zetta/LSCamoflash/blob/main/docs/camera-3225722.md) for deployment and resource measurements.
