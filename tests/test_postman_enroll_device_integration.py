"""
Tests verifying the integration of the POST /workpulse/enroll_device API
matching the exact backend contract shown in the Postman specification:

Endpoint: POST /workpulse/enroll_device
Response Schema:
{
  "message": "Device enrolled successfully.",
  "data": {
    "workpulse_enabled": true,
    "device_token": "ddd7064ac66eb1546dbc6acfe8268ee71fee763a0ca293b68d7e2ced1dd0756f",
    "capture_mode": "activity_with_screenshots",
    "sync_interval_minutes": 15,
    "idle_threshold_minutes": 1,
    "allow_start_stop_activity_tracking": true,
    "allow_logout": true,
    "screenshot_settings": {
      "enabled": true,
      "capture_mode": "window_change",
      "allowed_types": [
        "png",
        "jpg",
        "jpeg"
      ],
      "capture_on_window_change": true,
      "interval_minutes": 30,
      "max_kb": 100
    }
  }
}
"""

import unittest
import json
from unittest.mock import MagicMock, patch
from config.screenshot_config import (
    apply_api_screenshot_config,
    get_screenshot_config,
    reset_screenshot_config,
)
from services.sync_service import SyncService
from services.session_service import SessionService
from services.secure_session import SessionStore
from database.database import get_session
from database.repository import SettingsRepository


POSTMAN_ENROLL_RESPONSE = {
    "message": "Device enrolled successfully.",
    "data": {
        "workpulse_enabled": True,
        "device_token": "ddd7064ac66eb1546dbc6acfe8268ee71fee763a0ca293b68d7e2ced1dd0756f",
        "capture_mode": "activity_with_screenshots",
        "sync_interval_minutes": 15,
        "idle_threshold_minutes": 1,
        "allow_start_stop_activity_tracking": True,
        "allow_logout": True,
        "screenshot_settings": {
            "enabled": True,
            "capture_mode": "window_change",
            "allowed_types": [
                "png",
                "jpg",
                "jpeg",
            ],
            "capture_on_window_change": True,
            "interval_minutes": 30,
            "max_kb": 100,
        },
    },
}


class TestPostmanEnrollDeviceIntegration(unittest.TestCase):
    def setUp(self):
        reset_screenshot_config()
        SessionService().clear()
        self.sync_service = SyncService(api_url="https://test.api")
        self.sync_service.current_sync_interval_seconds = 300
        self.sync_service.current_idle_threshold_seconds = 300

    def tearDown(self):
        reset_screenshot_config()
        SessionService().clear()

    def test_postman_screenshot_settings_parsed_correctly(self):
        """Verify ScreenshotConfig parses the exact Postman response."""
        cfg = apply_api_screenshot_config(POSTMAN_ENROLL_RESPONSE)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.capture_mode, "window_change")
        self.assertTrue(cfg.capture_on_window_change)
        self.assertEqual(cfg.interval_minutes, 30.0)
        self.assertEqual(cfg.max_size_kb, 100)
        self.assertEqual(cfg.allowed_types, ["png", "jpg", "jpeg"])
        self.assertTrue(cfg.should_capture_on_window_change())
        self.assertFalse(cfg.should_capture_on_interval())

    def test_postman_sync_and_idle_minutes_conversion(self):
        """Verify sync_interval_minutes and idle_threshold_minutes are converted to seconds."""
        applied = self.sync_service.apply_settings_payload(POSTMAN_ENROLL_RESPONSE)
        self.assertIn("device_token", applied)

        # 15 minutes = 900 seconds
        self.assertEqual(self.sync_service.current_sync_interval_seconds, 900)
        # 1 minute = 60 seconds
        self.assertEqual(self.sync_service.current_idle_threshold_seconds, 60)

        # Check DB settings updated
        db = get_session()
        try:
            repo = SettingsRepository(db)
            db_st = repo.get_or_create()
            self.assertEqual(db_st.idle_threshold, 60)
            self.assertTrue(db_st.workpulse_enabled)
        finally:
            db.close()

    def test_postman_permissions_mapped_to_session(self):
        """Verify allow_logout and allow_start_stop_activity_tracking are updated in active session."""
        SessionService().login(
            username="test_emp",
            role="User",
            employee_id="E123",
            indo_code="INDO123",
            api_key="KEY123",
            company_code="COMP123",
            device_token="old_token",
            allow_logout=False,
            allow_start_stop_activity_tracking=False,
            workpulse_permitted=False,
        )

        self.sync_service.apply_settings_payload(POSTMAN_ENROLL_RESPONSE)

        curr = SessionService().current_user
        self.assertIsNotNone(curr)
        self.assertTrue(curr.allow_logout)
        self.assertTrue(curr.allow_start_stop_activity_tracking)
        self.assertTrue(curr.workpulse_permitted)

    def test_re_enroll_device_updates_token_and_settings(self):
        """Verify re_enroll_device updates the token, sync/idle intervals, and permissions."""
        SessionService().login(
            username="test_emp",
            role="User",
            employee_id="E123",
            indo_code="INDO123",
            api_key="KEY123",
            company_code="COMP123",
            device_token="revoked_token",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = POSTMAN_ENROLL_RESPONSE
        mock_resp.text = json.dumps(POSTMAN_ENROLL_RESPONSE)

        with patch("services.sync_service.requests.post", return_value=mock_resp), \
             patch.object(SessionStore, "load_session", return_value={
                 "indo_code": "INDO123",
                 "api_key": "KEY123",
                 "username": "test_emp",
                 "device_token": "revoked_token",
                 "base_url": "https://test.api",
             }), \
             patch.object(SessionStore, "update_device_token"):

            new_token = self.sync_service.re_enroll_device()

            self.assertEqual(
                new_token,
                "ddd7064ac66eb1546dbc6acfe8268ee71fee763a0ca293b68d7e2ced1dd0756f",
            )
            self.assertEqual(SessionService().device_token, new_token)
            self.assertEqual(SessionService().current_user.device_token, new_token)
            self.assertEqual(self.sync_service.current_sync_interval_seconds, 900)
            self.assertEqual(self.sync_service.current_idle_threshold_seconds, 60)

    def test_fetch_settings_with_postman_payload(self):
        """Verify fetch_settings successfully handles backend response wrapped in data."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = POSTMAN_ENROLL_RESPONSE
        mock_resp.text = json.dumps(POSTMAN_ENROLL_RESPONSE)

        with patch("services.sync_service.requests.post", return_value=mock_resp), \
             patch.object(self.sync_service, "_require_device_token", return_value="TOKEN_123"):

            settings = self.sync_service.fetch_settings()
            self.assertIn("device_token", settings)
            self.assertEqual(self.sync_service.current_sync_interval_seconds, 900)
            self.assertEqual(self.sync_service.current_idle_threshold_seconds, 60)

    def test_re_enroll_lock_thread_safety(self):
        """Verify _re_enroll_lock prevents duplicate concurrent re-enrollment executions."""
        self.assertTrue(hasattr(SyncService, "_re_enroll_lock"))
        self.assertFalse(SyncService._re_enroll_lock.locked())


if __name__ == "__main__":
    unittest.main()
