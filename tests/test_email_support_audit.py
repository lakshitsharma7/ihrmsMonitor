"""Comprehensive Verification and Audit Test Suite for Workpulse Email/Support Reporting System."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import APP_NAME, APP_VERSION, get_running_app_version
from database.database import init_database
from services.error_report_service import (
    DEFAULT_SUPPORT_EMAIL,
    DEFAULT_SMTP_FROM,
    ErrorReportService,
    sanitize_text,
)
from services.uninstall_reporter import (
    collect_uninstall_context,
    dispatch_uninstall_report,
    get_pending_uninstall_path,
    is_uninstall_pending,
    record_uninstall_event,
)


class TestEmailSupportAudit(unittest.TestCase):
    """End-to-end verification of all existing email and support reporting flows."""

    def setUp(self):
        init_database()
        self.service = ErrorReportService()
        self.service._sent_reports.clear()

    def test_flow_a_support_test_email(self):
        """Test Flow A: Manual support/test email verification."""
        test_type = "Support Mail Verification"
        error_msg = "Workpulse Email Test - Support Mail Verification: This is a test email from Workpulse to verify that the existing support email/reporting mechanism is working correctly."

        ctx = self.service._collect_context(
            error_type="SUPPORT_TEST_EMAIL",
            error_message=error_msg,
            extra_context={
                "test_type": test_type,
                "version": get_running_app_version(),
                "platform": sys.platform,
            },
        )

        self.assertEqual(ctx["error_type"], "SUPPORT_TEST_EMAIL")
        self.assertIn("Workpulse Email Test - Support Mail Verification", ctx["error_message"])
        self.assertEqual(self.service._support_email, DEFAULT_SUPPORT_EMAIL)

        report_text = self.service._build_report_text(ctx)
        self.assertIn("Critical Error Report", report_text)
        self.assertIn("SUPPORT_TEST_EMAIL", report_text)
        self.assertIn(DEFAULT_SUPPORT_EMAIL, self.service._support_email)

        # Verify direct SMTP dispatch
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            delivered = self.service._dispatch_via_smtp(ctx)
            self.assertTrue(delivered)
            mock_smtp_cls.assert_called_once()
            mock_server.ehlo.assert_called()
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with(self.service._smtp_user, self.service._smtp_pass)
            mock_server.send_message.assert_called_once()

    def test_flow_b_application_error_reporting(self):
        """Test Flow B: Application general error reporting."""
        with patch.object(self.service, "_dispatch_via_smtp", return_value=True) as mock_dispatch:
            self.service.report_error(
                error_type="RUNTIME_APPLICATION_ERROR",
                error_message="Unexpected null reference in UI component",
                extra_context={"component": "DashboardWidget"},
            )
            import time
            time.sleep(0.1)
            mock_dispatch.assert_called_once()
            called_ctx = mock_dispatch.call_args[0][0]
            self.assertEqual(called_ctx["error_type"], "RUNTIME_APPLICATION_ERROR")
            self.assertIn("Unexpected null reference", called_ctx["error_message"])

    def test_flow_c_update_failure_reporting(self):
        """Test Flow C: Update check, download, or installation failure reporting."""
        with patch.object(self.service, "_dispatch_via_smtp", return_value=True) as mock_dispatch:
            self.service.report_error(
                error_type="UPDATE_DOWNLOAD_ERROR",
                error_message="Failed to download update installer from https://updates.com/setup.exe: ConnectionReset",
                extra_context={"download_url": "https://updates.com/setup.exe", "target_version": "2.0.0"},
            )
            import time
            time.sleep(0.1)
            mock_dispatch.assert_called_once()
            called_ctx = mock_dispatch.call_args[0][0]
            self.assertEqual(called_ctx["error_type"], "UPDATE_DOWNLOAD_ERROR")
            self.assertIn("https://updates.com/setup.exe", called_ctx["error_message"])

    def test_flow_d_tracking_error_reporting(self):
        """Test Flow D: Activity tracking hook or session failure reporting."""
        with patch.object(self.service, "_dispatch_via_smtp", return_value=True) as mock_dispatch:
            self.service.report_error(
                error_type="TRACKER_HOOK_ERROR",
                error_message="Win32 SetWinEventHook returned 0 (access denied)",
                extra_context={"hook_type": "EVENT_SYSTEM_FOREGROUND"},
            )
            import time
            time.sleep(0.1)
            mock_dispatch.assert_called_once()
            called_ctx = mock_dispatch.call_args[0][0]
            self.assertEqual(called_ctx["error_type"], "TRACKER_HOOK_ERROR")

    def test_flow_e_api_sync_error_reporting(self):
        """Test Flow E: Activity batch sync and network failure reporting."""
        with patch.object(self.service, "_dispatch_via_smtp", return_value=True) as mock_dispatch:
            self.service.report_error(
                error_type="SYNC_BATCH_ERROR",
                error_message="Server returned 500 Internal Server Error during activity batch upload",
                extra_context={"endpoint": "tracking/save_activity_batch", "http_status": 500},
            )
            import time
            time.sleep(0.1)
            mock_dispatch.assert_called_once()
            called_ctx = mock_dispatch.call_args[0][0]
            self.assertEqual(called_ctx["error_type"], "SYNC_BATCH_ERROR")
            self.assertEqual(called_ctx["http_status"], "500")

    def test_flow_f_screenshot_error_reporting(self):
        """Test Flow F: Screenshot capture and upload failure reporting."""
        with patch.object(self.service, "_dispatch_via_smtp", return_value=True) as mock_dispatch:
            self.service.report_error(
                error_type="SCREENSHOT_CAPTURE_ERROR",
                error_message="Screen capture returned None: Graphics device context invalid",
                extra_context={"display_index": 0},
            )
            import time
            time.sleep(0.1)
            mock_dispatch.assert_called_once()
            called_ctx = mock_dispatch.call_args[0][0]
            self.assertEqual(called_ctx["error_type"], "SCREENSHOT_CAPTURE_ERROR")

    def test_flow_g_application_crash_reporting(self):
        """Test Flow G: Application crash / unhandled sys.excepthook reporting."""
        with patch.object(self.service, "_dispatch_via_smtp", return_value=True) as mock_dispatch:
            try:
                raise ZeroDivisionError("division by zero test")
            except Exception as exc:
                self.service.report_error(
                    error_type="APPLICATION_CRASH",
                    error_message=f"Unhandled exception: {exc}",
                    exc=exc,
                )
            import time
            time.sleep(0.1)
            mock_dispatch.assert_called_once()
            called_ctx = mock_dispatch.call_args[0][0]
            self.assertEqual(called_ctx["error_type"], "APPLICATION_CRASH")
            self.assertIn("ZeroDivisionError: division by zero test", called_ctx["traceback"])

    def test_flow_h_uninstall_reporting_and_offline_queue(self):
        """Test Flow H: Application uninstallation detection and offline queued reporting."""
        ctx = collect_uninstall_context(
            employee_id="EMP_001",
            username="test.employee",
            company_code="COMP_TEST",
            device_id="DEV_999",
        )
        self.assertEqual(ctx["employee_id"], "EMP_001")
        self.assertEqual(ctx["username"], "test.employee")
        self.assertEqual(ctx["company_code"], "COMP_TEST")
        self.assertEqual(ctx["event_type"], "APPLICATION_UNINSTALLED")

        # Record to queue file
        q_path = record_uninstall_event(ctx)
        self.assertTrue(q_path.exists())
        self.assertTrue(is_uninstall_pending())

        # When offline, dispatch returns False and file remains
        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp", return_value=False):
            delivered = dispatch_uninstall_report(ctx)
            self.assertFalse(delivered)
            self.assertTrue(q_path.exists())

        # When online, dispatch returns True
        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp", return_value=True):
            delivered = dispatch_uninstall_report(ctx)
            self.assertTrue(delivered)
            # Cleanup
            if q_path.exists():
                q_path.unlink()

    def test_flow_i_sanitization_and_security(self):
        """Test Flow I: Sensitive credential masking in error reports."""
        raw_text = (
            "Login failed for password='SecretPassword123' with token='eyJhbGciOiJIUzI1Ni...' "
            "and api_key=super_secret_key_456 using Authorization: Bearer secret_bearer_token"
        )
        sanitized = sanitize_text(raw_text)
        self.assertNotIn("SecretPassword123", sanitized)
        self.assertNotIn("super_secret_key_456", sanitized)
        self.assertNotIn("secret_bearer_token", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_flow_j_deduplication_and_cooldown(self):
        """Test Flow J: Deduplication suppresses duplicate spam within cooldown."""
        with patch.object(self.service, "_dispatch_via_smtp", return_value=True) as mock_dispatch:
            self.service.report_error("REPEATED_ERROR", "Database lock timeout on table activities")
            import time
            time.sleep(0.05)
            self.assertEqual(mock_dispatch.call_count, 1)

            # Second identical call within cooldown should be suppressed
            self.service.report_error("REPEATED_ERROR", "Database lock timeout on table activities")
            time.sleep(0.05)
            self.assertEqual(mock_dispatch.call_count, 1)

    def test_flow_k_offline_fallback_to_local_log(self):
        """Test Flow K: Offline fallback appends to error_reports.log without raising exceptions."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_log = Path(tmp_dir) / "test_app.log"
            with patch("services.error_report_service.get_log_file_path", return_value=tmp_log):
                with patch.object(self.service, "_dispatch_via_smtp", return_value=False):
                    ctx = self.service._collect_context("OFFLINE_ERROR", "Backend unreachable error")
                    self.service._dispatch_report(ctx)
                    report_log = Path(tmp_dir) / "error_reports.log"
                    self.assertTrue(report_log.exists())
                    content = report_log.read_text(encoding="utf-8")
                    self.assertIn("OFFLINE_ERROR", content)
                    self.assertIn("Backend unreachable error", content)


if __name__ == "__main__":
    unittest.main()
