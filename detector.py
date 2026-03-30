"""
detector.py — ffprobe video info and ffmpeg silencedetect wrapper
"""

import json
import re
import subprocess
from dataclasses import dataclass


@dataclass
class VideoInfo:
    duration: float
    video_codec: str
    audio_codec: str
    fps: float
    width: int
    height: int
    has_audio: bool


def get_video_info(input_path: str) -> VideoInfo:
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed on '{input_path}':\n{result.stderr.strip()}"
        )

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    duration = float(fmt.get("duration", 0))

    video_codec = ""
    audio_codec = ""
    fps = 0.0
    width = 0
    height = 0
    has_audio = False

    for s in streams:
        if s.get("codec_type") == "video" and not video_codec:
            video_codec = s.get("codec_name", "")
            width = s.get("width", 0)
            height = s.get("height", 0)
            # fps from r_frame_rate e.g. "30/1" or "60000/1001"
            r = s.get("r_frame_rate", "0/1")
            try:
                num, den = r.split("/")
                fps = float(num) / float(den) if float(den) else 0.0
            except (ValueError, ZeroDivisionError):
                fps = 0.0
        elif s.get("codec_type") == "audio" and not audio_codec:
            audio_codec = s.get("codec_name", "")
            has_audio = True

    return VideoInfo(
        duration=duration,
        video_codec=video_codec,
        audio_codec=audio_codec,
        fps=fps,
        width=width,
        height=height,
        has_audio=has_audio,
    )


def detect_silences(
    input_path: str,
    threshold_db: float,
    min_silence_dur: float,
) -> list[tuple[float, float]]:
    """
    Returns a sorted list of (start_sec, end_sec) silence intervals.
    Runs audio-only pass (~30-50x realtime).
    """
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-af", f"silencedetect=noise={threshold_db}dB:duration={min_silence_dur}",
        "-vn",
        "-f", "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # ffmpeg writes silencedetect output to stderr even on success
    stderr = result.stderr

    if result.returncode != 0 and "silencedetect" not in stderr:
        raise RuntimeError(
            f"ffmpeg failed on '{input_path}':\n{stderr.strip()}"
        )

    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", stderr)]

    # Edge case: video ends mid-silence — no matching silence_end for last start
    if len(starts) > len(ends):
        # Get duration from ffprobe to close the final interval
        try:
            info = get_video_info(input_path)
            ends.append(info.duration)
        except Exception:
            ends.append(starts[-1])  # fallback: zero-length final silence

    silences = sorted(zip(starts, ends))
    return silences
