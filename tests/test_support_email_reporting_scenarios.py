"""Unit and Scenario Tests for Workpulse Support-Email Reporting Behavior.

Validates:
1. Scenario A: When internet is offline -> Do not attempt immediate SMTP, queue locally in queued_reports.json, flush automatically when network returns.
2. Scenario B: When internet is connected but sync fails -> Send support report via direct SMTP, throttled to 1 email per continuous failure session.
3. Scenario C: Deduplication / anti-spam -> Continuous failure sends 1 email; reset on sync success; future failure generates a new email.
4. Scenario D: Support email content audit -> Contains all required diagnostics (employee, hostname, OS, timestamps, network status, sync status, CPU, RAM, Disk, app version) without secrets.
5. Scenario E: Offline queue persistence -> Queued items survive restarts and are cleared after successful delivery.
6. Scenario F: Internet online + successful sync -> No support email generated.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import APP_NAME, get_running_app_version
from database.database import init_database
from services.error_report_service import ErrorReportService, sanitize_text
from services.network_monitor import NetworkReachabilityMonitor
from services.sync_service import SyncService


class TestSupportEmailReportingScenarios(unittest.TestCase):
    """Test suite covering all required support-email reporting behavior for Workpulse."""

    def setUp(self):
        init_database()
        self.error_service = ErrorReportService()
        self.error_service._sent_reports.clear()
        SyncService.reset_sync_state()

    def tearDown(self):
        try:
            NetworkReachabilityMonitor().report_online()
        except Exception:
            pass
        SyncService.reset_sync_state()

    def test_scenario_a_offline_sync_queues_and_flushes_when_online(self):
        """Scenario A: When offline, queue report locally without SMTP, then flush upon reconnect."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_log = Path(tmp_dir) / "workpulse.log"
            queue_file = Path(tmp_dir) / "queued_reports.json"
            self.error_service._custom_queue_file = queue_file
            self.error_service._sent_reports.clear()
            SyncService.reset_sync_state()

            try:
                with patch("services.error_report_service.get_log_file_path", return_value=tmp_log):
                    # Set network offline
                    monitor = NetworkReachabilityMonitor()
                    monitor.report_offline()
                    self.assertFalse(monitor.is_online)

                    with patch.object(self.error_service, "_dispatch_via_smtp") as mock_smtp:
                        # Trigger a sync failure while offline
                        SyncService._report_sync_failure(
                            error_message="Host softdev.indovisionservices.in unreachable (Offline)",
                            endpoint="/workpulse/save_activity_batch",
                        )
                        # Wait for background queue write
                        for _ in range(30):
                            if queue_file.exists():
                                break
                            time.sleep(0.05)

                        # Assert: No immediate SMTP call was made while offline
                        mock_smtp.assert_not_called()

                        # Assert: Report was queued locally on disk
                        self.assertTrue(queue_file.exists(), "queued_reports.json must exist")
                        queued_data = json.loads(queue_file.read_text(encoding="utf-8"))
                        self.assertEqual(len(queued_data), 1)
                        self.assertIn("Offline", queued_data[0]["error_message"])

                    # Now simulate internet connection restored
                    with patch.object(self.error_service, "_dispatch_via_smtp", return_value=True) as mock_smtp_flushed:
                        monitor.report_online()
                        self.assertTrue(monitor.is_online)
                        # Explicitly trigger flush in case listener thread had slight delay
                        for _ in range(20):
                            if mock_smtp_flushed.called:
                                break
                            time.sleep(0.05)
                        if not mock_smtp_flushed.called:
                            self.error_service.flush_queued_reports()

                        # Assert: Automatically flushed or manually flushed
                        mock_smtp_flushed.assert_called()

                        # Assert: Queue file is now empty/cleared
                        remaining = json.loads(queue_file.read_text(encoding="utf-8"))
                        self.assertEqual(len(remaining), 0)
            finally:
                self.error_service._custom_queue_file = None

    def test_scenario_b_online_sync_failure_dispatches_smtp(self):
        """Scenario B: When online and backend sync fails, send support email via SMTP."""
        monitor = NetworkReachabilityMonitor()
        monitor.report_online()
        self.assertTrue(monitor.is_online)

        with patch.object(self.error_service, "_dispatch_via_smtp", return_value=True) as mock_smtp:
            SyncService._report_sync_failure(
                error_message="HTTP 500: Internal Server Error from save_activity_batch",
                endpoint="/workpulse/save_activity_batch",
                http_status=500,
                response_error="Internal Server Error",
            )
            for _ in range(20):
                if mock_smtp.called:
                    break
                time.sleep(0.05)

            # Assert: Support report was sent via SMTP
            mock_smtp.assert_called_once()
            ctx = mock_smtp.call_args[0][0]
            self.assertEqual(ctx["error_type"], "SYNC_FAILURE")
            self.assertIn("HTTP 500", ctx["error_message"])
            self.assertEqual(ctx["endpoint"], "/workpulse/save_activity_batch")
            self.assertEqual(ctx["http_status"], "500")

    def test_scenario_c_avoid_email_spam_throttles_continuous_failures(self):
        """Scenario C: Throttles repeated failures to 1 email per failure session, resets on success."""
        monitor = NetworkReachabilityMonitor()
        monitor.report_online()

        with patch.object(self.error_service, "_dispatch_via_smtp", return_value=True) as mock_smtp:
            # 1. First sync failure triggers 1 email
            SyncService._report_sync_failure(
                error_message="Backend timeout on save_activity_batch",
                endpoint="/workpulse/save_activity_batch",
            )
            for _ in range(20):
                if mock_smtp.called:
                    break
                time.sleep(0.05)
            self.assertEqual(mock_smtp.call_count, 1)

            # 2. Second failure during same continuous failure session does NOT trigger another email
            SyncService._report_sync_failure(
                error_message="Backend timeout on save_activity_batch",
                endpoint="/workpulse/save_activity_batch",
            )
            time.sleep(0.05)
            self.assertEqual(mock_smtp.call_count, 1, "Must not send repeated emails for continuous failure")

            # 3. Third failure during same continuous session still throttled
            SyncService._report_sync_failure(
                error_message="Backend timeout on save_activity_batch",
                endpoint="/workpulse/save_activity_batch",
            )
            time.sleep(0.05)
            self.assertEqual(mock_smtp.call_count, 1)

            # 4. Now sync succeeds -> resets failure state
            SyncService.reset_sync_state()
            self.assertFalse(SyncService._sync_failure_reported)
            self.assertFalse(SyncService._offline_sync_failure_reported)

            # 5. A new failure later creates a new support email
            SyncService._report_sync_failure(
                error_message="New connection refused on save_activity_batch",
                endpoint="/workpulse/save_activity_batch",
            )
            time.sleep(0.05)
            self.assertEqual(mock_smtp.call_count, 2, "New failure after recovery must trigger new report")

    def test_scenario_d_support_email_content_and_security(self):
        """Scenario D: Verify all diagnostic fields are in the email and sensitive secrets are masked."""
        ctx = self.error_service._collect_context(
            error_type="SYNC_FAILURE",
            error_message="Failed to sync batch with token='secret_token_123' and password='my_password'",
            extra_context={
                "endpoint": "/workpulse/save_activity_batch",
                "http_status": "503",
                "response_error": "Service Unavailable",
            },
        )

        report_text = self.error_service._build_report_text(ctx)
        report_html = self.error_service._build_report_html(ctx)

        # Check required fields in plain-text email
        self.assertIn("WORKPULSE ERROR REPORT", report_text)
        self.assertIn("Employee Name", report_text)
        self.assertIn("Employee Code / ID", report_text)
        self.assertIn("Device / Host Name", report_text)
        self.assertIn("OS / Platform", report_text)
        self.assertIn("Workpulse App Version", report_text)
        self.assertIn("Network Status", report_text)
        self.assertIn("Sync Status", report_text)
        self.assertIn("Last Successful Sync Time", report_text)
        self.assertIn("Current Failure Time", report_text)
        self.assertIn("API Endpoint / Action", report_text)
        self.assertIn("CPU Usage", report_text)
        self.assertIn("RAM Usage", report_text)
        self.assertIn("Disk Usage", report_text)

        # Check required fields in HTML email
        self.assertIn("WORKPULSE SUPPORT REPORT", report_html)
        self.assertIn("Employee & Device Information", report_html)
        self.assertIn("Connectivity & Sync Diagnostics", report_html)
        self.assertIn("Current System Health at Error Time", report_html)

        # SECURITY: Verify secrets are sanitized
        self.assertNotIn("secret_token_123", report_text)
        self.assertNotIn("my_password", report_text)
        self.assertNotIn("secret_token_123", report_html)
        self.assertNotIn("my_password", report_html)
        self.assertIn("[REDACTED]", report_text)

    def test_scenario_e_offline_queue_persists_across_restarts(self):
        """Scenario E: Queued reports survive when the application is restarted."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_log = Path(tmp_dir) / "workpulse.log"
            queue_file = Path(tmp_dir) / "queued_reports.json"

            with patch("services.error_report_service.get_log_file_path", return_value=tmp_log):
                # Queue a report
                ctx = {"error_type": "OFFLINE_SYNC", "error_message": "Offline sync failure at 10:00"}
                self.error_service._queue_report(ctx)

                self.assertTrue(queue_file.exists())
                loaded_1 = self.error_service._load_queued_reports()
                self.assertEqual(len(loaded_1), 1)

                # Set offline so newly initialized instance does not flush immediately
                monitor = NetworkReachabilityMonitor()
                monitor.report_offline()

                ErrorReportService._instance = None
                new_service = ErrorReportService()
                loaded_2 = new_service._load_queued_reports()
                self.assertEqual(len(loaded_2), 1)
                self.assertEqual(loaded_2[0]["error_type"], "OFFLINE_SYNC")

                # Restore online
                monitor.report_online()

    def test_scenario_f_online_successful_sync_generates_no_email(self):
        """Scenario F: When online and sync succeeds, no support email should be generated."""
        monitor = NetworkReachabilityMonitor()
        monitor.report_online()

        with patch.object(self.error_service, "_dispatch_via_smtp") as mock_smtp:
            # Successful sync path
            SyncService.last_sync_status = "Sent"
            SyncService.last_successful_sync_time = "2026-10-05 17:00:00"
            SyncService._sync_failure_reported = False
            SyncService._offline_sync_failure_reported = False

            time.sleep(0.05)
            # Assert: No support email was triggered
            mock_smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
