"""Offline malformed-input and timestamp controls for the YYOS recording reader."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('yyos_recording_convert', REPO / 'tools/yyos/convert-recording.py')
CONVERT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CONVERT)
KEYFRAME = b'\0\0\0\1\x67sps\0\0\0\1\x68pps\0\0\0\1\x65picture'
PFRAME = b'\0\0\0\1\x41picture'


def frame(kind, pts, payload):
    return CONVERT.HEADER.pack(kind, len(payload), 1700000000000 + pts // 1000, pts) + payload


class RecordingConversionTests(unittest.TestCase):
    def test_microsecond_timestamps_and_audio_preserved(self):
        source = frame(1, 39771000, KEYFRAME) + frame(3, 39771000, b'\xff' * 320)
        source += frame(0, 39841000, PFRAME) + frame(3, 39851000, b'\x80' * 320)
        result = CONVERT.inspect(io.BytesIO(source))
        self.assertEqual(result['frames'], {'video': 2, 'audio': 2})
        self.assertEqual(result['audio_samples'], 640)
        self.assertEqual(result['duration_us'], 120000)
        self.assertEqual(result['first_pts_us'], 39771000)
        self.assertEqual(result['extradata'], b'\0\0\0\1\x67sps\0\0\0\1\x68pps')

    def test_incomplete_headers_and_payloads_refused(self):
        for source in (b'\x01', CONVERT.HEADER.pack(1, 100, 0, 0) + b'short'):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, 'Truncated'):
                    list(CONVERT.frames(io.BytesIO(source)))

    def test_unknown_type_and_huge_payload_refused_before_read(self):
        for kind, size in ((2, 100), (1, CONVERT.MAX_FRAME + 1), (3, 0)):
            with self.subTest(kind=kind, size=size):
                with self.assertRaisesRegex(ValueError, 'type or size'):
                    list(CONVERT.frames(io.BytesIO(CONVERT.HEADER.pack(kind, size, 0, 0))))

    def test_duplicate_or_backwards_pts_refused_per_track(self):
        for pts in (100, 99):
            with self.subTest(pts=pts):
                source = frame(1, 100, KEYFRAME) + frame(3, 100, b'\xff' * 320) + frame(0, pts, PFRAME)
                with self.assertRaisesRegex(ValueError, 'timestamps'):
                    CONVERT.inspect(io.BytesIO(source))

    def test_missing_keyframe_or_parameter_sets_refused(self):
        for source in (frame(0, 0, PFRAME), frame(1, 0, b'\0\0\0\1\x65picture')):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    CONVERT.inspect(io.BytesIO(source))

    def test_encrypted_or_duplicate_metadata_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.info'
            for contents in ('{"encrypt":1}', '{"encrypt":0,"encrypt":1}'):
                with self.subTest(contents=contents):
                    path.write_text(contents)
                    with self.assertRaises(ValueError):
                        CONVERT.metadata(path)

    def test_symlink_and_empty_source_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'empty'
            source.touch()
            with self.assertRaises(ValueError):
                CONVERT.open_regular(source, 100)
            link = Path(tmp) / 'link'
            link.symlink_to(source)
            with self.assertRaises(OSError):
                CONVERT.open_regular(link, 100)


if __name__ == '__main__':
    unittest.main()
