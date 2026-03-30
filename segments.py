"""
segments.py — pure Python logic for converting silence intervals to speech segments.
No external dependencies. Fully unit-testable in isolation.
"""


def invert_silences(
    silences: list[tuple[float, float]],
    duration: float,
    margin: float = 0.05,
) -> list[tuple[float, float]]:
    """
    Converts a list of silence intervals into speech (keep) intervals.

    margin: seconds of audio to keep at the edges of each silence,
            preventing the first/last phoneme of a word from being clipped.

    Example:
        silences = [(1.0, 3.0), (6.0, 8.0)], duration = 10.0, margin = 0.1
        speech   = [(0.0, 1.1), (2.9, 6.1), (7.9, 10.0)]
    """
    if not silences:
        return [(0.0, duration)] if duration > 0 else []

    speech = []
    prev_end = 0.0

    for silence_start, silence_end in silences:
        seg_start = max(0.0, prev_end - margin)
        seg_end = min(duration, silence_start + margin)
        if seg_start < seg_end:
            speech.append((seg_start, seg_end))
        prev_end = silence_end

    # Tail: from last silence_end to the end of the video
    tail_start = max(0.0, prev_end - margin)
    if tail_start < duration:
        speech.append((tail_start, duration))

    return speech


def merge_overlapping(
    segments: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    Merges overlapping or adjacent speech segments (produced after margin expansion).
    Input must be sorted by start time (invert_silences already returns sorted output).
    """
    if not segments:
        return []

    merged = [segments[0]]
    for start, end in segments[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    return merged


def filter_min_duration(
    segments: list[tuple[float, float]],
    min_dur: float = 0.05,
) -> list[tuple[float, float]]:
    """
    Drops segments shorter than min_dur seconds.
    These are typically noise blips between two silences, not real speech.
    """
    return [(s, e) for s, e in segments if (e - s) >= min_dur]


def compute_stats(
    original_duration: float,
    speech_segments: list[tuple[float, float]],
) -> dict:
    """
    Returns a summary dict describing how much was removed.
    """
    output_duration = sum(e - s for s, e in speech_segments)
    removed = original_duration - output_duration
    removed_pct = (removed / original_duration * 100) if original_duration > 0 else 0.0
    return {
        "original_s": original_duration,
        "output_s": output_duration,
        "removed_s": removed,
        "removed_pct": removed_pct,
        "num_cuts": len(speech_segments),
    }
