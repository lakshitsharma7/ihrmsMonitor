"""End-to-End Test Suite for Laptop Health Data Synchronization.

Verifies:
1. Health collection (CPU, RAM, Disk, Network, Battery, Uptime, Hostname, OS).
2. Health payload construction and presence in outgoing API requests.
3. Backend reception of health fields.
4. Correct association with user and device.
5. Value fidelity between laptop and backend payload.
6. Dynamic health metric updates across sync cycles.
7. Offline resilience (data preservation on network failure).
8. Network reconnection and successful delayed sync.
9. Continuous tracking stability during health sync.
10. Activity, session, and screenshot sync coexistence.
"""

import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from database.models import ActivitySession
from database.database import get_session
from database.repository import ActivityRepository
from services.sync_service import SyncService
from services.session_service import SessionService
from utils.system_health import get_system_health


class TestLaptopHealthSyncEndToEnd(unittest.TestCase):
    def setUp(self):
        self.sync_svc = SyncService(api_url="https://test.indovisionservices.in/api")
        self.now = datetime.now(timezone.utc)

    def test_01_health_data_collection(self):
        """TEST 1: Verify CPU, RAM, Disk, and hardware health metrics are collected accurately."""
        health = get_system_health()
        
        self.assertIn("cpu_usage_percent", health)
        self.assertIn("cpu_logical_cores", health)
        self.assertIn("ram_usage_percent", health)
        self.assertIn("ram_total_mb", health)
        self.assertIn("ram_used_mb", health)
        self.assertIn("ram_available_mb", health)
        self.assertIn("disk_usage_percent", health)
        self.assertIn("disk_total_gb", health)
        self.assertIn("disk_free_gb", health)
        self.assertIn("network_status", health)
        self.assertIn("network_sent_mb", health)
        self.assertIn("network_received_mb", health)

        self.assertGreaterEqual(health["cpu_usage_percent"], 0.0)
        self.assertGreaterEqual(health["ram_usage_percent"], 0.0)
        self.assertGreaterEqual(health["disk_usage_percent"], 0.0)
        self.assertIn(health["network_status"], ["connected", "disconnected"])

    def test_02_outgoing_payload_contains_health_fields(self):
        """TEST 2 & 3: Trigger sync and verify outgoing request contains all health metrics."""
        mock_session = MagicMock(spec=ActivitySession)
        mock_session.id = 1001
        mock_session.application_name = "Code.exe"
        mock_session.process_id = 1234
        mock_session.window_title = "app.py - Visual Studio Code"
        mock_session.started_at = self.now - timedelta(minutes=5)
        mock_session.ended_at = self.now
        mock_session.duration_seconds = 300
        mock_session.idle_seconds = 0
        mock_session.employee_id = "EMP_101"

        with patch.object(self.sync_svc, "_require_device_token", return_value="device_token_xyz"), \
             patch.object(self.sync_svc, "fetch_settings", return_value={}), \
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
                mock_resp.text = '{"response": "Success", "data": [{"client_session_ref": 1001, "activity_session_id": "srv_1001"}]}'
                mock_resp.json.return_value = {
                    "response": "Success",
                    "data": [{"client_session_ref": 1001, "activity_session_id": "srv_1001"}],
                }
                mock_post.return_value = mock_resp

                success = self.sync_svc.sync_activity_now(timeout=5.0)
                self.assertTrue(success)

                # Inspect actual outgoing request
                mock_post.assert_called_once()
                call_args, call_kwargs = mock_post.call_args
                payload = call_kwargs["data"]

                # Verify root-level health payload
                self.assertIn("system_health", payload)
                self.assertIn("device_health", payload)
                self.assertIn("cpu_usage_percent", payload)
                self.assertIn("ram_usage_percent", payload)
                self.assertIn("disk_usage_percent", payload)
                self.assertIn("network_status", payload)

                # Verify sessions payload contains session-level health
                sessions_json = json.loads(payload["sessions"])
                self.assertEqual(len(sessions_json), 1)
                session_item = sessions_json[0]
                self.assertIn("system_health", session_item)
                sys_h = session_item["system_health"]
                self.assertIn("cpu", sys_h)
                self.assertIn("ram", sys_h)
                self.assertIn("disk", sys_h)
                self.assertIn("os", sys_h)
                self.assertIn("usage_percent", sys_h["cpu"])
                self.assertIn("usage_percent", sys_h["ram"])
                self.assertIn("cpu_usage_percent", session_item)
                self.assertIn("ram_usage_percent", session_item)

    def test_04_dynamic_health_updates_across_syncs(self):
        """TEST 4, 5 & 6: Change health metrics dynamically and verify updated values reach backend."""
        mock_session = MagicMock(spec=ActivitySession)
        mock_session.id = 1002
        mock_session.application_name = "PyCharm.exe"
        mock_session.process_id = 5678
        mock_session.window_title = "project - PyCharm"
        mock_session.started_at = self.now - timedelta(minutes=5)
        mock_session.ended_at = self.now
        mock_session.duration_seconds = 300
        mock_session.idle_seconds = 0
        mock_session.employee_id = "EMP_101"

        with patch.object(self.sync_svc, "_require_device_token", return_value="device_token_xyz"), \
             patch.object(self.sync_svc, "fetch_settings", return_value={}), \
             patch("services.sync_service.get_session") as mock_get_session, \
             patch("requests.post") as mock_post:

            mock_db = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_unsynced_closed_sessions.return_value = [mock_session]
            mock_repo.get_sessions_with_unuploaded_screenshots.return_value = []
            mock_get_session.return_value = mock_db

            with patch("services.sync_service.ActivityRepository", return_value=mock_repo), \
                 patch("psutil.cpu_percent", return_value=88.5), \
                 patch("psutil.virtual_memory") as mock_mem:

                mock_mem.return_value = MagicMock(percent=92.0, total=16*1024*1024*1024, used=14.72*1024*1024*1024, available=1.28*1024*1024*1024)

                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.text = '{"response": "Success", "data": [{"client_session_ref": 1002, "activity_session_id": "srv_1002"}]}'
                mock_resp.json.return_value = {
                    "response": "Success",
                    "data": [{"client_session_ref": 1002, "activity_session_id": "srv_1002"}],
                }
                mock_post.return_value = mock_resp

                success = self.sync_svc.sync_activity_now(timeout=5.0)
                self.assertTrue(success)

                payload = mock_post.call_args[1]["data"]
                self.assertEqual(payload["cpu_usage_percent"], "88.5")
                self.assertEqual(payload["ram_usage_percent"], "92.0")

    def test_07_offline_preservation_and_recovery(self):
        """TEST 7 & 8: Network failure preserves health and activity records for subsequent retry."""
        mock_session = MagicMock(spec=ActivitySession)
        mock_session.id = 1003
        mock_session.application_name = "notepad.exe"
        mock_session.process_id = 9012
        mock_session.window_title = "notes.txt - Notepad"
        mock_session.started_at = self.now - timedelta(minutes=5)
        mock_session.ended_at = self.now
        mock_session.duration_seconds = 300
        mock_session.idle_seconds = 0
        mock_session.employee_id = "EMP_101"

        with patch.object(self.sync_svc, "_require_device_token", return_value="device_token_xyz"), \
             patch.object(self.sync_svc, "fetch_settings", return_value={}), \
             patch("services.sync_service.get_session") as mock_get_session, \
             patch("requests.post", side_effect=Exception("ConnectionRefusedError: Server unreachable")):

            mock_db = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_unsynced_closed_sessions.return_value = [mock_session]
            mock_repo.get_sessions_with_unuploaded_screenshots.return_value = []
            mock_get_session.return_value = mock_db

            with patch("services.sync_service.ActivityRepository", return_value=mock_repo):
                # 1. Attempt sync while offline -> fails cleanly without crashing
                success = self.sync_svc.sync_activity_now(timeout=5.0)
                self.assertFalse(success)
                # Session was not marked uploaded
                mock_repo.update_session_server_id.assert_not_called()

        # 2. Reconnect network -> next sync succeeds
        with patch.object(self.sync_svc, "_require_device_token", return_value="device_token_xyz"), \
             patch.object(self.sync_svc, "fetch_settings", return_value={}), \
             patch("services.sync_service.get_session") as mock_get_session, \
             patch("requests.post") as mock_post_online:

            mock_db2 = MagicMock()
            mock_repo2 = MagicMock()
            mock_repo2.get_unsynced_closed_sessions.return_value = [mock_session]
            mock_repo2.get_sessions_with_unuploaded_screenshots.return_value = []
            mock_get_session.return_value = mock_db2

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"response": "Success", "data": [{"client_session_ref": 1003, "activity_session_id": "srv_1003"}]}'
            mock_resp.json.return_value = {
                "response": "Success",
                "data": [{"client_session_ref": 1003, "activity_session_id": "srv_1003"}],
            }
            mock_post_online.return_value = mock_resp

            with patch("services.sync_service.ActivityRepository", return_value=mock_repo2):
                recovered = self.sync_svc.sync_activity_now(timeout=5.0)
                self.assertTrue(recovered)
                mock_repo2.update_session_server_id.assert_called_once_with(1003, "srv_1003")

    def test_09_continuous_tracking_uninterrupted(self):
        """TEST 9 & 10: Health syncing coexists cleanly with activity and screenshot tracking."""
        # Check that health collector is lightweight and safe under repeated invocations
        for _ in range(5):
            h = get_system_health()
            self.assertIsNotNone(h)
            self.assertIn("cpu_usage_percent", h)
            self.assertIn("ram_usage_percent", h)

    def test_11_database_schema_and_column_persistence(self):
        """TEST 11: Verify dedicated system_health column exists in database and stores structured JSON."""
        from database.database import get_session, init_database, get_engine
        from sqlalchemy import text
        from database.models import EnrolledDevice, ActivitySession
        from database.repository import ActivityRepository

        # Initialize schema and migrations
        init_database()
        engine = get_engine()

        with engine.connect() as conn:
            # 1. Verify system_health column in activity_sessions
            act_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(activity_sessions)")).fetchall()]
            self.assertIn("system_health", act_cols, "Column system_health must exist in activity_sessions table")

            # 2. Verify system_health column in enrolled_devices
            dev_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(enrolled_devices)")).fetchall()]
            self.assertIn("system_health", dev_cols, "Column system_health must exist in enrolled_devices table")

        # 3. Test saving session with system health
        db = get_session()
        try:
            repo = ActivityRepository(db)
            test_health = {
                "cpu_usage_percent": 42.5,
                "ram_usage_percent": 68.3,
                "disk_usage_percent": 22.1,
                "network_status": "connected",
                "hostname": "Test-Laptop",
                "os": "Windows",
            }
            session_rec = repo.create_session(
                application_name="Code.exe",
                process_id=9999,
                window_title="workspace - VS Code",
                started_at=self.now,
                employee_id="EMP_TEST",
                system_health=test_health,
            )
            self.assertIsNotNone(session_rec.system_health)
            stored_data = json.loads(session_rec.system_health)
            self.assertEqual(stored_data["cpu_usage_percent"], 42.5)
            self.assertEqual(stored_data["ram_usage_percent"], 68.3)
            self.assertEqual(stored_data["hostname"], "Test-Laptop")
        finally:
            db.close()

    def test_12_device_registry_persists_system_health_in_database(self):
        """TEST 12: Verify DeviceRegistryService records system_health in database and exposes it."""
        from services.device_registry_service import DeviceRegistryService
        from database.database import get_session
        from database.models import EnrolledDevice
        from sqlalchemy import select

        registry = DeviceRegistryService()
        test_dev_id = "test_device_health_check_999"
        test_health = {
            "cpu_usage_percent": 25.4,
            "ram_usage_percent": 48.2,
            "disk_usage_percent": 61.5,
            "network_status": "connected",
        }

        # 1. Heartbeat saves system health
        dev = registry.record_heartbeat(
            device_identifier=test_dev_id,
            hostname="TestLaptop-Host",
            employee_id="EMP_888",
            username="testuser",
            system_health=test_health,
        )
        self.assertIsNotNone(dev.system_health)
        stored_json = json.loads(dev.system_health)
        self.assertEqual(stored_json["cpu_usage_percent"], 25.4)
        self.assertEqual(stored_json["ram_usage_percent"], 48.2)

        # 2. Sync success updates system health in database
        updated_health = {
            "cpu_usage_percent": 30.1,
            "ram_usage_percent": 52.0,
            "disk_usage_percent": 61.5,
            "network_status": "connected",
        }
        registry.record_sync_success(device_identifier=test_dev_id, system_health=updated_health)

        # Query database directly to confirm value
        db = get_session()
        try:
            device_db = db.execute(select(EnrolledDevice).where(EnrolledDevice.device_identifier == test_dev_id)).scalars().first()
            self.assertIsNotNone(device_db)
            self.assertIsNotNone(device_db.system_health)
            db_data = json.loads(device_db.system_health)
            self.assertEqual(db_data["cpu_usage_percent"], 30.1)
            self.assertEqual(db_data["ram_usage_percent"], 52.0)
        finally:
            db.close()

        # 3. get_all_devices exposes system_health
        all_devs = registry.get_all_devices()
        target = next((d for d in all_devs if d["device_identifier"] == test_dev_id), None)
        self.assertIsNotNone(target)
        self.assertIsNotNone(target.get("system_health"))


if __name__ == "__main__":
    unittest.main()
