import unittest
from unittest.mock import patch

from app.schemas.ai import (
    AIAnalysisResponse,
    ConfidenceLevel,
    DetectedItem,
    MeasurementType,
)
from app.services import analysis_pipeline
from app.services.analysis_pipeline import (
    EXTRACTION_GROUPS,
    analyze_blueprint_pipeline,
    merge_items,
)


def _item(name, quantity=None, confidence=None):
    return DetectedItem(
        item_name=name,
        measurement_type=MeasurementType.AREA,
        quantity=quantity,
        confidence=confidence,
        unit="sqft",
    )


class MergeItemsTests(unittest.TestCase):
    def test_disjoint_items_are_all_kept_in_order(self):
        merged = merge_items([[_item("Footings")], [_item("Drywall")]])
        self.assertEqual([i.item_name for i in merged], ["Footings", "Drywall"])

    def test_duplicate_keeps_the_one_with_a_quantity(self):
        merged = merge_items(
            [[_item("Stucco", quantity=None)], [_item("stucco", quantity=1500.0)]]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].quantity, 1500.0)

    def test_dedupe_ignores_word_order_and_punctuation(self):
        merged = merge_items(
            [
                [_item("Water Closets (Ultra Flush)", quantity=None)],
                [_item("Ultra Flush Water Closets", quantity=2.0)],
            ]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].quantity, 2.0)

    def test_unrelated_items_stay_distinct(self):
        merged = merge_items([[_item("Exterior Stucco")], [_item("Interior Drywall")]])
        self.assertEqual(len(merged), 2)

    def test_duplicate_prefers_higher_confidence_when_both_quantified(self):
        merged = merge_items(
            [
                [_item("Roof", quantity=2000.0, confidence=ConfidenceLevel.LOW)],
                [_item("roof", quantity=2000.0, confidence=ConfidenceLevel.HIGH)],
            ]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].confidence, ConfidenceLevel.HIGH)


class PipelineOrchestrationTests(unittest.TestCase):
    def test_runs_every_group_and_merges(self):
        calls = []

        def fake_request(file_content, instructions, prompt):
            calls.append(prompt)
            # Name by prompt (unique per group) so the count is stable even when
            # the passes run in parallel threads.
            return AIAnalysisResponse(items=[_item(f"item-{prompt}", 1.0)])

        with patch.object(analysis_pipeline, "build_input_content", return_value={}):
            with patch.object(
                analysis_pipeline, "request_items", side_effect=fake_request
            ):
                result = analyze_blueprint_pipeline("dummy.pdf")

        self.assertEqual(len(calls), len(EXTRACTION_GROUPS))
        self.assertEqual(len(result.items), len(EXTRACTION_GROUPS))

    def test_one_failing_pass_does_not_sink_the_job(self):
        def fake_request(file_content, instructions, prompt):
            if "foundation" in prompt:
                raise RuntimeError("boom")
            # Unique name per pass so merge does not dedupe them together.
            return AIAnalysisResponse(items=[_item(f"ok-{prompt}", 1.0)])

        with patch.object(analysis_pipeline, "build_input_content", return_value={}):
            with patch.object(
                analysis_pipeline, "request_items", side_effect=fake_request
            ):
                result = analyze_blueprint_pipeline("dummy.pdf")

        # 6 groups, 1 failed -> 5 items survive.
        self.assertEqual(len(result.items), len(EXTRACTION_GROUPS) - 1)

    def test_all_passes_failing_raises(self):
        def fake_request(file_content, instructions, prompt):
            raise RuntimeError("boom")

        with patch.object(analysis_pipeline, "build_input_content", return_value={}):
            with patch.object(
                analysis_pipeline, "request_items", side_effect=fake_request
            ):
                with self.assertRaises(ValueError):
                    analyze_blueprint_pipeline("dummy.pdf")


if __name__ == "__main__":
    unittest.main()
