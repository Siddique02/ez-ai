import unittest

from app.eval.scorer import GoldItem, score_takeoff


class ScorerTests(unittest.TestCase):
    def test_split_items_are_summed_for_one_gold_line(self):
        gold = [GoldItem("slab", "Slab", "sqft", 1600.0, ("slab",), tol=0.1)]
        produced = [
            {"item_name": "Concrete Slab House", "unit": "sqft", "quantity": 1200.0},
            {"item_name": "Concrete Slab Garage", "unit": "sqft", "quantity": 400.0},
        ]
        report = score_takeoff(produced, gold)
        self.assertEqual(report.lines[0].produced_quantity, 1600.0)
        self.assertTrue(report.lines[0].within_tolerance)
        self.assertEqual(report.overall, 100.0)

    def test_missing_scope_is_not_found(self):
        gold = [GoldItem("drywall", "Drywall", "sqft", 5000.0, ("drywall",))]
        report = score_takeoff([], gold)
        self.assertFalse(report.lines[0].found)
        self.assertEqual(report.coverage, 0.0)
        self.assertEqual(report.overall, 0.0)

    def test_found_but_out_of_tolerance_counts_as_found_not_correct(self):
        gold = [GoldItem("roof", "Roof", "sqft", 2000.0, ("roof",), tol=0.1)]
        produced = [{"item_name": "Roof shingles", "unit": "sqft", "quantity": 1200.0}]
        report = score_takeoff(produced, gold)
        self.assertTrue(report.lines[0].found)
        self.assertFalse(report.lines[0].within_tolerance)
        self.assertEqual(report.coverage, 1.0)
        self.assertEqual(report.accuracy, 0.0)

    def test_null_quantity_match_is_found_but_wrong(self):
        gold = [GoldItem("footings", "Footings", "ft", 230.0, ("footing",))]
        produced = [{"item_name": "Concrete Footings", "unit": "ft", "quantity": None}]
        report = score_takeoff(produced, gold)
        # Named but unquantified: it should not score as a correct hit.
        self.assertFalse(report.lines[0].within_tolerance)

    def test_wrong_unit_does_not_match(self):
        gold = [GoldItem("stucco", "Stucco", "sqft", 1500.0, ("stucco",))]
        produced = [{"item_name": "Stucco", "unit": "ft", "quantity": 1500.0}]
        report = score_takeoff(produced, gold)
        self.assertFalse(report.lines[0].found)

    def test_exclude_blocks_a_broad_keyword_collision(self):
        gold = [
            GoldItem("slab", "Slab", "sqft", 1600.0, ("slab",), tol=0.1,
                     exclude=("vapor", "reinforc"))
        ]
        produced = [
            {"item_name": "Concrete Slab", "unit": "sqft", "quantity": 1600.0},
            {"item_name": "Under-slab Vapor Barrier", "unit": "sqft", "quantity": 1600.0},
            {"item_name": "Slab Reinforcing", "unit": "sqft", "quantity": 1600.0},
        ]
        report = score_takeoff(produced, gold)
        # Only the real slab counts; the excluded look-alikes are ignored.
        self.assertEqual(report.lines[0].produced_quantity, 1600.0)
        self.assertTrue(report.lines[0].within_tolerance)

    def test_count_tolerance_allows_off_by_one(self):
        gold = [GoldItem("smoke", "Smoke", "ea", 4, ("smoke",), tol=0.0, abs_tol=1.0)]
        produced = [{"item_name": "Smoke detectors", "unit": "ea", "quantity": 5}]
        report = score_takeoff(produced, gold)
        self.assertTrue(report.lines[0].within_tolerance)


if __name__ == "__main__":
    unittest.main()
