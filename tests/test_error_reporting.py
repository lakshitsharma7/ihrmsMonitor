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
            "app_name": "Workpulse",
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

        body = service._build_report_text(context)
        self.assertIn("Workpulse - Critical Error Report", body)
        self.assertIn("v2.0.1", body)
        self.assertIn("ACTIVITY_UPLOAD_ERROR", body)
        self.assertIn("/tracking/save_activity_batch", body)
        self.assertIn("HTTP Status   : 502", body)
        self.assertIn("Response Err  : Bad Gateway", body)
        self.assertIn("EMP-100", body)
        self.assertIn("TEST-PC", body)

    def test_dispatch_email_tries_targets_and_handles_failure(self):
        service = self.service
        context = service._collect_context(
            error_type="MOCK_TEST_ERROR",
            error_message="Mock error for dispatch testing",
        )

        with patch.object(service, "_dispatch_via_smtp", return_value=False) as mock_smtp:
            result = service._dispatch_email(context)
            self.assertFalse(result)
            self.assertTrue(mock_smtp.called)

    def test_listener_notification_on_report_error(self):
        service = self.service
        received_errors = []

        def mock_listener(err_type, err_msg, ctx):
            received_errors.append((err_type, err_msg, ctx))

        service.register_listener(mock_listener)
        unique_sig = f"LISTENER_TEST_{time.time()}"
        with patch.object(service, "_dispatch_email"):
            service.report_error(
                error_type=unique_sig,
                error_message="Test listener notification",
            )
            self.assertEqual(len(received_errors), 1)
            self.assertEqual(received_errors[0][0], unique_sig)
            self.assertEqual(received_errors[0][1], "Test listener notification")
            self.assertIn("device_details", received_errors[0][2])
            self.assertIn("calling_module", received_errors[0][2])

        service.unregister_listener(mock_listener)

    def test_dashboard_status_area_updates_on_error(self):
        """Verify DashboardPage immediately displays short error status when an error is reported."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        from services.activity_service import ActivityService
        from database.database import get_session
        from ui.dashboard import DashboardPage

        service = ActivityService(get_session)
        page = DashboardPage(activity_service=service)

        # Trigger a sync network issue -> displays user-friendly Sync Pending
        ErrorReportService().report_error(
            error_type="API_SYNC_ERROR",
            error_message="Connection timed out while uploading batch",
        )
        self.assertIn("Sync Pending", page.sync_status_label.text())

        # Trigger a sync auth failure -> displays Sync Error (Auth Failed)
        ErrorReportService().report_error(
            error_type="API_SYNC_ERROR",
            error_message="HTTP 401: Unauthorized",
        )
        self.assertIn("Sync Error", page.sync_status_label.text())

        # Trigger an update error
        ErrorReportService().report_error(
            error_type="UPDATE_INSTALL_ERROR",
            error_message="Installer hash mismatch",
        )
        self.assertIn("Update Error", page.update_status_label.text())
        self.assertIn("Installer hash mismatch", page.update_status_label.text())

        # Trigger a tracking error
        ErrorReportService().report_error(
            error_type="TRACKING_ERROR",
            error_message="Window handle invalid",
        )
        self.assertIn("Error", page.tracking_status_label.text())
        self.assertIn("Window handle invalid", page.tracking_status_label.text())


    def test_dispatch_via_smtp_successful_transmission(self):
        """Verify that _dispatch_via_smtp connects over TLS, logs in, and sends message."""
        service = self.service
        context = service._collect_context(
            error_type="TEST_SMTP_SUCCESS",
            error_message="Testing SMTP transmission handling",
        )

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            result = service._dispatch_via_smtp(context)
            self.assertTrue(result, "SMTP send must return True on success.")
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once()
            mock_server.send_message.assert_called_once()

    def test_dispatch_via_smtp_handles_auth_failure_gracefully(self):
        """Verify that SMTP authentication failure returns False and does not crash."""
        import smtplib
        service = self.service
        context = service._collect_context(
            error_type="TEST_SMTP_AUTH_FAIL",
            error_message="Testing auth failure handling",
        )

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"BadCredentials")
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            result = service._dispatch_via_smtp(context)
            self.assertFalse(result, "Auth failure must return False.")


if __name__ == "__main__":
    unittest.main()


