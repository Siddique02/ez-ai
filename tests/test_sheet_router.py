import unittest

from app.services.sheet_router import classify_pages, pages_for_group


class ClassifyPagesTests(unittest.TestCase):
    def test_tags_pages_by_title_keywords(self):
        tags = classify_pages(
            [
                "S-2 FOUNDATION PLAN continuous footing",
                "A-4 ROOF PLAN",
                "A-3 FLOOR PLAN electrical and plumbing symbols",
            ]
        )
        self.assertIn("foundation", tags[0])
        self.assertIn("roofing", tags[1])
        self.assertTrue({"floorplan", "interior", "openings"} <= tags[2])

    def test_untitled_page_has_no_tags(self):
        self.assertEqual(classify_pages([""]), [set()])


class PagesForGroupTests(unittest.TestCase):
    def setUp(self):
        self.classifications = classify_pages(
            [
                "S-2 FOUNDATION PLAN footing slab",   # 0 foundation/structural
                "A-4 ROOF PLAN elevation",            # 1 roofing/envelope
                "A-3 FLOOR PLAN electrical plumbing",  # 2 floorplan/interior/openings/elec/plumb
                "GENERAL NOTES and specifications",   # 3 general
            ]
        )

    def test_foundation_pass_gets_structural_and_general_pages(self):
        pages = pages_for_group(self.classifications, "foundation", 4)
        self.assertIn(0, pages)      # the foundation sheet
        self.assertIn(3, pages)      # general notes ride along
        self.assertNotIn(1, pages)   # the roof sheet is excluded

    def test_mep_pass_gets_the_floor_plan(self):
        pages = pages_for_group(self.classifications, "mep", 4)
        self.assertIn(2, pages)

    def test_unknown_group_falls_back_to_all_pages(self):
        self.assertEqual(pages_for_group(self.classifications, "sitework", 4), [0, 1, 2, 3])

    def test_no_real_match_falls_back_to_all_pages(self):
        # Only a general-notes page present; a pass must not run on notes alone.
        only_general = classify_pages(["GENERAL NOTES"])
        self.assertEqual(pages_for_group(only_general, "foundation", 1), [0])

    def test_empty_classification_falls_back_to_all_pages(self):
        self.assertEqual(pages_for_group([], "foundation", 3), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
