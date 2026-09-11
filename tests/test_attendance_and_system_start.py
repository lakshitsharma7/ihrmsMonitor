"""Unit tests for daily system start tracking and dynamic punch integration."""

import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from database.models import ActivitySession
from services.attendance_service import AttendanceService
from services.sync_service import SyncService
from config.api_config import ApiConfig


class TestAttendanceAndSystemStart(unittest.TestCase):
    def setUp(self):
        self.service = AttendanceService()
        self.service.clear_state()
        self.today_str = datetime.now().astimezone().strftime("%Y-%m-%d")

    def tearDown(self):
        self.service.clear_state()

    def test_01_system_and_tracking_start_captured_automatically(self):
        """Verify system_started_at and tracking_started_at are recorded for today."""
        res = self.service.record_tracking_start()
        self.assertEqual(res["date"], self.today_str)
        self.assertIsNotNone(res["system_started_at"])
        self.assertIsNotNone(res["tracking_started_at"])
        self.assertIsNone(res["punch_in"])
        self.assertIsNone(res["punch_out"])

    def test_02_multiple_restarts_preserve_initial_tracking_start_time(self):
        """Verify subsequent calls on the same day do not overwrite initial tracking_started_at."""
        first_time = datetime(2026, 9, 11, 8, 47, 15)
        self.service.record_tracking_start(timestamp=first_time)
        first_res = self.service.get_daily_attendance(date_str="2026-09-11")
        self.assertEqual(first_res["tracking_started_at"], "2026-09-11 08:47:15")

        # Simulate app restart 2 hours later
        second_time = datetime(2026, 9, 11, 10, 47, 15)
        self.service.record_tracking_start(timestamp=second_time)
        second_res = self.service.get_daily_attendance(date_str="2026-09-11")
        self.assertEqual(second_res["tracking_started_at"], "2026-09-11 08:47:15")

    def test_03_punch_in_and_out_recording(self):
        """Verify Punch-In and Punch-Out timestamps can be recorded and retrieved."""
        self.service.record_punch_in("2026-09-11 09:03:11", date_str="2026-09-11")
        att = self.service.get_daily_attendance(date_str="2026-09-11")
        self.assertEqual(att["punch_in"], "2026-09-11 09:03:11")
        self.assertIsNone(att["punch_out"])

        self.service.record_punch_out("2026-09-11 18:12:40", date_str="2026-09-11")
        att2 = self.service.get_daily_attendance(date_str="2026-09-11")
        self.assertEqual(att2["punch_in"], "2026-09-11 09:03:11")
        self.assertEqual(att2["punch_out"], "2026-09-11 18:12:40")

    def test_04_sync_service_payload_includes_system_start_and_punch(self):
        """Verify SyncService page and activity payloads contain system start and punch fields."""
        sync_svc = SyncService(api_url="https://test.api")
        now = datetime.now(timezone.utc)

        mock_session = MagicMock(spec=ActivitySession)
        mock_session.id = 501
        mock_session.application_name = "explorer.exe"
        mock_session.process_id = 1234
        mock_session.window_title = "My Documents"
        mock_session.started_at = now - timedelta(minutes=2)
        mock_session.ended_at = now
        mock_session.duration_seconds = 120
        mock_session.idle_seconds = 0

        payload = sync_svc._build_page_payload(
            sessions=[mock_session],
            sync_from=now - timedelta(minutes=2),
            sync_to=now,
            page=1,
            page_size=25,
        )

        # Root payload check
        self.assertIn("system_started_at", payload)
        self.assertIn("tracking_started_at", payload)
        self.assertIn("punch_in", payload)
        self.assertIn("punch_out", payload)

        # Activity record check
        self.assertIn("activities", payload)
        self.assertEqual(len(payload["activities"]), 1)
        activity = payload["activities"][0]
        self.assertIn("system_started_at", activity)
        self.assertIn("tracking_started_at", activity)
        self.assertIn("punch_in", activity)
        self.assertIn("punch_out", activity)
        self.assertIn("system_health", activity)

    def test_05_dynamic_punch_url_resolution(self):
        """Verify ApiConfig resolves punch_url dynamically."""
        cfg = ApiConfig()
        cfg._details = {
            "base_url": "https://company.api/v1/",
            "punch_url": "https://company.api/v1/Punch/get_punch_time",
        }
        self.assertEqual(cfg.punch_url, "https://company.api/v1/Punch/get_punch_time")

        # Test environment override
        with patch.dict(os.environ, {"IHRMS_PUNCH_API_URL": "https://env.api/Punch/get_punch_time"}):
            self.assertEqual(cfg.punch_url, "https://env.api/Punch/get_punch_time")

    def test_06_fetch_punch_time_contract_success(self):
        """Verify fetch_punch_time sends indo_code, key, punch_date and parses exact Postman response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": 200,
            "status": 1,
            "message": "Data found",
            "punch_date": "22-05-2025",
            "punch_in_time": "10:36:42",
            "punch_out_time": "14:39:41",
        }

        with patch("requests.post", return_value=mock_response) as mock_post, \
             patch.dict(os.environ, {"IHRMS_PUNCH_API_URL": "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/punch/get_punch_time"}):
            
            res = self.service.fetch_punch_time(
                punch_date="22-05-2025",
                indo_code="EC-098",
                key="testapikey111",
                force=True,
            )

            # Check post call arguments
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(args[0], "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/punch/get_punch_time")
            self.assertEqual(kwargs["data"], {
                "indo_code": "EC-098",
                "key": "testapikey111",
                "punch_date": "22-05-2025",
            })

            # Check parsed attendance
            self.assertIsNotNone(res)
            self.assertEqual(res["punch_in"], "2025-05-22 10:36:42")
            self.assertEqual(res["punch_out"], "2025-05-22 14:39:41")

    def test_07_fetch_punch_time_graceful_failure(self):
        """Verify fetch_punch_time fails gracefully when server is offline."""
        with patch("requests.post", side_effect=Exception("Connection refused")), \
             patch.dict(os.environ, {"IHRMS_PUNCH_API_URL": "https://company.api/Punch/get_punch_time"}):
            
            res = self.service.fetch_punch_time(
                punch_date="2026-09-11",
                indo_code="EC-098",
                key="testapikey111",
                force=True,
            )
            self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
