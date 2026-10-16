#!/usr/bin/env python3
"""Convert a downloaded unencrypted YYOS v5 .media segment to timestamped NUT.

Runs on the owner's computer, never on the camera. Video and microphone audio
are copied without re-encoding. Requires PyAV; use FFmpeg for an optional MP4.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys

HEADER = struct.Struct('<IIQQ')
MAX_FRAME = 4 * 1024 * 1024
MAX_INPUT = 1024 * 1024 * 1024
MAX_FRAMES = 1000000
MAX_TIMELINE_US = 24 * 60 * 60 * 1000000
TIME_BASE = Fraction(1, 1000000)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate recording metadata field')
        value[key] = item
    return value


def open_regular(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stream = os.fdopen(descriptor, 'rb')
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
        stream.close()
        raise ValueError('Expected a bounded regular input file')
    return stream


def metadata(path):
    with open_regular(path, 16384) as stream:
        value = json.loads(stream.read(), object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError('Invalid recording metadata')
    expected = {'version': 5, 'encrypt': 0, 'codec': 2, 'video_type': 0,
                'auido_codec': 105, 'audio_sample': 8000, 'audio_databits': 16, 'audio_channel': 0}
    for key, expected_value in expected.items():
        if type(value.get(key)) is not int or value[key] != expected_value:
            raise ValueError('Supported recordings require unencrypted v5 H.264 and 8 kHz mono mu-law audio')
    for key, low, high in (('video_width', 32, 4096), ('video_height', 32, 4096), ('frame_rate', 1, 60)):
        if type(value.get(key)) is not int or not low <= value[key] <= high:
            raise ValueError('Invalid recording dimensions or frame rate')
    return {key: value[key] for key in ('video_width', 'video_height', 'frame_rate')}


def nals(payload):
    if not payload.startswith((b'\0\0\0\1', b'\0\0\1')):
        raise ValueError('Expected H.264 Annex B video payload')
    return [part for part in re.split(rb'\x00\x00(?:\x00)?\x01', payload) if part]


def frames(stream):
    """Read bounded frames. Timestamp fields are wall-clock ms and monotonic us."""
    count = 0
    while True:
        raw = stream.read(HEADER.size)
        if not raw:
            return
        if len(raw) != HEADER.size:
            raise ValueError('Truncated recording frame header')
        kind, size, wall_ms, pts_us = HEADER.unpack(raw)
        if kind not in (0, 1, 3) or not 0 < size <= MAX_FRAME:
            raise ValueError('Unsupported recording frame type or size')
        payload = stream.read(size)
        if len(payload) != size:
            raise ValueError('Truncated recording frame payload')
        count += 1
        if count > MAX_FRAMES:
            raise ValueError('Recording frame limit exceeded')
        yield kind, wall_ms, pts_us, payload, raw


def inspect(stream):
    first_pts = first_wall = None
    latest = {}
    counts = {'video': 0, 'audio': 0}
    hasher = hashlib.sha256()
    extra = None
    final_pts = 0
    audio_samples = 0
    for kind, wall, pts, payload, raw in frames(stream):
        hasher.update(raw); hasher.update(payload)
        media = 'audio' if kind == 3 else 'video'
        if first_pts is None:
            if kind != 1:
                raise ValueError('Segment must begin with a complete H.264 keyframe')
            first_pts, first_wall = pts, wall
            units = nals(payload)
            parameter_sets = [unit for unit in units if unit[0] & 31 in (7, 8)]
            if {unit[0] & 31 for unit in parameter_sets} != {7, 8}:
                raise ValueError('First keyframe is missing H.264 parameter sets')
            extra = b''.join(b'\0\0\0\1' + unit for unit in parameter_sets)
        if pts < first_pts or pts - first_pts > MAX_TIMELINE_US or (media in latest and pts <= latest[media]):
            raise ValueError('Recording timestamps are invalid or non-increasing')
        if kind != 3:
            types = {unit[0] & 31 for unit in nals(payload)}
            if (5 if kind == 1 else 1) not in types:
                raise ValueError('Video frame type does not match its H.264 payload')
        else:
            audio_samples += len(payload)
        latest[media] = pts
        counts[media] += 1
        final_pts = max(final_pts, pts - first_pts + (len(payload) * 125 if kind == 3 else 0))
    if not counts['video'] or not counts['audio']:
        raise ValueError('Expected both video and microphone audio')
    return {'source_sha256': hasher.hexdigest(), 'first_pts_us': first_pts, 'first_wall_ms': first_wall,
            'duration_us': final_pts, 'frames': counts, 'audio_samples': audio_samples, 'extradata': extra}


def identity(stream):
    info = os.fstat(stream.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def convert(source, info_path, output):
    dimensions = metadata(info_path)
    output = Path(output).absolute()
    if output.suffix.lower() != '.nut' or output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('Choose a new .nut output file in an existing directory')
    import av
    av.logging.set_level(av.logging.ERROR)
    with open_regular(source, MAX_INPUT) as stream:
        before = identity(stream)
        report = inspect(stream)
        if identity(stream) != before:
            raise ValueError('Source changed during validation; download a completed segment')
        stream.seek(0)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as destination, av.open(destination, 'w', format='nut') as mux:
                video = mux.add_stream('h264', rate=dimensions['frame_rate'])
                video.width, video.height = dimensions['video_width'], dimensions['video_height']
                video.time_base = TIME_BASE
                video.codec_context.extradata = report['extradata']
                audio = mux.add_stream('pcm_mulaw', rate=8000)
                audio.layout, audio.time_base = 'mono', TIME_BASE
                copied_hash = hashlib.sha256()
                for kind, wall, pts, payload, raw in frames(stream):
                    copied_hash.update(raw); copied_hash.update(payload)
                    packet = av.Packet(payload)
                    packet.stream = audio if kind == 3 else video
                    packet.time_base = TIME_BASE
                    packet.pts = packet.dts = pts - report['first_pts_us']
                    packet.is_keyframe = kind == 1
                    packet.duration = len(payload) * 125 if kind == 3 else 0
                    mux.mux(packet)
                if identity(stream) != before or copied_hash.hexdigest() != report['source_sha256']:
                    raise ValueError('Source changed during conversion')
            with output.open('rb') as complete:
                os.fsync(complete.fileno())
            directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    del report['extradata']
    report.update({'ok': True, 'video_reencoded': False, 'audio_reencoded': False,
                   'timestamps_preserved': True, 'output_bytes': output.stat().st_size})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='downloaded completed NNNN.media segment')
    parser.add_argument('--info', required=True, type=Path, help='downloaded .info from the same recording session')
    parser.add_argument('--output', required=True, type=Path, help='new .nut file; existing files are never overwritten')
    args = parser.parse_args()
    try:
        report = convert(args.source, args.info, args.output)
    except ImportError:
        parser.exit(1, 'Install the host dependency: python3 -m pip install av==19.0.1\n')
    except (OSError, ValueError, RuntimeError):
        parser.exit(1, 'Conversion failed: unsupported, incomplete, changed or unreadable input; existing files were preserved.\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
