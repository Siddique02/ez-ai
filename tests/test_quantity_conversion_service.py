import unittest
from types import SimpleNamespace

from app.services.quantity_conversion_service import (
    QuantityConversionError,
    calculate_catalog_quantity,
    normalize_unit,
)


class QuantityConversionServiceTests(unittest.TestCase):
    def test_each_uses_count(self):
        item = SimpleNamespace(
            count=4,
            quantity=4,
            measurement_type="count",
            width=None,
            height=None,
            length=None,
        )

        self.assertEqual(calculate_catalog_quantity(item, "ea"), 4)

    def test_square_feet_uses_counted_component_dimensions(self):
        item = SimpleNamespace(
            count=4,
            quantity=4,
            measurement_type="count",
            width=6,
            height=4,
            length=None,
        )

        self.assertEqual(calculate_catalog_quantity(item, "sqft"), 96)

    def test_area_quantity_is_used_for_square_feet(self):
        item = SimpleNamespace(
            count=None,
            quantity=1240,
            measurement_type="area",
            width=None,
            height=None,
            length=None,
        )

        self.assertEqual(calculate_catalog_quantity(item, "sf"), 1240)

    def test_square_is_one_hundred_square_feet(self):
        item = SimpleNamespace(
            count=None,
            quantity=1250,
            measurement_type="area",
            width=None,
            height=None,
            length=None,
        )

        self.assertEqual(calculate_catalog_quantity(item, "square"), 12.5)

    def test_linear_feet_multiply_length_by_count(self):
        item = SimpleNamespace(
            count=6,
            quantity=6,
            measurement_type="count",
            width=None,
            height=None,
            length=5.0,
        )

        self.assertEqual(calculate_catalog_quantity(item, "lf"), 30)

    def test_linear_feet_without_count_use_length(self):
        item = SimpleNamespace(
            count=None,
            quantity=120,
            measurement_type="linear",
            width=None,
            height=None,
            length=120.0,
        )

        self.assertEqual(calculate_catalog_quantity(item, "ft"), 120)

    def test_unit_spelling_variants_are_normalized(self):
        self.assertEqual(normalize_unit("Sq. Ft."), "sqft")
        self.assertEqual(normalize_unit("s.f."), "sqft")
        self.assertEqual(normalize_unit(" L.F. "), "ft")
        self.assertEqual(normalize_unit("Linear Feet"), "ft")
        self.assertEqual(normalize_unit("PCS"), "ea")

    def test_malformed_units_are_not_guessed(self):
        for unit in ("sqdt", "totak", "123", "15 sqft", "6ft", "mh", "ls"):
            with self.subTest(unit=unit):
                self.assertIsNone(normalize_unit(unit))

    def test_unsupported_catalog_unit_is_rejected(self):
        item = SimpleNamespace(
            count=1,
            quantity=1,
            measurement_type="count",
            width=None,
            height=None,
            length=None,
        )

        with self.assertRaises(QuantityConversionError):
            calculate_catalog_quantity(item, "LS")


if __name__ == "__main__":
    unittest.main()
