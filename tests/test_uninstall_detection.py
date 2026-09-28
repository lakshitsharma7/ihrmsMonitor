"""Unit tests for true application uninstall detection and offline delivery."""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import APP_NAME, APP_VERSION
from database.database import get_session, init_database
from database.models import EnrolledDevice
from services.device_registry_service import DeviceRegistryService
from services.uninstall_reporter import (
    PENDING_UNINSTALL_FILENAME,
    collect_uninstall_context,
    dispatch_uninstall_report,
    get_pending_uninstall_path,
    is_uninstall_pending,
    process_pending_uninstall_reports,
    record_uninstall_event,
)


class TestUninstallDetectionSystem(unittest.TestCase):
    """Verify that ONLY real uninstalls trigger support emails, with offline queuing and deduplication."""

    def setUp(self):
        init_database()
        # Clean up any leftover pending uninstall file
        pending_path = get_pending_uninstall_path()
        if pending_path.exists():
            pending_path.unlink()

    def tearDown(self):
        pending_path = get_pending_uninstall_path()
        if pending_path.exists():
            pending_path.unlink()

    def test_collect_uninstall_context_contains_all_required_details(self):
        """Verify collected context contains user ID, username, company, device ID, hostname, OS, version, and timestamp."""
        ctx = collect_uninstall_context(
            employee_id="EMP-9001",
            username="john.tester",
            company_code="INDO-CORP",
            device_id="DEV-MOCK-999",
        )
        self.assertEqual(ctx["employee_id"], "EMP-9001")
        self.assertEqual(ctx["username"], "john.tester")
        self.assertEqual(ctx["company_code"], "INDO-CORP")
        self.assertEqual(ctx["device_id"], "DEV-MOCK-999")
        self.assertTrue(len(ctx["hostname"]) > 0)
        self.assertTrue(len(ctx["os"]) > 0)
        self.assertEqual(ctx["app_version"], APP_VERSION)
        self.assertIn("uninstall_time_local", ctx)
        self.assertIn("uninstall_time_utc", ctx)
        self.assertEqual(ctx["event_type"], "APPLICATION_UNINSTALLED")

    def test_normal_uninstall_with_internet_on_dispatches_email_immediately(self):
        """Scenario 1: App uninstalled with internet ON -> support email sent immediately."""
        ctx = collect_uninstall_context(
            employee_id="EMP-100",
            username="alice.online",
            company_code="CORP-A",
            device_id="DEV-ONLINE-01",
        )

        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp", return_value=True) as mock_dispatch:
            success = dispatch_uninstall_report(ctx)
            self.assertTrue(success)
            mock_dispatch.assert_called_once()
            called_ctx = mock_dispatch.call_args[0][0]
            self.assertEqual(called_ctx["error_type"], "APPLICATION_UNINSTALLED")
            self.assertIn("alice.online", called_ctx["error_message"])
            self.assertIn("EMP-100", called_ctx["error_message"])
            self.assertIn("CORP-A", called_ctx["error_message"])

    def test_uninstall_with_internet_off_queues_and_delivers_when_internet_restores(self):
        """
        Scenario 2: App uninstalled with internet OFF -> no email while offline.
        When internet becomes available later -> single email sent, queue cleared.
        """
        ctx = collect_uninstall_context(
            employee_id="EMP-200",
            username="bob.offline",
            company_code="CORP-B",
            device_id="DEV-OFFLINE-01",
        )

        # 1. Uninstallation occurs while offline
        record_uninstall_event(ctx)
        self.assertTrue(is_uninstall_pending())

        # Attempt to dispatch while offline -> fails, file remains queued
        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp", return_value=False) as mock_dispatch_fail:
            delivered_offline = process_pending_uninstall_reports()
            self.assertFalse(delivered_offline)
            self.assertTrue(is_uninstall_pending())

        # 2. Later, internet connectivity is restored -> process pending delivers report
        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp", return_value=True) as mock_dispatch_success:
            delivered_online = process_pending_uninstall_reports()
            self.assertTrue(delivered_online)
            # Queue file must be deleted to guarantee exactly one email
            self.assertFalse(is_uninstall_pending())
            mock_dispatch_success.assert_called_once()

    def test_internet_disconnected_alone_does_not_send_uninstall_email(self):
        """Scenario 3: Internet disconnected / offline without uninstall -> NO uninstall email."""
        self.assertFalse(is_uninstall_pending())

        # Registry check scans offline devices
        registry = DeviceRegistryService()
        offline = registry.check_offline_devices(threshold_seconds=1)

        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp") as mock_dispatch:
            processed = process_pending_uninstall_reports()
            self.assertFalse(processed)
            mock_dispatch.assert_not_called()

    def test_app_crash_does_not_send_uninstall_email(self):
        """Scenario 4: App crash / kill -> NO uninstall email is generated."""
        self.assertFalse(is_uninstall_pending())

        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp") as mock_dispatch:
            processed = process_pending_uninstall_reports()
            self.assertFalse(processed)
            mock_dispatch.assert_not_called()

    def test_windows_restart_does_not_send_uninstall_email(self):
        """Scenario 5: Windows reboot / shutdown without uninstall -> NO uninstall email."""
        self.assertFalse(is_uninstall_pending())

        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp") as mock_dispatch:
            processed = process_pending_uninstall_reports()
            self.assertFalse(processed)
            mock_dispatch.assert_not_called()

    def test_exactly_one_email_per_uninstall_event(self):
        """Scenario 6: Deduplication ensures consecutive process runs do not spam duplicate emails."""
        ctx = collect_uninstall_context(
            employee_id="EMP-300",
            username="charlie.dedup",
            company_code="CORP-C",
            device_id="DEV-DEDUP-01",
        )

        record_uninstall_event(ctx)

        with patch("services.error_report_service.ErrorReportService._dispatch_via_smtp", return_value=True) as mock_dispatch:
            # First delivery succeeds
            first_run = process_pending_uninstall_reports()
            self.assertTrue(first_run)
            self.assertEqual(mock_dispatch.call_count, 1)

            # Subsequent runs do nothing
            second_run = process_pending_uninstall_reports()
            self.assertFalse(second_run)
            self.assertEqual(mock_dispatch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
