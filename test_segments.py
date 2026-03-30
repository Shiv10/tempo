"""
test_segments.py — Unit tests for segments.py (pure Python logic).
Run with: python -m unittest test_segments.py
"""

import unittest
from segments import (
    compute_stats,
    filter_min_duration,
    invert_silences,
    merge_overlapping,
)

EPS = 1e-9  # floating-point tolerance


def approx_eq(a: float, b: float) -> bool:
    return abs(a - b) < EPS


def segs_approx_eq(
    actual: list[tuple[float, float]],
    expected: list[tuple[float, float]],
) -> bool:
    if len(actual) != len(expected):
        return False
    return all(approx_eq(a[0], b[0]) and approx_eq(a[1], b[1]) for a, b in zip(actual, expected))


class TestInvertSilences(unittest.TestCase):

    def test_basic_inversion(self):
        # Silences at 1-3 and 5-7 in a 10s video, no margin
        result = invert_silences([(1.0, 3.0), (5.0, 7.0)], duration=10.0, margin=0.0)
        self.assertTrue(segs_approx_eq(result, [(0.0, 1.0), (3.0, 5.0), (7.0, 10.0)]))

    def test_silence_at_start(self):
        # Silence from 0-2 → speech starts at 2.0
        result = invert_silences([(0.0, 2.0)], duration=10.0, margin=0.0)
        self.assertTrue(segs_approx_eq(result, [(2.0, 10.0)]))

    def test_silence_at_end(self):
        result = invert_silences([(8.0, 10.0)], duration=10.0, margin=0.0)
        self.assertTrue(segs_approx_eq(result, [(0.0, 8.0)]))

    def test_silence_at_both_ends(self):
        # Silence at start (0-1) and end (9-10) → speech is the middle (1-9)
        result = invert_silences([(0.0, 1.0), (9.0, 10.0)], duration=10.0, margin=0.0)
        self.assertTrue(segs_approx_eq(result, [(1.0, 9.0)]))

    def test_no_silences_returns_full_duration(self):
        result = invert_silences([], duration=10.0, margin=0.0)
        self.assertTrue(segs_approx_eq(result, [(0.0, 10.0)]))

    def test_all_silence(self):
        # Entire video is silent
        result = invert_silences([(0.0, 10.0)], duration=10.0, margin=0.0)
        # No speech segment should be non-empty
        non_empty = [(s, e) for s, e in result if e > s]
        self.assertEqual(non_empty, [])

    def test_margin_expands_segments(self):
        # 0.1s margin should extend each speech segment outward
        result = invert_silences([(2.0, 4.0), (6.0, 8.0)], duration=10.0, margin=0.1)
        # First segment: 0.0 to 2.1
        # Second: 3.9 to 6.1
        # Third: 7.9 to 10.0
        self.assertTrue(segs_approx_eq(result, [(0.0, 2.1), (3.9, 6.1), (7.9, 10.0)]))

    def test_margin_clamped_at_zero(self):
        # margin cannot push start below 0.0
        result = invert_silences([(0.5, 2.0)], duration=10.0, margin=1.0)
        # seg_start = max(0.0, 0.0 - 1.0) = 0.0 (previous end is 0)
        # seg_end = min(10.0, 0.5 + 1.0) = 1.5
        self.assertEqual(result[0][0], 0.0)
        self.assertAlmostEqual(result[0][1], 1.5, places=9)

    def test_margin_clamped_at_duration(self):
        # margin cannot push end beyond duration
        result = invert_silences([(8.0, 9.5)], duration=10.0, margin=1.0)
        # tail: start = max(0.0, 9.5 - 1.0) = 8.5, end = 10.0
        tail = result[-1]
        self.assertAlmostEqual(tail[0], 8.5, places=9)
        self.assertAlmostEqual(tail[1], 10.0, places=9)

    def test_zero_duration(self):
        result = invert_silences([], duration=0.0, margin=0.0)
        self.assertEqual(result, [])

    def test_multiple_silences_no_margin(self):
        silences = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)]
        result = invert_silences(silences, duration=9.0, margin=0.0)
        expected = [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0), (6.0, 7.0), (8.0, 9.0)]
        self.assertTrue(segs_approx_eq(result, expected))


class TestMergeOverlapping(unittest.TestCase):

    def test_no_overlap(self):
        segs = [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]
        self.assertEqual(merge_overlapping(segs), segs)

    def test_overlapping_pair(self):
        segs = [(0.0, 2.0), (1.5, 3.0)]
        self.assertTrue(segs_approx_eq(merge_overlapping(segs), [(0.0, 3.0)]))

    def test_adjacent_segments(self):
        # Exactly touching (end == next start) should merge
        segs = [(0.0, 1.0), (1.0, 2.0)]
        result = merge_overlapping(segs)
        self.assertTrue(segs_approx_eq(result, [(0.0, 2.0)]))

    def test_all_overlapping(self):
        segs = [(0.0, 5.0), (1.0, 3.0), (2.0, 7.0)]
        result = merge_overlapping(segs)
        self.assertTrue(segs_approx_eq(result, [(0.0, 7.0)]))

    def test_empty(self):
        self.assertEqual(merge_overlapping([]), [])

    def test_single(self):
        self.assertEqual(merge_overlapping([(1.0, 2.0)]), [(1.0, 2.0)])

    def test_contained_segment(self):
        # Second segment is fully within first
        segs = [(0.0, 5.0), (1.0, 3.0)]
        result = merge_overlapping(segs)
        self.assertTrue(segs_approx_eq(result, [(0.0, 5.0)]))


class TestFilterMinDuration(unittest.TestCase):

    def test_filters_short_segments(self):
        segs = [(0.0, 0.03), (1.0, 2.0), (3.0, 3.04)]
        result = filter_min_duration(segs, min_dur=0.05)
        self.assertTrue(segs_approx_eq(result, [(1.0, 2.0)]))

    def test_keeps_exactly_min_dur(self):
        segs = [(0.0, 0.05)]
        result = filter_min_duration(segs, min_dur=0.05)
        self.assertEqual(len(result), 1)

    def test_empty(self):
        self.assertEqual(filter_min_duration([], min_dur=0.05), [])

    def test_all_kept(self):
        segs = [(0.0, 1.0), (2.0, 3.0)]
        result = filter_min_duration(segs, min_dur=0.05)
        self.assertEqual(result, segs)

    def test_all_filtered(self):
        segs = [(0.0, 0.01), (1.0, 1.02)]
        result = filter_min_duration(segs, min_dur=0.05)
        self.assertEqual(result, [])


class TestComputeStats(unittest.TestCase):

    def test_basic_stats(self):
        speech = [(0.0, 3.0), (5.0, 8.0), (10.0, 12.0)]
        stats = compute_stats(original_duration=15.0, speech_segments=speech)
        self.assertAlmostEqual(stats["original_s"], 15.0)
        self.assertAlmostEqual(stats["output_s"], 8.0)   # 3 + 3 + 2
        self.assertAlmostEqual(stats["removed_s"], 7.0)
        self.assertAlmostEqual(stats["removed_pct"], 7.0 / 15.0 * 100)
        self.assertEqual(stats["num_cuts"], 3)

    def test_no_speech(self):
        stats = compute_stats(original_duration=10.0, speech_segments=[])
        self.assertAlmostEqual(stats["output_s"], 0.0)
        self.assertAlmostEqual(stats["removed_s"], 10.0)
        self.assertAlmostEqual(stats["removed_pct"], 100.0)
        self.assertEqual(stats["num_cuts"], 0)

    def test_all_speech(self):
        stats = compute_stats(original_duration=10.0, speech_segments=[(0.0, 10.0)])
        self.assertAlmostEqual(stats["removed_s"], 0.0)
        self.assertAlmostEqual(stats["removed_pct"], 0.0)

    def test_zero_duration(self):
        stats = compute_stats(original_duration=0.0, speech_segments=[])
        self.assertAlmostEqual(stats["removed_pct"], 0.0)


class TestEndToEnd(unittest.TestCase):
    """Integration-style tests that run the full pipeline on synthetic data."""

    def test_pipeline_basic(self):
        # Simulate: 10s video, silence at [1-3] and [6-8], margin=0.05
        silences = [(1.0, 3.0), (6.0, 8.0)]
        duration = 10.0
        margin = 0.05

        speech = invert_silences(silences, duration, margin)
        speech = merge_overlapping(speech)
        speech = filter_min_duration(speech)
        stats = compute_stats(duration, speech)

        # Should produce 3 speech segments
        self.assertEqual(stats["num_cuts"], 3)
        # Each segment should respect the margin
        self.assertAlmostEqual(speech[0][1], 1.05, places=9)  # 1.0 + 0.05
        self.assertAlmostEqual(speech[1][0], 2.95, places=9)  # 3.0 - 0.05

    def test_pipeline_video_ends_mid_silence(self):
        # Simulate: silencedetect found start but no end (video ended in silence)
        # detector.py appends duration as the end — simulate that here
        silences = [(8.0, 10.0)]  # already closed
        speech = invert_silences(silences, 10.0, margin=0.0)
        speech = merge_overlapping(speech)
        speech = filter_min_duration(speech)
        # Should only have (0.0, 8.0)
        self.assertEqual(len(speech), 1)
        self.assertAlmostEqual(speech[0][0], 0.0)
        self.assertAlmostEqual(speech[0][1], 8.0)

    def test_pipeline_no_silences(self):
        # No silence detected → single segment covering full duration
        speech = invert_silences([], 15.0, margin=0.05)
        self.assertEqual(len(speech), 1)
        self.assertAlmostEqual(speech[0][0], 0.0)
        self.assertAlmostEqual(speech[0][1], 15.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
