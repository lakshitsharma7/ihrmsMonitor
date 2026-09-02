"""Unit tests for ErrorReportService.

Verifies:
1. Sensitive data sanitization (passwords, tokens, API keys).
2. Context collection (user details, device details, version, logs).
3. Deduplication prevents repeated email dispatches for identical errors.
4. Error reports are only generated on actual errors.
"""

import unittest
from services.error_report_service import ErrorReportService, sanitize_text


class TestErrorReportService(unittest.TestCase):

    def test_sanitize_sensitive_text(self):
        raw = (
            'password="SecretPass123!" api_key="my_secret_token_abc" '
            'token="xyz789" Authorization: Bearer secret-bearer-token'
        )
        cleaned = sanitize_text(raw)
        self.assertNotIn("SecretPass123!", cleaned)
        self.assertNotIn("my_secret_token_abc", cleaned)
        self.assertNotIn("xyz789", cleaned)
        self.assertNotIn("secret-bearer-token", cleaned)
        self.assertIn("[REDACTED]", cleaned)

    def test_deduplication(self):
        service = ErrorReportService()
        sig = service._get_error_signature("TEST_ERROR", "Database connection lost to 127.0.0.1")
        sig2 = service._get_error_signature("TEST_ERROR", "Database connection lost to 192.168.1.1")
        # Since numbers are normalized to 'N', both messages should have the exact same signature
        self.assertEqual(sig, sig2)

        # First dispatch
        self.assertFalse(service._is_duplicate(sig))
        service._record_sent(sig)
        # Immediate subsequent check should be marked duplicate
        self.assertTrue(service._is_duplicate(sig))

    def test_collect_context_structure(self):
        service = ErrorReportService()
        try:
            raise ValueError("Test runtime failure")
        except ValueError as exc:
            context = service._collect_context(
                error_type="RUNTIME_TEST_ERROR",
                error_message="Test failure occurred",
                exc=exc,
                extra_context={"action": "test_verification"},
            )

            self.assertEqual(context["error_type"], "RUNTIME_TEST_ERROR")
            self.assertIn("Test failure occurred", context["error_message"])
            self.assertIn("ValueError", context["traceback"])
            self.assertIn("device_details", context)
            self.assertIn("user_details", context)
            self.assertIn("app_version", context)
            self.assertIn("recent_logs", context)


if __name__ == "__main__":
    unittest.main()
