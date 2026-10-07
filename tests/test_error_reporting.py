"""Unit tests for ErrorReportService.

Verifies:
1. Sensitive data sanitization (passwords, tokens, API keys).
2. Context collection (user details, device details, version, logs, endpoint, HTTP status).
3. Email body structure containing all required diagnostic fields.
4. Deduplication prevents repeated email dispatches for identical errors.
5. Asynchronous dispatch does not block caller execution.
6. Graceful failure handling without raising exceptions.
"""

import sys
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
                    "endpoint": "/workpulse/save_activity_batch",
                    "http_status": 500,
                    "response_error": '{"response": "Error", "message": "Server failure"}',
                },
            )

            self.assertEqual(context["error_type"], "RUNTIME_TEST_ERROR")
            self.assertIn("Test failure occurred", context["error_message"])
            self.assertIn("ValueError", context["traceback"])
            self.assertEqual(context["endpoint"], "/workpulse/save_activity_batch")
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
            "endpoint": "/workpulse/save_activity_batch",
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
        self.assertIn("/workpulse/save_activity_batch", body)
        self.assertIn("HTTP Status", body)
        self.assertIn("502", body)
        self.assertIn("Bad Gateway", body)
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

        # Trigger a workpulse error
        ErrorReportService().report_error(
            error_type="TRACKING_ERROR",
            error_message="Window handle invalid",
        )
        self.assertIn("Error", page.workpulse_status_label.text())
        self.assertIn("Window handle invalid", page.workpulse_status_label.text())


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

    def test_dispatch_via_api_success_and_parameter_mapping(self):
        """Verify that _dispatch_via_api formats and sends all required parameters correctly."""
        import json
        service = self.service
        context = service._collect_context(
            error_type="UPLOAD_FAILED",
            error_message="HTTP 500 from upload_screenshot",
            extra_context={
                "device_token": "ENROLLED_DEVICE_TOKEN_123",
                "severity": "error",
                "error_category": "upload",
                "agent_endpoint": "upload_screenshot",
                "http_status": 500,
                "retry": 3,
                "file_size": 482113,
            },
        )

        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"response": "Success", "status": 200, "message": "Error logged"}
            mock_post.return_value = mock_response

            result = service._dispatch_via_api(context)
            self.assertTrue(result, "API dispatch should return True on HTTP 200.")
            mock_post.assert_called_once()

            call_kwargs = mock_post.call_args[1]
            data = call_kwargs["data"]

            # Verify exact required parameter names
            self.assertEqual(data["device_token"], "ENROLLED_DEVICE_TOKEN_123")
            self.assertEqual(data["error_code"], "UPLOAD_FAILED")
            self.assertEqual(data["error_message"], "HTTP 500 from upload_screenshot")
            self.assertEqual(data["severity"], "error")
            self.assertEqual(data["error_category"], "upload")
            self.assertEqual(data["agent_endpoint"], "upload_screenshot")
            self.assertTrue(bool(data["app_version"]))
            self.assertTrue(bool(data["platform"]))
            self.assertTrue(bool(data["occurred_at"]))

            # Verify error_payload JSON parsing and contents
            payload = json.loads(data["error_payload"])
            self.assertEqual(payload["http_status"], 500)
            self.assertEqual(payload["retry"], 3)
            self.assertEqual(payload["file_size"], 482113)

    def test_dispatch_via_api_handles_server_error_and_timeout(self):
        """Verify that _dispatch_via_api returns False on HTTP 500 or timeout without crashing."""
        import requests
        service = self.service
        context = service._collect_context(
            error_type="SYNC_FAILURE",
            error_message="Server error during sync",
        )

        # 1. HTTP 500
        with patch("requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response

            result = service._dispatch_via_api(context)
            self.assertFalse(result)

        # 2. Timeout
        with patch("requests.post", side_effect=requests.exceptions.Timeout("Timed out")):
            result = service._dispatch_via_api(context)
            self.assertFalse(result)

    def test_dual_dispatch_failure_isolation_api_fails_email_still_sent(self):
        """Failure isolation: If Error API fails, support email must still be attempted and sent."""
        service = self.service
        context = service._collect_context(
            error_type="API_FAIL_ISOLATION",
            error_message="API is down but SMTP should work",
        )

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(service, "_dispatch_via_api", return_value=False) as mock_api, \
             patch.object(service, "_dispatch_via_smtp", return_value=True) as mock_smtp, \
             patch.object(service, "_queue_report") as mock_queue:

            service._dispatch_report(context)

            mock_api.assert_called_once()
            mock_smtp.assert_called_once()
            # Partial success (API failed, SMTP sent) queues report with flags
            mock_queue.assert_called_once()
            queued_ctx = mock_queue.call_args[0][0]
            self.assertFalse(queued_ctx.get("_api_sent"))
            self.assertTrue(queued_ctx.get("_smtp_sent"))

    def test_dual_dispatch_failure_isolation_email_fails_api_still_sent(self):
        """Failure isolation: If support email fails, Error API must still be attempted and sent."""
        service = self.service
        context = service._collect_context(
            error_type="SMTP_FAIL_ISOLATION",
            error_message="SMTP is down but API should work",
        )

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(service, "_dispatch_via_api", return_value=True) as mock_api, \
             patch.object(service, "_dispatch_via_smtp", return_value=False) as mock_smtp, \
             patch.object(service, "_queue_report") as mock_queue:

            service._dispatch_report(context)

            mock_api.assert_called_once()
            mock_smtp.assert_called_once()
            # Partial success (API sent, SMTP failed) queues report with flags
            mock_queue.assert_called_once()
            queued_ctx = mock_queue.call_args[0][0]
            self.assertTrue(queued_ctx.get("_api_sent"))
            self.assertFalse(queued_ctx.get("_smtp_sent"))

    def test_dual_dispatch_both_succeed_no_queueing(self):
        """When both API and SMTP succeed, report is not queued."""
        service = self.service
        context = service._collect_context(
            error_type="FULL_SUCCESS_TEST",
            error_message="Both channels succeed",
        )

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(service, "_dispatch_via_api", return_value=True) as mock_api, \
             patch.object(service, "_dispatch_via_smtp", return_value=True) as mock_smtp, \
             patch.object(service, "_queue_report") as mock_queue:

            service._dispatch_report(context)

            mock_api.assert_called_once()
            mock_smtp.assert_called_once()
            mock_queue.assert_not_called()

    def test_deduplication_prevents_duplicate_dispatches(self):
        """Verify report_error suppresses duplicate error dispatches within cooldown."""
        service = self.service
        unique_sig = f"DEDUP_TEST_{time.time()}"

        with patch.object(service, "_dispatch_report") as mock_dispatch:
            service.report_error(
                error_type=unique_sig,
                error_message="Duplicate test error",
            )
            # Second identical error
            service.report_error(
                error_type=unique_sig,
                error_message="Duplicate test error",
            )

            # Wait briefly for thread execution
            time.sleep(0.1)
            self.assertEqual(mock_dispatch.call_count, 1)

    def test_developer_mode_suppresses_email_and_api(self):
        """Verify normal developer errors in local Python run do NOT dispatch email or API."""
        service = self.service
        context = service._collect_context(
            error_type="DEV_TEST_NORMAL_ERROR",
            error_message="Normal developer error during coding",
        )

        with patch.object(sys, "frozen", False, create=True), \
             patch.dict("os.environ", {}, clear=False):
            # Ensure not production
            self.assertFalse(service.is_production_build())
            self.assertFalse(service.should_send_email(context))
            self.assertFalse(service.should_send_api(context))

            with patch.object(service, "_dispatch_via_smtp") as mock_smtp, \
                 patch.object(service, "_dispatch_via_api") as mock_api, \
                 patch.object(service, "_queue_report") as mock_queue:
                service._dispatch_report(context)
                mock_smtp.assert_not_called()
                mock_api.assert_not_called()
                mock_queue.assert_not_called()

    def test_production_mode_enables_both(self):
        """Verify packaged production build (frozen) dispatches both email and API."""
        service = self.service
        context = service._collect_context(
            error_type="PROD_TEST_REAL_ERROR",
            error_message="Real production error",
        )

        with patch.object(sys, "frozen", True, create=True):
            self.assertTrue(service.is_production_build())
            self.assertTrue(service.should_send_email(context))
            self.assertTrue(service.should_send_api(context))

            with patch.object(service, "_dispatch_via_smtp", return_value=True) as mock_smtp, \
                 patch.object(service, "_dispatch_via_api", return_value=True) as mock_api, \
                 patch.object(service, "_queue_report") as mock_queue:
                service._dispatch_report(context)
                mock_smtp.assert_called_once()
                mock_api.assert_called_once()
                mock_queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()



