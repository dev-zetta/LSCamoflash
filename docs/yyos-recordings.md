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
