import unittest

from app.schemas.ai import ConfidenceLevel, DetectedItem, MeasurementType
from app.services.calculation_service import calculate_quantity
from app.services.takeoff_normalization import normalize_detected_items


def _normalize_one(item: DetectedItem) -> DetectedItem:
    return normalize_detected_items([item])[0]


class WallFinishTests(unittest.TestCase):
    def test_wall_segments_are_summed_into_length(self):
        item = _normalize_one(
            DetectedItem(
                item_name="Stucco",
                measurement_type=MeasurementType.AREA,
                wall_segments=[68.0, 32.8333, 68.0, 32.8333],
                height=9.0,
                unit="sqft",
            )
        )
        self.assertAlmostEqual(item.length, 201.6666, places=3)
        self.assertIsNone(item.width)

        # The stored dimensions must reproduce the quantity (edit contract).
        self.assertAlmostEqual(
            calculate_quantity(item.model_dump()), 201.6666 * 9.0, places=2
        )

    def test_seven_eighths_spec_is_not_used_as_a_length(self):
        # The old bug: "7/8 inch" plaster read as length 78. With segments the
        # length comes from the wall runs, and a stray 0.875 does nothing here.
        item = _normalize_one(
            DetectedItem(
                item_name='Stucco 7/8" cement plaster',
                measurement_type=MeasurementType.AREA,
                wall_segments=[188.5],
                height=8.0,
                unit="sqft",
            )
        )
        self.assertEqual(item.length, 188.5)
        self.assertEqual(calculate_quantity(item.model_dump()), 188.5 * 8.0)


class SlopedRoofTests(unittest.TestCase):
    def test_pitch_scales_length_so_area_is_sloped(self):
        item = _normalize_one(
            DetectedItem(
                item_name="Class A roof",
                measurement_type=MeasurementType.AREA,
                length=50.0,
                width=40.0,
                pitch="4:12",
                unit="sqft",
            )
        )
        # length is scaled by the slope factor; width is untouched.
        self.assertAlmostEqual(item.length, 50.0 * 1.0540925533, places=4)
        self.assertAlmostEqual(
            calculate_quantity(item.model_dump()),
            50.0 * 40.0 * 1.0540925533,
            places=2,
        )

    def test_flat_roof_without_pitch_is_unchanged(self):
        item = _normalize_one(
            DetectedItem(
                item_name="Flat roof",
                measurement_type=MeasurementType.AREA,
                length=50.0,
                width=40.0,
                unit="sqft",
            )
        )
        self.assertEqual(item.length, 50.0)
        self.assertEqual(calculate_quantity(item.model_dump()), 2000.0)


class OpeningDeductionTests(unittest.TestCase):
    def test_openings_are_subtracted_into_net_quantity(self):
        item = _normalize_one(
            DetectedItem(
                item_name="Exterior stucco",
                measurement_type=MeasurementType.AREA,
                wall_segments=[200.0],
                height=9.0,
                openings_sqft=325.0,
                unit="sqft",
            )
        )
        # 200 * 9 = 1800 gross, less 325 openings = 1475 net.
        self.assertEqual(item.quantity, 1475.0)
        # Dimensions are cleared so a later edit does not recompute the gross.
        self.assertIsNone(item.length)
        self.assertIsNone(item.width)
        self.assertIsNone(item.height)

    def test_opening_larger_than_wall_is_flagged_not_negative(self):
        item = _normalize_one(
            DetectedItem(
                item_name="Tiny wall",
                measurement_type=MeasurementType.AREA,
                length=10.0,
                height=9.0,
                openings_sqft=500.0,
                unit="sqft",
            )
        )
        self.assertEqual(item.confidence, ConfidenceLevel.LOW)
        self.assertNotEqual(item.quantity, -410.0)


class ValidationTests(unittest.TestCase):
    def test_implausible_dimension_lowers_confidence(self):
        item = _normalize_one(
            DetectedItem(
                item_name="Mislabeled wall",
                measurement_type=MeasurementType.AREA,
                length=5000.0,
                width=9.0,
                confidence=ConfidenceLevel.HIGH,
                unit="sqft",
            )
        )
        self.assertEqual(item.confidence, ConfidenceLevel.LOW)

    def test_linear_segments_are_summed(self):
        item = _normalize_one(
            DetectedItem(
                item_name="Continuous footing",
                measurement_type=MeasurementType.LINEAR,
                wall_segments=[138.1667, 65.1667, 17.3333, 11.25],
                unit="ft",
            )
        )
        self.assertAlmostEqual(item.length, 231.9167, places=3)

    def test_count_item_is_untouched(self):
        item = _normalize_one(
            DetectedItem(
                item_name="New Window W2",
                measurement_type=MeasurementType.COUNT,
                count=3,
                width=6.0,
                height=4.0,
                unit="ea",
            )
        )
        self.assertEqual(item.count, 3)
        self.assertEqual(calculate_quantity(item.model_dump()), 3)


if __name__ == "__main__":
    unittest.main()
