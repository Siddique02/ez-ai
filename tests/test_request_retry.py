import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.schemas.ai import AIAnalysisResponse
from app.services import ai_service


class RateLimitDetectionTests(unittest.TestCase):
    def test_detects_by_status_code(self):
        exc = SimpleNamespace()
        exc = Exception("boom")
        exc.status_code = 429
        self.assertTrue(ai_service._is_rate_limit(exc))

    def test_detects_by_message(self):
        self.assertTrue(ai_service._is_rate_limit(Exception("rate_limit_exceeded")))
        self.assertFalse(ai_service._is_rate_limit(Exception("bad request")))

    def test_wait_honors_try_again_hint(self):
        wait = ai_service._retry_wait_seconds(
            Exception("Please try again in 1.519s. Visit..."), attempt=0
        )
        self.assertAlmostEqual(wait, 1.519 + 0.25, places=3)

    def test_wait_backs_off_without_hint(self):
        self.assertEqual(ai_service._retry_wait_seconds(Exception("429"), attempt=0), 2.0)
        self.assertEqual(ai_service._retry_wait_seconds(Exception("429"), attempt=1), 4.0)


class RequestRetryTests(unittest.TestCase):
    @patch("app.services.ai_service.time.sleep", return_value=None)
    @patch("app.services.ai_service.client.responses.parse")
    def test_retries_then_succeeds_on_rate_limit(self, parse, _sleep):
        ok = SimpleNamespace(output_parsed=AIAnalysisResponse(items=[]))
        parse.side_effect = [Exception("rate_limit_exceeded"), ok]
        result = ai_service.request_items({}, "instructions", "prompt")
        self.assertEqual(result, ok.output_parsed)
        self.assertEqual(parse.call_count, 2)

    @patch("app.services.ai_service.time.sleep", return_value=None)
    @patch("app.services.ai_service.client.responses.parse")
    def test_non_rate_limit_error_is_not_retried(self, parse, _sleep):
        parse.side_effect = ValueError("bad input")
        with self.assertRaises(ValueError):
            ai_service.request_items({}, "instructions", "prompt")
        self.assertEqual(parse.call_count, 1)


if __name__ == "__main__":
    unittest.main()
