import unittest

from app.services.calculation_service import calculate_quantity


class CalculationServiceTests(unittest.TestCase):
    def test_horizontal_area_uses_length_and_width(self):
        quantity = calculate_quantity(
            {
                "measurement_type": "area",
                "length": 12,
                "width": 8,
                "height": None,
            }
        )

        self.assertEqual(quantity, 96)

    def test_vertical_area_uses_length_and_height(self):
        quantity = calculate_quantity(
            {
                "measurement_type": "area",
                "length": 12,
                "width": None,
                "height": 9,
            }
        )

        self.assertEqual(quantity, 108)

    def test_count_ignores_scheduled_component_dimensions(self):
        quantity = calculate_quantity(
            {
                "measurement_type": "count",
                "count": 7,
                "width": 2.6667,
                "height": 6.6667,
            }
        )

        self.assertEqual(quantity, 7)

    def test_linear_multiplies_length_by_count(self):
        quantity = calculate_quantity(
            {
                "measurement_type": "linear",
                "count": 6,
                "length": 5.0,
            }
        )

        self.assertEqual(quantity, 30)

    def test_area_multiplies_by_count(self):
        quantity = calculate_quantity(
            {
                "measurement_type": "area",
                "count": 3,
                "length": 12,
                "width": 10,
                "height": None,
            }
        )

        self.assertEqual(quantity, 360)


if __name__ == "__main__":
    unittest.main()
