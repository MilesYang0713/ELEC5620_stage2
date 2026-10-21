import json
import os
import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from app.llm_client import LLMRequestError, chat_completion


class LLMClientErrorTests(unittest.TestCase):
    api_key = "sk-test-sensitive-key"
    provider_secret = "provider-internal-sensitive-detail"

    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "OPENAI_API_KEY": self.api_key,
            "OPENAI_BASE_URL": "https://provider.example/v1",
            "OPENAI_MODEL": "qwen-test-model",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def assert_safe_error(self, expected_message, *sensitive_values):
        with self.assertRaises(LLMRequestError) as raised:
            chat_completion("system", "user")

        self.assertEqual(str(raised.exception), expected_message)
        for sensitive_value in sensitive_values:
            self.assertNotIn(sensitive_value, str(raised.exception))

    def test_timeout_returns_safe_connection_message(self):
        with patch("app.llm_client.urlopen", side_effect=TimeoutError(self.provider_secret + self.api_key)):
            self.assert_safe_error(
                "Could not connect to the configured model provider.",
                self.api_key,
                self.provider_secret,
            )

    def test_network_error_returns_safe_connection_message(self):
        with patch("app.llm_client.urlopen", side_effect=URLError(self.provider_secret + self.api_key)):
            self.assert_safe_error(
                "Could not connect to the configured model provider.",
                self.api_key,
                self.provider_secret,
            )

    def test_invalid_key_does_not_expose_provider_error_body(self):
        response_body = json.dumps({"error": {"message": self.provider_secret, "key": self.api_key}}).encode()
        error = HTTPError(
            "https://provider.example/v1/chat/completions",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(response_body),
        )
        with patch("app.llm_client.urlopen", side_effect=error):
            self.assert_safe_error(
                "Model provider returned HTTP 401.",
                self.api_key,
                self.provider_secret,
            )

    def test_server_error_does_not_expose_provider_error_body(self):
        response_body = json.dumps({"error": {"message": self.provider_secret, "key": self.api_key}}).encode()
        error = HTTPError(
            "https://provider.example/v1/chat/completions",
            503,
            "Unavailable",
            hdrs=None,
            fp=BytesIO(response_body),
        )
        with patch("app.llm_client.urlopen", side_effect=error):
            self.assert_safe_error(
                "Model provider returned HTTP 503.",
                self.api_key,
                self.provider_secret,
            )

    def test_invalid_json_returns_safe_format_message(self):
        response = BytesIO(("not-json " + self.provider_secret + " " + self.api_key).encode())
        with patch("app.llm_client.urlopen", return_value=response):
            self.assert_safe_error(
                "The model provider returned an invalid response.",
                self.api_key,
                self.provider_secret,
            )

    def test_missing_completion_shape_returns_safe_format_message(self):
        response = BytesIO(json.dumps({"error": {"message": self.provider_secret, "key": self.api_key}}).encode())
        with patch("app.llm_client.urlopen", return_value=response):
            self.assert_safe_error(
                "The model provider response did not contain a chat completion.",
                self.api_key,
                self.provider_secret,
            )

    def test_empty_completion_returns_safe_empty_response_message(self):
        response = BytesIO(json.dumps({
            "choices": [{"message": {"content": "  "}}],
            "provider_detail": self.provider_secret,
        }).encode())
        with patch("app.llm_client.urlopen", return_value=response):
            self.assert_safe_error(
                "The model returned an empty response.",
                self.api_key,
                self.provider_secret,
            )

    def test_non_string_completion_returns_safe_empty_response_message(self):
        response = BytesIO(json.dumps({
            "choices": [{"message": {"content": {"detail": self.provider_secret}}}],
            "api_key": self.api_key,
        }).encode())
        with patch("app.llm_client.urlopen", return_value=response):
            self.assert_safe_error(
                "The model returned an empty response.",
                self.api_key,
                self.provider_secret,
            )


if __name__ == "__main__":
    unittest.main()
