"""Unit tests for Windows EXE auto-update verification and device fleet tracking."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from config.settings import get_running_app_version
from database.database import get_session, init_database
from database.models import EnrolledDevice
from services.device_registry_service import DeviceRegistryService, OFFLINE_THRESHOLD_SECONDS


class TestDeviceVerificationSystem(unittest.TestCase):
    """Test suite verifying device tracking, version comparison, and update status evaluation."""

    def setUp(self):
        init_database()
        self.registry = DeviceRegistryService()
        # Clean up test table records
        db = get_session()
        try:
            db.query(EnrolledDevice).delete()
            db.commit()
        finally:
            db.close()

    def test_running_exe_reports_authoritative_version_not_hardcoded(self):
        """Verify device heartbeat records real get_running_app_version() instead of a static string."""
        with patch("services.device_registry_service.get_running_app_version", return_value="1.0.5"):
            dev = self.registry.record_heartbeat(
                device_identifier="TEST-DEVICE-001",
                hostname="Laptop-Alpha",
                employee_id="EMP-101",
                username="john.doe",
            )
            self.assertEqual(dev.installed_version, "1.0.5")
            self.assertEqual(dev.hostname, "Laptop-Alpha")
            self.assertEqual(dev.device_identifier, "TEST-DEVICE-001")

    def test_status_updated_only_when_running_exe_reports_new_version(self):
        """
        Verify device is NOT considered Updated just because latest version is available on server.
        Must be marked Updated ONLY when the installed/running version is >= server version.
        """
        now = datetime.now(timezone.utc)

        # Case 1: Server has 1.0.2, laptop still running 1.0.1 -> Update Pending
        status = DeviceRegistryService.calculate_device_status(
            installed_version="1.0.1",
            latest_version="1.0.2",
            last_seen=now,
        )
        self.assertEqual(status, "Update Pending")

        # Case 2: Laptop updates and restarts, now reports running 1.0.2 -> Update Successful
        status_after_update = DeviceRegistryService.calculate_device_status(
            installed_version="1.0.2",
            latest_version="1.0.2",
            last_seen=now,
        )
        self.assertEqual(status_after_update, "Update Successful")

        # Case 3: Laptop running newer hotfix 1.0.3 vs server 1.0.2 -> Update Successful
        status_hotfix = DeviceRegistryService.calculate_device_status(
            installed_version="1.0.3",
            latest_version="1.0.2",
            last_seen=now,
        )
        self.assertEqual(status_hotfix, "Update Successful")

    def test_status_update_failed_records_and_displays_failure_reason(self):
        """Verify failed update transitions device to Update Error and stores the reason."""
        dev_id = "TEST-LAPTOP-FAIL"
        self.registry.record_heartbeat(
            device_identifier=dev_id,
            hostname="Laptop-Beta",
            installed_version="1.0.0",
        )

        error_reason = "Pre-update flush failed: 2 pending activities timed out"
        self.registry.record_update_failure(
            reason=error_reason,
            device_identifier=dev_id,
            target_version="1.0.1",
        )

        devices = self.registry.get_all_devices()
        dev_entry = next(d for d in devices if d["device_identifier"] == dev_id)

        self.assertEqual(dev_entry["update_status"], "Update Error")
        self.assertEqual(dev_entry["failure_reason"], error_reason)
        self.assertEqual(dev_entry["latest_version"], "1.0.1")

    def test_status_offline_when_not_recently_seen(self):
        """Verify device is marked Offline / Not Recently Seen when heartbeat exceeds threshold."""
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=OFFLINE_THRESHOLD_SECONDS + 300)

        status = DeviceRegistryService.calculate_device_status(
            installed_version="1.0.0",
            latest_version="1.0.1",
            last_seen=stale_time,
        )
        self.assertEqual(status, "Offline / Not Recently Seen")

    def test_complete_update_flow_across_fleet(self):
        """
        Simulate fleet with 4 laptops:
        1. Laptop-A: Updated (running 1.0.2)
        2. Laptop-B: Update Pending (running 1.0.0, server 1.0.2)
        3. Laptop-C: Update Failed (download corrupt)
        4. Laptop-D: Offline (> 2 hours ago)
        """
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=3)

        # 1. Laptop A
        self.registry.record_heartbeat(
            device_identifier="DEV-A",
            hostname="Laptop-A",
            installed_version="1.0.2",
            latest_version="1.0.2",
        )

        # 2. Laptop B
        self.registry.record_heartbeat(
            device_identifier="DEV-B",
            hostname="Laptop-B",
            installed_version="1.0.0",
            latest_version="1.0.2",
        )

        # 3. Laptop C
        self.registry.record_heartbeat(
            device_identifier="DEV-C",
            hostname="Laptop-C",
            installed_version="1.0.0",
            latest_version="1.0.2",
        )
        self.registry.record_update_failure(
            reason="Downloaded installer checksum invalid",
            device_identifier="DEV-C",
            target_version="1.0.2",
        )

        # 4. Laptop D (Offline)
        db = get_session()
        try:
            d = EnrolledDevice(
                device_identifier="DEV-D",
                hostname="Laptop-D",
                platform="Windows",
                installed_version="1.0.0",
                latest_version="1.0.2",
                last_seen=past,
            )
            db.add(d)
            db.commit()
        finally:
            db.close()

        summary = self.registry.get_device_summary()
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["offline"], 1)

        # Now simulate Laptop B completing the update, restarting, and reporting new version 1.0.2
        self.registry.record_update_success(new_version="1.0.2", device_identifier="DEV-B")

        updated_summary = self.registry.get_device_summary()
        self.assertEqual(updated_summary["updated"], 2)
        self.assertEqual(updated_summary["pending"], 0)

    def test_verification_cli_script_execution(self):
        """Test the standalone verify_device_updates CLI script."""
        from scripts.verify_device_updates import print_fleet_verification_report
        import io
        from contextlib import redirect_stdout
        # Execute report generator in json mode
        with redirect_stdout(io.StringIO()):
            exit_code = print_fleet_verification_report(as_json=True, check_offline=True)
            self.assertEqual(exit_code, 0)

    def test_offline_detection_within_grace_period(self):
        """Verify brief disconnection within threshold grace period does not mark device offline."""
        dev_id = "DEV-SHORT-OUTAGE"
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=10)

        db = get_session()
        try:
            d = EnrolledDevice(
                device_identifier=dev_id,
                hostname="Laptop-Grace",
                platform="Windows",
                employee_id="EMP-301",
                username="grace.user",
                installed_version="2.0.1",
                last_seen=recent_time,
            )
            db.add(d)
            db.commit()
        finally:
            db.close()

        offline = self.registry.check_offline_devices(threshold_seconds=7200)
        self.assertEqual(len(offline), 0)

    def test_offline_detection_beyond_threshold_flags_device(self):
        """Verify device inactive past threshold is detected in offline fleet scan."""
        dev_id = "DEV-INACTIVE-01"
        stale_time = datetime.now(timezone.utc) - timedelta(hours=3)

        db = get_session()
        try:
            d = EnrolledDevice(
                device_identifier=dev_id,
                hostname="LAPTOP-DEV-01",
                platform="Windows",
                os_username="corp_user",
                employee_id="EMP-999",
                username="alex.smith",
                installed_version="2.0.1",
                last_seen=stale_time,
            )
            db.add(d)
            db.commit()
        finally:
            db.close()

        offline = self.registry.check_offline_devices(threshold_seconds=7200)
        self.assertEqual(len(offline), 1)
        self.assertEqual(offline[0]["device_identifier"], dev_id)
        self.assertEqual(offline[0]["username"], "alex.smith")
        self.assertEqual(offline[0]["employee_id"], "EMP-999")
        self.assertEqual(offline[0]["hostname"], "LAPTOP-DEV-01")

    def test_device_reconnect_restores_online_status(self):
        """Verify device resuming heartbeat resets offline tracking state."""
        dev_id = "DEV-RECONNECTING"
        stale_time = datetime.now(timezone.utc) - timedelta(hours=5)

        db = get_session()
        try:
            d = EnrolledDevice(
                device_identifier=dev_id,
                hostname="LAPTOP-RECONNECT",
                platform="Windows",
                employee_id="EMP-777",
                username="sarah.connor",
                installed_version="2.0.1",
                last_seen=stale_time,
            )
            db.add(d)
            db.commit()
        finally:
            db.close()

        # 1. Device is detected offline
        offline_1 = self.registry.check_offline_devices(threshold_seconds=7200)
        self.assertEqual(len(offline_1), 1)

        # 2. Device comes back online and sends heartbeat
        self.registry.record_heartbeat(
            device_identifier=dev_id,
            hostname="LAPTOP-RECONNECT",
            employee_id="EMP-777",
            username="sarah.connor",
            installed_version="2.0.1",
        )
        self.assertNotIn(dev_id, self.registry.get_offline_alerted_devices())


if __name__ == "__main__":
    unittest.main()
