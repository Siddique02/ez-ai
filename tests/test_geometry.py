import unittest

from app.services.geometry import (
    is_implausible_dimension,
    slope_factor,
    sum_segments,
)


class SlopeFactorTests(unittest.TestCase):
    def test_four_twelve_pitch(self):
        self.assertAlmostEqual(slope_factor("4:12"), 1.0540925533, places=6)

    def test_accepts_slash_and_words(self):
        self.assertAlmostEqual(slope_factor("4/12"), slope_factor("4:12"))
        self.assertAlmostEqual(slope_factor("4 in 12"), slope_factor("4:12"))

    def test_flat_and_missing_pitch_return_one(self):
        self.assertEqual(slope_factor(None), 1.0)
        self.assertEqual(slope_factor("flat"), 1.0)
        self.assertEqual(slope_factor("0:12"), 1.0)

    def test_numeric_pitch_assumes_run_of_twelve(self):
        self.assertAlmostEqual(slope_factor(4), slope_factor("4:12"))


class SumSegmentsTests(unittest.TestCase):
    def test_sums_positive_runs(self):
        self.assertEqual(sum_segments([10.0, 20.0, 5.5]), 35.5)

    def test_ignores_blanks_and_non_positive(self):
        self.assertEqual(sum_segments([10.0, 0, -3, None]), 10.0)

    def test_empty_is_none(self):
        self.assertIsNone(sum_segments([]))
        self.assertIsNone(sum_segments(None))


class ImplausibleDimensionTests(unittest.TestCase):
    def test_normal_dimension_is_fine(self):
        self.assertFalse(is_implausible_dimension(68.0))

    def test_none_is_fine(self):
        self.assertFalse(is_implausible_dimension(None))

    def test_non_positive_is_flagged(self):
        self.assertTrue(is_implausible_dimension(0))
        self.assertTrue(is_implausible_dimension(-5))

    def test_absurdly_large_is_flagged(self):
        self.assertTrue(is_implausible_dimension(5000))


if __name__ == "__main__":
    unittest.main()
