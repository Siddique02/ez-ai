import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app.core.config import settings
from app.schemas.ai import AIAnalysisResponse, DetectedItem
from app.services.ai_service import analyze_blueprint


class AIServiceTests(unittest.TestCase):
    @staticmethod
    def _parsed_result() -> AIAnalysisResponse:
        return AIAnalysisResponse(
            items=[
                DetectedItem(
                    item_name="Window W1",
                    measurement_type="count",
                    width=4,
                    height=4,
                    count=4,
                    unit="ea",
                    confidence="high",
                )
            ]
        )

    @patch("app.services.ai_service.settings.analysis_mode", "single")
    @patch("app.services.ai_service.client.responses.parse")
    def test_pdf_is_sent_directly_with_high_detail(self, parse_response):
        parsed_result = self._parsed_result()
        parse_response.return_value = SimpleNamespace(output_parsed=parsed_result)

        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "plan.pdf"
            pdf_bytes = b"%PDF-1.7 test blueprint"
            pdf_path.write_bytes(pdf_bytes)

            result = analyze_blueprint(str(pdf_path))

        self.assertIs(result, parsed_result)
        kwargs = parse_response.call_args.kwargs
        self.assertEqual(kwargs["model"], settings.llm_model)
        self.assertIs(kwargs["text_format"], AIAnalysisResponse)
        # temperature is intentionally not sent, so reasoning models that
        # reject it (e.g. the GPT-6 reasoning tier) still accept the call.
        self.assertNotIn("temperature", kwargs)
        self.assertFalse(kwargs["store"])
        self.assertIn("first value is width", kwargs["instructions"])
        self.assertIn("do not put\n  dimensions in item_name", kwargs["instructions"])

        file_content = kwargs["input"][0]["content"][0]
        self.assertEqual(file_content["type"], "input_file")
        self.assertEqual(file_content["filename"], "plan.pdf")
        self.assertEqual(file_content["detail"], "high")
        self.assertEqual(
            file_content["file_data"],
            "data:application/pdf;base64,"
            + base64.b64encode(pdf_bytes).decode("utf-8"),
        )

    @patch("app.services.ai_service.client.responses.parse")
    def test_image_keeps_its_real_mime_type(self, parse_response):
        parse_response.return_value = SimpleNamespace(
            output_parsed=self._parsed_result()
        )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "plan.jpg"
            image_path.write_bytes(b"jpeg image bytes")

            analyze_blueprint(str(image_path))

        image_content = parse_response.call_args.kwargs["input"][0]["content"][0]
        self.assertEqual(image_content["type"], "input_image")
        self.assertEqual(image_content["detail"], "high")
        self.assertTrue(
            image_content["image_url"].startswith("data:image/jpeg;base64,")
        )

    @patch("app.services.ai_service.client.responses.parse")
    def test_missing_parsed_output_is_rejected(self, parse_response):
        parse_response.return_value = SimpleNamespace(output_parsed=None)

        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "plan.pdf"
            pdf_path.write_bytes(b"%PDF-1.7")

            with self.assertRaisesRegex(ValueError, "parsed takeoff result"):
                analyze_blueprint(str(pdf_path))

    @patch("app.services.ai_service.client.responses.parse")
    def test_unsupported_file_type_is_rejected_before_api_call(
        self,
        parse_response,
    ):
        with tempfile.TemporaryDirectory() as directory:
            text_path = Path(directory) / "plan.txt"
            text_path.write_text("not a blueprint", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Unsupported blueprint"):
                analyze_blueprint(str(text_path))

        parse_response.assert_not_called()


if __name__ == "__main__":
    unittest.main()
