#!/usr/bin/env python3
"""
silence_cut.py — Remove all pauses from a video. Outputs a clean MP4.

Usage:
    python3 silence_cut.py input.mp4
    python3 silence_cut.py input.mp4 -o output.mp4 --preset aggressive
    python3 silence_cut.py input.mp4 --dry-run --verbose
"""

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from detector import detect_silences, get_video_info
from encoder import _check_hw_accel
from segments import (
    compute_stats,
    filter_min_duration,
    invert_silences,
    merge_overlapping,
)

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

PRESETS = {
    "aggressive": {"threshold": -30.0, "min_silence": 0.25, "margin": 0.0},
    "balanced":   {"threshold": -35.0, "min_silence": 0.40, "margin": 0.05},
    "gentle":     {"threshold": -40.0, "min_silence": 0.60, "margin": 0.15},
}


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def extract_wav(input_path: str, wav_path: str) -> None:
    """Extracts audio as uncompressed 16-bit PCM WAV at 44.1kHz stereo."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", input_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        "-y", wav_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed:\n{result.stderr.strip()}")


def stitch_wav(
    wav_path: str,
    speech_segments: list[tuple[float, float]],
    output_wav_path: str,
) -> None:
    """
    Copies only the speech segments from a PCM WAV at exact sample boundaries.
    sample_index = seconds × sample_rate  →  no codec frames, no bleed, no echo.
    """
    with wave.open(wav_path, "rb") as src:
        n_channels   = src.getnchannels()
        sample_width = src.getsampwidth()
        frame_rate   = src.getframerate()
        total_frames = src.getnframes()

        with wave.open(output_wav_path, "wb") as dst:
            dst.setnchannels(n_channels)
            dst.setsampwidth(sample_width)
            dst.setframerate(frame_rate)

            for seg_start, seg_end in speech_segments:
                start_frame = max(0, min(int(seg_start * frame_rate), total_frames))
                end_frame   = max(0, min(int(seg_end   * frame_rate), total_frames))
                n_frames    = end_frame - start_frame
                if n_frames <= 0:
                    continue
                src.setpos(start_frame)
                dst.writeframes(src.readframes(n_frames))


# ---------------------------------------------------------------------------
# Video helpers
# ---------------------------------------------------------------------------

def cut_video_only(
    input_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
    no_hw: bool,
    forced_keyframes: list[float] = None,
) -> None:
    """
    Cuts the video using FFmpeg's trim filter on decoded frames.

    The old concat demuxer approach seeked to each cut point in the container,
    which required decoding from the nearest keyframe first. That pre-roll caused
    frozen frames and glitches at every cut. The trim filter operates entirely on
    already-decoded frames — no seeking, no pre-roll, no glitches.

    Filter structure per segment:
        [0:v] trim=start=X:end=Y, setpts=PTS-STARTPTS [vN]
    Then all [vN] are joined by the concat filter into [vout].
    """
    use_hw = not no_hw and _check_hw_accel()
    video_codec_args = (
        ["-c:v", "h264_videotoolbox", "-q:v", "65"]
        if use_hw else
        ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
    )
    if forced_keyframes:
        kf_expr = ",".join(f"{t:.6f}" for t in forced_keyframes)
        video_codec_args.extend(["-force_key_frames", kf_expr])

    accel_label = "h264_videotoolbox (HW)" if use_hw else "libx264 (SW)"
    print(f"Cutting video with {accel_label}...")

    # Build the filter graph
    parts, labels = [], []
    for i, (start, end) in enumerate(segments):
        parts.append(
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{i}]"
        )
        labels.append(f"[v{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=0[vout]")
    filter_complex = ";".join(parts)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-stats",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        *video_codec_args,
        "-an",
        "-y", output_path,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit("ERROR: ffmpeg video cut failed.")


def mux(video_path: str, wav_path: str, output_path: str) -> None:
    """
    Combines the cut video with the clean WAV into the final MP4.
    -c:v copy   : video is already encoded, no second pass needed
    -c:a aac    : WAV → AAC for the MP4 container
    -shortest   : absorbs any sub-frame rounding difference in duration
    """
    print("Muxing video + audio...")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-i", wav_path,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        "-y", output_path,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit("ERROR: ffmpeg mux failed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="silence_cut",
        description="Remove all pauses from a video file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 silence_cut.py interview.mp4
  python3 silence_cut.py lecture.mov --preset aggressive -o lecture_tight.mp4
  python3 silence_cut.py podcast.mp4 -t -40 -d 0.3 -m 0.1
  python3 silence_cut.py demo.mp4 --dry-run --verbose
        """,
    )
    parser.add_argument("input", help="Path to input video file")
    parser.add_argument("-o", "--output", help="Output path. Default: <input>_cut.mp4")
    parser.add_argument("-t", "--threshold", type=float, default=None, metavar="DB",
                        help="Silence threshold in dBFS (default: -35).")
    parser.add_argument("-d", "--min-silence", type=float, default=None,
                        dest="min_silence", metavar="SEC",
                        help="Minimum silence duration to cut in seconds (default: 0.4).")
    parser.add_argument("-m", "--margin", type=float, default=None, metavar="SEC",
                        help="Audio padding kept at edges of each segment (default: 0.05).")
    parser.add_argument("--preset", choices=list(PRESETS.keys()), default="balanced",
                        help="aggressive | balanced (default) | gentle")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect and report only. No output file.")
    parser.add_argument("--no-hw", action="store_true",
                        help="Disable hardware acceleration.")
    parser.add_argument("--split-segments", action="store_true",
                        help="Export each speech segment as an individual video file in chronological order.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print all detected intervals.")
    return parser.parse_args()


def apply_preset(args: argparse.Namespace) -> None:
    p = PRESETS[args.preset]
    if args.threshold  is None: args.threshold  = p["threshold"]
    if args.min_silence is None: args.min_silence = p["min_silence"]
    if args.margin     is None: args.margin     = p["margin"]


def fmt_time(s: float) -> str:
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def print_report(args, silences, speech, stats) -> None:
    print(f"\n--- Detection Report ---")
    print(f"Original : {fmt_time(stats['original_s'])} ({stats['original_s']:.1f}s)")
    print(f"Output   : {fmt_time(stats['output_s'])} ({stats['output_s']:.1f}s)")
    print(f"Removed  : {stats['removed_s']:.1f}s ({stats['removed_pct']:.1f}%)")
    print(f"Segments : {stats['num_cuts']}")
    print(f"Settings : threshold={args.threshold}dB  "
          f"min_silence={args.min_silence}s  margin={args.margin}s")
    if args.verbose:
        print(f"\nSilences ({len(silences)}):")
        for i, (s, e) in enumerate(silences, 1):
            print(f"  [{i:3d}] {s:.3f}s → {e:.3f}s  ({e-s:.3f}s)")
        print(f"\nSpeech segments ({len(speech)}):")
        for i, (s, e) in enumerate(speech, 1):
            print(f"  [{i:3d}] {s:.3f}s → {e:.3f}s  ({e-s:.3f}s)")
    print()


def main() -> None:
    args = parse_args()
    apply_preset(args)

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"ERROR: File not found: '{args.input}'")
    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        sys.exit(f"ERROR: Unsupported file type '{input_path.suffix}'")

    output_path = args.output or str(input_path.parent / f"{input_path.stem}_cut.mp4")
    if Path(output_path).resolve() == input_path.resolve():
        sys.exit("ERROR: Output path cannot be the same as the input.")

    # --- Probe ---
    print(f"Probing: {args.input}")
    try:
        info = get_video_info(args.input)
    except RuntimeError as e:
        sys.exit(f"ERROR: {e}")
    if not info.has_audio:
        sys.exit("ERROR: No audio stream found.")
    print(f"  {info.width}x{info.height} {info.video_codec} @ {info.fps:.2f}fps | "
          f"Audio: {info.audio_codec} | Duration: {fmt_time(info.duration)}")

    # --- Detect silences ---
    print(f"\nDetecting silences (threshold={args.threshold}dB, min={args.min_silence}s)...")
    try:
        silences = detect_silences(args.input, args.threshold, args.min_silence)
    except RuntimeError as e:
        sys.exit(f"ERROR: {e}")

    speech = invert_silences(silences, info.duration, args.margin)
    speech = merge_overlapping(speech)
    speech = filter_min_duration(speech)
    stats  = compute_stats(info.duration, speech)

    print_report(args, silences, speech, stats)

    if not speech:
        sys.exit("ERROR: No speech detected. Try a more permissive threshold (e.g., -t -50).")

    if args.dry_run:
        print("[dry-run] No output file written.")
        return

    # --- Process (all temp files share one directory, cleaned up on exit) ---
    with tempfile.TemporaryDirectory(prefix=".silence_cut_") as tmp:
        raw_wav        = f"{tmp}/raw.wav"
        clean_wav      = f"{tmp}/clean.wav"
        video_only_mp4 = f"{tmp}/video_only.mp4"

        print("Extracting audio...")
        try:
            extract_wav(args.input, raw_wav)
        except RuntimeError as e:
            sys.exit(f"ERROR: {e}")

        print(f"Stitching {len(speech)} audio segments at sample level...")
        stitch_wav(raw_wav, speech, clean_wav)

        forced_keyframes = []
        current_time = 0.0
        for s, e in speech:
            forced_keyframes.append(current_time)
            current_time += (e - s)

        cut_video_only(args.input, speech, video_only_mp4, args.no_hw, forced_keyframes if args.split_segments else None)

        mux(video_only_mp4, clean_wav, output_path)

        if args.split_segments:
            print(f"Splitting into {len(speech)} segments...")
            chunks_dir = input_path.parent / f"{input_path.stem}_chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            split_pattern = str(chunks_dir / f"{input_path.stem}_%03d{input_path.suffix}")
            
            split_points = forced_keyframes[1:]
            if split_points:
                times_str = ",".join(f"{t:.6f}" for t in split_points)
                split_cmd = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-i", output_path,
                    "-f", "segment",
                    "-segment_times", times_str,
                    "-reset_timestamps", "1",
                    "-c", "copy",
                    "-y",
                    split_pattern
                ]
                result = subprocess.run(split_cmd)
                if result.returncode != 0:
                    sys.exit("ERROR: ffmpeg segment splitting failed.")

                # Remove the combined output as we only want individual files in this mode
                Path(output_path).unlink(missing_ok=True)
                output_path = split_pattern.replace("%03d", "...")

    print(f"\nDone → {output_path}")
    print(f"Removed {stats['removed_s']:.1f}s ({stats['removed_pct']:.0f}%) "
          f"across {stats['num_cuts']} cuts.")


if __name__ == "__main__":
    main()
