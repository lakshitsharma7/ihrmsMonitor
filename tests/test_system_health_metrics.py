"""Unit tests for system health metrics in application activity tracking."""

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from database.models import ActivitySession
from services.sync_service import SyncService
from utils.system_health import get_system_health


class TestSystemHealthMetrics(unittest.TestCase):
    def test_get_system_health_structure_and_types(self):
        """Verify get_system_health returns all required fields with appropriate types."""
        health = get_system_health()

        required_keys = [
            "cpu_usage_percent",
            "cpu_logical_cores",
            "ram_usage_percent",
            "ram_total_mb",
            "ram_used_mb",
            "ram_available_mb",
            "disk_usage_percent",
            "disk_total_gb",
            "disk_free_gb",
            "network_status",
            "network_sent_mb",
            "network_received_mb",
        ]

        for key in required_keys:
            self.assertIn(key, health, f"Missing system health key: {key}")

        # Check types
        self.assertIsInstance(health["cpu_usage_percent"], (int, float))
        self.assertIsInstance(health["cpu_logical_cores"], int)
        self.assertGreaterEqual(health["cpu_logical_cores"], 1)

        self.assertIsInstance(health["ram_usage_percent"], (int, float))
        self.assertIsInstance(health["ram_total_mb"], (int, float))
        self.assertIsInstance(health["ram_used_mb"], (int, float))
        self.assertIsInstance(health["ram_available_mb"], (int, float))

        self.assertIsInstance(health["disk_usage_percent"], (int, float))
        self.assertIsInstance(health["disk_total_gb"], (int, float))
        self.assertIsInstance(health["disk_free_gb"], (int, float))

        self.assertIn(health["network_status"], ["connected", "disconnected"])
        self.assertIsInstance(health["network_sent_mb"], (int, float))
        self.assertIsInstance(health["network_received_mb"], (int, float))

    def test_get_system_health_resilience_on_exception(self):
        """Verify get_system_health returns safe defaults if psutil raises exceptions."""
        with patch("psutil.cpu_percent", side_effect=RuntimeError("CPU read error")), \
             patch("psutil.virtual_memory", side_effect=RuntimeError("RAM read error")), \
             patch("psutil.disk_usage", side_effect=RuntimeError("Disk read error")), \
             patch("psutil.net_io_counters", side_effect=RuntimeError("Net read error")):

            health = get_system_health()
            self.assertEqual(health["cpu_usage_percent"], 0.0)
            self.assertEqual(health["ram_usage_percent"], 0.0)
            self.assertEqual(health["disk_usage_percent"], 0.0)
            self.assertEqual(health["network_status"], "disconnected")

    def test_sync_service_build_page_payload_includes_system_health(self):
        """Verify SyncService._build_page_payload attaches system_health to each activity record."""
        sync_svc = SyncService(api_url="https://test.api")
        now = datetime.now(timezone.utc)

        mock_session = MagicMock(spec=ActivitySession)
        mock_session.id = 101
        mock_session.application_name = "Code.exe"
        mock_session.process_id = 4567
        mock_session.window_title = "workspace - Visual Studio Code"
        mock_session.started_at = now - timedelta(minutes=5)
        mock_session.ended_at = now
        mock_session.duration_seconds = 300
        mock_session.idle_seconds = 0

        payload = sync_svc._build_page_payload(
            sessions=[mock_session],
            sync_from=now - timedelta(minutes=5),
            sync_to=now,
            page=1,
            page_size=25,
        )

        self.assertIn("activities", payload)
        self.assertEqual(len(payload["activities"]), 1)
        activity = payload["activities"][0]

        # Verify existing fields are preserved
        self.assertEqual(activity["activity_session_id"], 101)
        self.assertEqual(activity["application_name"], "Code.exe")
        self.assertEqual(activity["process_id"], 4567)
        self.assertEqual(activity["status"], "Active")

        # Verify system_health field is attached
        self.assertIn("system_health", activity)
        sys_health = activity["system_health"]
        self.assertIn("cpu_usage_percent", sys_health)
        self.assertIn("ram_usage_percent", sys_health)
        self.assertIn("disk_usage_percent", sys_health)
        self.assertIn("network_status", sys_health)


if __name__ == "__main__":
    unittest.main()
