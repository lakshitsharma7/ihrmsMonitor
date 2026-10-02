"""Unit tests for system health metrics in application activity workpulse."""

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
        self.assertIn("cpu", sys_health)
        self.assertIn("ram", sys_health)
        self.assertIn("disk", sys_health)
        self.assertIn("os", sys_health)
        self.assertIn("hostname", sys_health)
        self.assertIn("usage_percent", sys_health["cpu"])
        self.assertIn("usage_percent", sys_health["ram"])

        # Root payload check
        self.assertIn("system_health", payload)

    def test_sync_service_build_activity_payload_includes_system_health(self):
        """Verify SyncService._build_activity_payload attaches system_health."""
        sync_svc = SyncService(api_url="https://test.api")
        now = datetime.now(timezone.utc)

        mock_session = MagicMock(spec=ActivitySession)
        mock_session.id = 202
        mock_session.application_name = "chrome.exe"
        mock_session.process_id = 7890
        mock_session.started_at = now - timedelta(minutes=3)
        mock_session.ended_at = now
        mock_session.duration_seconds = 180

        with patch("services.sync_service.get_session") as mock_get_session:
            mock_repo = MagicMock()
            mock_repo.get_sessions_between.return_value = [mock_session]
            mock_repo.get_application_usage.return_value = [{"application_name": "chrome.exe", "total_duration_seconds": 180}]
            
            with patch("services.sync_service.ActivityRepository", return_value=mock_repo):
                payload = sync_svc._build_activity_payload(
                    sync_from=now - timedelta(minutes=5),
                    sync_to=now,
                )

                self.assertIn("system_health", payload)
                self.assertIn("activities", payload)
                self.assertEqual(len(payload["activities"]), 1)
                self.assertIn("system_health", payload["activities"][0])

    def test_sync_activity_now_sends_health_in_request_payload(self):
        """Verify sync_activity_now includes top-level and session-level health metrics."""
        sync_svc = SyncService(api_url="https://test.api")
        now = datetime.now(timezone.utc)

        mock_session = MagicMock(spec=ActivitySession)
        mock_session.id = 303
        mock_session.application_name = "slack.exe"
        mock_session.process_id = 3333
        mock_session.window_title = "General - Slack"
        mock_session.started_at = now - timedelta(minutes=4)
        mock_session.ended_at = now
        mock_session.duration_seconds = 240
        mock_session.idle_seconds = 0
        mock_session.employee_id = "EMP001"

        with patch.object(sync_svc, "_require_device_token", return_value="test_token_123"), \
             patch.object(sync_svc, "fetch_settings", return_value={}), \
             patch("services.sync_service.get_session") as mock_get_session, \
             patch("requests.post") as mock_post:

            mock_db = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_unsynced_closed_sessions.return_value = [mock_session]
            mock_repo.get_sessions_with_unuploaded_screenshots.return_value = []
            
            mock_get_session.return_value = mock_db
            with patch("services.sync_service.ActivityRepository", return_value=mock_repo):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.text = '{"response": "Success", "data": [{"client_session_ref": 303, "activity_session_id": "srv_303"}]}'
                mock_resp.json.return_value = {
                    "response": "Success",
                    "data": [{"client_session_ref": 303, "activity_session_id": "srv_303"}],
                }
                mock_post.return_value = mock_resp

                success = sync_svc.sync_activity_now(timeout=5.0)
                self.assertTrue(success)

                # Verify requests.post was called with health fields
                mock_post.assert_called()
                call_args, call_kwargs = mock_post.call_args
                sent_data = call_kwargs["data"]

                self.assertEqual(sent_data["device_token"], "test_token_123")
                self.assertIn("sessions", sent_data)
                self.assertIn("system_health", sent_data)
                self.assertIn("cpu_usage_percent", sent_data)
                self.assertIn("ram_usage_percent", sent_data)
                self.assertIn("disk_usage_percent", sent_data)
                self.assertIn("network_status", sent_data)


if __name__ == "__main__":
    unittest.main()

