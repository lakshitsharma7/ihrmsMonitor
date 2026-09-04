"""Unit tests for API-driven sync_interval_seconds and idle_threshold_seconds configuration."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from database.database import get_session, init_database
from database.repository import SettingsRepository
from services.sync_service import SyncService
from tracker.activity_tracker import ActivityTracker


class FakeProvider:
    def __init__(self):
        from platform_support.base import ActiveApplication
        self.active_application = ActiveApplication("Code.exe", 100, "main.py")
        self.idle_seconds = 0.0

    def get_active_application(self):
        return self.active_application

    def get_idle_seconds(self):
        return self.idle_seconds


class FakeClock:
    def __init__(self, start_dt):
        self.dt = start_dt

    def __call__(self):
        return self.dt

    def advance(self, seconds):
        self.dt += timedelta(seconds=seconds)


class TestSyncAndIdleConfiguration(unittest.TestCase):
    """Test suite verifying API-driven sync interval and idle threshold behavior."""

    def setUp(self):
        init_database()
        self.sync_service = SyncService(api_url="https://test.api")
        # Ensure fresh state
        self.sync_service.current_sync_interval_seconds = 300
        self.sync_service.current_idle_threshold_seconds = 300

    def test_fetch_settings_applies_exact_api_values(self):
        """Verify fetch_settings applies the exact sync_interval_seconds and idle_threshold_seconds."""
        test_cases = [
            {"sync_interval_seconds": 60, "idle_threshold_seconds": 60},
            {"sync_interval_seconds": 300, "idle_threshold_seconds": 120},
            {"sync_interval_seconds": 600, "idle_threshold_seconds": 300},
        ]

        for case in test_cases:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "response": "Success",
                "data": {
                    "sync_interval_seconds": case["sync_interval_seconds"],
                    "idle_threshold_seconds": case["idle_threshold_seconds"],
                },
            }

            with patch("requests.post", return_value=mock_resp), \
                 patch.object(self.sync_service, "_require_device_token", return_value="TOKEN_123"):
                
                settings = self.sync_service.fetch_settings()
                self.assertEqual(self.sync_service.current_sync_interval_seconds, case["sync_interval_seconds"])
                self.assertEqual(self.sync_service.current_idle_threshold_seconds, case["idle_threshold_seconds"])

                # Verify database settings repository updated
                db = get_session()
                try:
                    db_settings = SettingsRepository(db).get_or_create()
                    self.assertEqual(db_settings.idle_threshold, case["idle_threshold_seconds"])
                finally:
                    db.close()

    def test_dynamic_server_change_without_restart(self):
        """
        Verify that when the server changes:
        sync_interval_seconds = 600
        idle_threshold_seconds = 120
        the active tracker dynamically adopts 600s sync and 120s idle threshold immediately.
        """
        provider = FakeProvider()
        clock = FakeClock(datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc))

        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=300,
            track_window_titles=True,
            clock=clock,
            sync_service=self.sync_service,
        )
        tracker.start()

        # Initial check
        self.assertEqual(tracker._get_sync_interval_seconds(), 300)
        self.assertEqual(tracker._idle_threshold_seconds, 300)

        # Server changes settings to 600s sync, 120s idle
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "sync_interval_seconds": 600,
                "idle_threshold_seconds": 120,
            },
        }

        with patch("requests.post", return_value=mock_resp), \
             patch.object(self.sync_service, "_require_device_token", return_value="TOKEN_123"):
            self.sync_service.fetch_settings()

        # Tracker poll immediately adopts the new idle threshold
        tracker.poll()
        self.assertEqual(tracker._idle_threshold_seconds, 120)
        self.assertEqual(tracker._get_sync_interval_seconds(), 600)

        # Verify idle detection follows 120 seconds exactly
        provider.idle_seconds = 119.0
        state = tracker.poll()
        self.assertFalse(state.is_idle, "User should still be active at 119 seconds")

        provider.idle_seconds = 120.0
        state = tracker.poll()
        self.assertTrue(state.is_idle, "User must become idle at 120 seconds")

    def test_dynamic_sync_interval_transition_300_to_60_sends_logs_every_minute(self):
        """
        Verify that changing sync_interval_seconds from 300 to 60 automatically
        starts sending activity logs every 1 minute without rebuilding or restart.
        """
        provider = FakeProvider()
        clock = FakeClock(datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc))

        self.sync_service.current_sync_interval_seconds = 300
        self.sync_service.current_idle_threshold_seconds = 180

        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=180,
            track_window_titles=True,
            clock=clock,
            sync_service=self.sync_service,
        )

        with patch.object(tracker, "_sync_activity") as mock_sync, \
             patch.object(self.sync_service, "_require_device_token", return_value="TOKEN_123"):

            tracker.start()
            # Initial sync triggered on start
            self.assertEqual(mock_sync.call_count, 1)

            # Server now updates sync_interval_seconds = 60
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "response": "Success",
                "data": {
                    "sync_interval_seconds": 60,
                    "idle_threshold_seconds": 180,
                },
            }

            with patch("requests.post", return_value=mock_resp):
                # Advance by 30 seconds - within interval, no sync yet
                clock.advance(30)
                tracker.poll()
                self.assertEqual(mock_sync.call_count, 1)

                # Advance another 30 seconds (total 60 seconds = 1 minute)
                clock.advance(30)
                tracker.poll()
                # Periodic fetch picked up 60s, and sync fired!
                self.assertEqual(mock_sync.call_count, 2)
                self.assertEqual(tracker._get_sync_interval_seconds(), 60)

                # Advance another 60 seconds (total 120 seconds = 2 minutes)
                clock.advance(60)
                tracker.poll()
                self.assertEqual(mock_sync.call_count, 3)

                # Advance another 60 seconds (total 180 seconds = 3 minutes)
                clock.advance(60)
                tracker.poll()
                self.assertEqual(mock_sync.call_count, 4)

                # Verify idle threshold stayed completely separate at 180 seconds
                self.assertEqual(tracker._idle_threshold_seconds, 180)
                provider.idle_seconds = 179.0
                self.assertFalse(tracker.poll().is_idle)
                provider.idle_seconds = 180.0
                self.assertTrue(tracker.poll().is_idle)

    def test_api_failure_preserves_last_received_settings(self):
        """Verify that when API temporarily fails, last received settings are preserved."""
        self.sync_service.current_sync_interval_seconds = 600
        self.sync_service.current_idle_threshold_seconds = 120

        # Simulate API network timeout or error 500
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = Exception("500 Internal Server Error")

        with patch("requests.post", return_value=mock_resp), \
             patch.object(self.sync_service, "_require_device_token", return_value="TOKEN_123"):
            result = self.sync_service.fetch_settings()
            self.assertEqual(result, {})

        # Settings must remain preserved
        self.assertEqual(self.sync_service.current_sync_interval_seconds, 600)
        self.assertEqual(self.sync_service.current_idle_threshold_seconds, 120)

    def test_sync_cycle_logging_and_schedule(self):
        """Verify sync_activity_now logs current intervals, next sync time, and records sending."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "sync_interval_seconds": 300,
                "idle_threshold_seconds": 120,
            },
        }

        with patch("requests.post", return_value=mock_resp), \
             patch.object(self.sync_service, "_require_device_token", return_value="TOKEN_123"), \
             patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", return_value=[]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]), \
             self.assertLogs("activity_tracker.services.sync_service", level="INFO") as cm:

            success = self.sync_service.sync_activity_now()
            self.assertTrue(success)

            # Check required logging content
            log_text = "\n".join(cm.output)
            self.assertIn("sync_interval_seconds=300", log_text)
            self.assertIn("idle_threshold_seconds=120", log_text)
            self.assertIn("next_sync_time=", log_text)
            self.assertIn("records_currently_sending=0", log_text)
            self.assertIn("Sync SUCCESS", log_text)


    def test_idle_activity_payload_includes_app_status_and_timestamps(self):
        """Verify activity records sent to API when idle include application name, Status: Idle, idle start/end, and duration."""
        from database.models import ActivitySession

        db = get_session()
        try:
            start_dt = datetime(2026, 9, 4, 10, 0, 0, tzinfo=timezone.utc)
            end_dt = datetime(2026, 9, 4, 10, 20, 0, tzinfo=timezone.utc)
            # 5 minutes 32 seconds idle = 332 seconds
            sess = ActivitySession(
                application_name="Google Chrome",
                window_title="HRMS Portal - Google Chrome",
                process_id=5432,
                started_at=start_dt,
                ended_at=end_dt,
                duration_seconds=1200,
                idle_seconds=332,
                employee_id="EMP_IDLE_TEST",
            )
            db.add(sess)
            db.commit()
            db.refresh(sess)

            # Build payload
            payload = self.sync_service._build_page_payload([sess], start_dt, end_dt, page=1, page_size=25)
            self.assertEqual(len(payload["activities"]), 1)
            act = payload["activities"][0]

            self.assertEqual(act["application_name"], "Google Chrome")
            self.assertEqual(act["status"], "Idle")
            self.assertEqual(act["idle_status"], "Idle")
            self.assertTrue(act["is_idle"])
            self.assertEqual(act["idle_time"], 332)
            self.assertEqual(act["idle_duration_seconds"], 332)
            self.assertIn("idle_start_time", act)
            self.assertIn("idle_end_time", act)
            self.assertTrue(len(act["idle_start_time"]) > 0)
            self.assertTrue(len(act["idle_end_time"]) > 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
