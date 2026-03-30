"""
encoder.py — concat spec writer and ffmpeg encode command builder.
"""

import os
import subprocess
import sys
from pathlib import Path


def write_concat_file(
    speech_segments: list[tuple[float, float]],
    input_path: str,
    tmp_dir: str,
) -> Path:
    """
    Writes an FFmpeg concat demuxer spec file.
    References the same source file N times with inpoint/outpoint.
    No temp video segments are created — disk-efficient.

    Format:
        file '/abs/path/input.mp4'
        inpoint 2.847000
        outpoint 5.102000
        ...
    """
    abs_input = os.path.abspath(input_path)
    concat_path = Path(tmp_dir) / "concat.txt"

    lines = []
    for start, end in speech_segments:
        lines.append(f"file '{abs_input}'")
        lines.append(f"inpoint {start:.6f}")
        lines.append(f"outpoint {end:.6f}")

    concat_path.write_text("\n".join(lines) + "\n")
    return concat_path


def _check_hw_accel() -> bool:
    """Returns True if h264_videotoolbox is available (macOS only)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True,
        )
        return "h264_videotoolbox" in result.stdout
    except Exception:
        return False


def encode_output(
    concat_file: Path,
    output_path: str,
    no_hw: bool = False,
    crf: int = 18,
    preset: str = "fast",
    audio_bitrate: str = "192k",
    verbose: bool = False,
) -> None:
    """
    Runs the final FFmpeg encode using the concat demuxer spec.
    Uses libx264 by default; switches to h264_videotoolbox on macOS if available.

    Re-encoding (not stream copy) is required for frame-accurate cuts
    at non-keyframe boundaries.
    """
    use_hw = not no_hw and _check_hw_accel()

    if use_hw:
        video_codec_args = ["-c:v", "h264_videotoolbox", "-q:v", "65"]
    else:
        video_codec_args = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]

    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        *video_codec_args,
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        "-y",
        output_path,
    ]

    if not verbose:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats",
               "-f", "concat", "-safe", "0", "-i", str(concat_file),
               *video_codec_args,
               "-c:a", "aac", "-b:a", audio_bitrate,
               "-movflags", "+faststart",
               "-y", output_path]

    if verbose:
        print(f"[encoder] Running: {' '.join(cmd)}")
    else:
        accel_label = "h264_videotoolbox (HW)" if use_hw else "libx264 (SW)"
        print(f"Encoding with {accel_label}...")

    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print(
            f"\nERROR: ffmpeg encode failed (exit {result.returncode}).",
            file=sys.stderr,
        )
        sys.exit(1)
