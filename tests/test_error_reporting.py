"""Unit tests for ErrorReportService.

Verifies:
1. Sensitive data sanitization (passwords, tokens, API keys).
2. Context collection (user details, device details, version, logs, endpoint, HTTP status).
3. Email body structure containing all required diagnostic fields.
4. Deduplication prevents repeated email dispatches for identical errors.
5. Asynchronous dispatch does not block caller execution.
6. Graceful failure handling without raising exceptions.
"""

import time
import unittest
from unittest.mock import patch, MagicMock
from services.error_report_service import ErrorReportService, sanitize_text


class TestErrorReportService(unittest.TestCase):

    def setUp(self):
        self.service = ErrorReportService()

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
        service = self.service
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
        service = self.service
        try:
            raise ValueError("Test runtime failure")
        except ValueError as exc:
            context = service._collect_context(
                error_type="RUNTIME_TEST_ERROR",
                error_message="Test failure occurred",
                exc=exc,
                extra_context={
                    "action": "test_verification",
                    "endpoint": "/tracking/save_activity_batch",
                    "http_status": 500,
                    "response_error": '{"response": "Error", "message": "Server failure"}',
                },
            )

            self.assertEqual(context["error_type"], "RUNTIME_TEST_ERROR")
            self.assertIn("Test failure occurred", context["error_message"])
            self.assertIn("ValueError", context["traceback"])
            self.assertEqual(context["endpoint"], "/tracking/save_activity_batch")
            self.assertEqual(context["http_status"], "500")
            self.assertIn("Server failure", context["response_error"])
            self.assertIn("device_details", context)
            self.assertIn("user_details", context)
            self.assertIn("app_version", context)
            self.assertIn("recent_logs", context)

    def test_build_email_body_formatting(self):
        service = self.service
        context = {
            "app_name": "iHRMS Monitor",
            "app_version": "2.0.1",
            "timestamp_local": "2026-09-08 11:30:00",
            "timestamp_utc": "2026-09-08T06:00:00+00:00",
            "error_type": "ACTIVITY_UPLOAD_ERROR",
            "error_message": "Activity sync batch failed",
            "endpoint": "/tracking/save_activity_batch",
            "http_status": "502",
            "response_error": "Bad Gateway",
            "user_details": {
                "username": "testuser",
                "employee_id": "EMP-100",
                "full_name": "Test User",
                "company_code": "COMP01",
                "role": "Staff",
            },
            "device_details": {
                "hostname": "TEST-PC",
                "os_user": "tester",
                "platform": "Windows",
                "os_release": "11",
                "os_version": "10.0.22631",
                "architecture": "AMD64",
            },
            "traceback": "Traceback: None",
            "extra_context": "{'page': 1}",
            "recent_logs": "2026-09-08 11:29:59 INFO Log test line",
        }

        body = service._build_email_body(context)
        self.assertIn("iHRMS Monitor - Critical Error Report", body)
        self.assertIn("v2.0.1", body)
        self.assertIn("ACTIVITY_UPLOAD_ERROR", body)
        self.assertIn("/tracking/save_activity_batch", body)
        self.assertIn("HTTP Status  : 502", body)
        self.assertIn("Response Err : Bad Gateway", body)
        self.assertIn("EMP-100", body)
        self.assertIn("TEST-PC", body)

    def test_dispatch_email_tries_targets_and_handles_failure(self):
        service = self.service
        context = service._collect_context(
            error_type="MOCK_TEST_ERROR",
            error_message="Mock error for dispatch testing",
        )

        with patch.object(service, "_send_smtp_message", side_effect=Exception("Connection refused")) as mock_send:
            result = service._dispatch_email(context)
            self.assertFalse(result)
            self.assertTrue(mock_send.called)

    def test_report_error_runs_asynchronously(self):
        service = self.service
        unique_sig = f"ASYNC_TEST_{time.time()}"
        with patch.object(service, "_dispatch_email") as mock_dispatch:
            service.report_error(
                error_type=unique_sig,
                error_message="Async non-blocking test",
            )
            # Should not block, thread will run in background
            time.sleep(0.3)
            mock_dispatch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
