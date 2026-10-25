import importlib
import json
import logging
import unittest


class LLMFailureDiagnosticTests(unittest.TestCase):
    def setUp(self):
        try:
            self.diagnostics = importlib.import_module("app.diagnostics")
        except ImportError:
            self.fail("Structured LLM failure diagnostics are not implemented yet.")

    def _record_failure(self, error, **kwargs):
        logger_name = "app.llm_diagnostics"
        with self.assertLogs(logger_name, level="WARNING") as captured:
            self.diagnostics.log_agent_failure(
                analysis_id="analysis-123",
                agent_name="Inventory Agent",
                error=error,
                **kwargs,
            )

        return json.loads(captured.output[0].split(":", 2)[2])

    def test_timeout_log_has_safe_structured_fields(self):
        record = self._record_failure(TimeoutError("secret-key and prompt text"))

        self.assertEqual(record["event"], "llm_agent_failure")
        self.assertEqual(record["analysis_id"], "analysis-123")
        self.assertEqual(record["agent_name"], "Inventory Agent")
        self.assertEqual(record["error_type"], "TimeoutError")
        self.assertEqual(record["error_category"], "timeout")

    def test_log_omits_exception_text_and_accepts_explicit_category(self):
        secret_message = "provider response contains secret-key and private prompt"
        record = self._record_failure(
            ValueError(secret_message),
            error_category="invalid_response",
        )
        serialized = json.dumps(record)

        self.assertEqual(record["error_category"], "invalid_response")
        self.assertNotIn("secret-key", serialized)
        self.assertNotIn("private prompt", serialized)
        self.assertNotIn(secret_message, serialized)

    def test_connection_errors_are_classified_without_reading_message(self):
        record = self._record_failure(ConnectionError("sensitive provider detail"))

        self.assertEqual(record["error_category"], "connection")
        self.assertNotIn("sensitive provider detail", json.dumps(record))

    def test_only_retryable_provider_statuses_are_selected(self):
        class ProviderError(Exception):
            def __init__(self, status_code):
                self.status_code = status_code

        for status, category in ((429, "rate_limit"), (503, "server_error")):
            with self.subTest(status=status):
                self.assertEqual(self.diagnostics.retryable_error_category(ProviderError(status)), category)
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.assertIsNone(self.diagnostics.retryable_error_category(ProviderError(status)))


if __name__ == "__main__":
    unittest.main()
