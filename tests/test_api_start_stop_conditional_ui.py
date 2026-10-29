"""Tests for API Start/Stop response parsing and conditional UI rendering.

Verifies:
1. When both start and stop values returned by API are False (e.g. {"start": False, "stop": False}):
   - Neither the Pause button nor the related Last Update section is displayed.
   - Completely hidden without disabled button placeholder or unnecessary spacing.
2. When start/stop API values are True (e.g. {"start": True, "stop": True}):
   - Both Pause button and Last Update section are displayed.
   - Preserves existing Start/Pause/Stop functionality and display behavior.
3. When API response is missing/null:
   - Does not treat missing/null as False without explicit API contract.
4. Dynamic UI updates:
   - UI updates dynamically whenever permissions change from True to False and back.
"""

import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication

from services.session_service import SessionService
from services.sync_service import SyncService
from ui.dashboard import DashboardPage


class TestApiStartStopConditionalUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        SessionService().clear()
        self.mock_service = MagicMock()
        self.mock_service.get_today_total_seconds.return_value = 150
        self.mock_service.get_persisted_daily_active_seconds.return_value = 150

    def tearDown(self):
        SessionService().clear()

    @patch("services.sync_service.requests.post")
    def test_api_start_false_stop_false_hides_pause_and_last_update(self, mock_post):
        """When API returns start: false, stop: false, both Pause button and Last Update section are hidden."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "start": False,
                "stop": False,
            }
        }
        mock_post.return_value = mock_resp

        SessionService().login(
            username="emp_hide_test",
            role="User",
            device_token="TOKEN_ABC",
            allow_start_stop_activity_tracking=True,
        )

        # 1. Fetch settings from API
        sync = SyncService(api_url="https://mock.api")
        settings = sync.fetch_settings()

        self.assertEqual(settings.get("allow_start_stop_activity_tracking"), False)
        self.assertFalse(SessionService().current_user.allow_start_stop_activity_tracking)

        # 2. Verify Dashboard rendering
        dashboard = DashboardPage(self.mock_service)
        dashboard.show()
        dashboard.set_workpulse_active(True)

        # Completely hidden: no visible button, no visible last update, no container visible
        self.assertFalse(dashboard.start_stop_section.isVisible())
        self.assertFalse(dashboard.workpulse_toggle_button.isVisible())
        self.assertFalse(dashboard.last_update_label.isVisible())

        # Button is also disabled to prevent keyboard/programmatic activation
        self.assertFalse(dashboard.workpulse_toggle_button.isEnabled())

        dashboard._shutdown()

    @patch("services.sync_service.requests.post")
    def test_api_start_true_stop_true_displays_pause_and_last_update(self, mock_post):
        """When API returns start: true, stop: true, both Pause button and Last Update section are visible."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "start": True,
                "stop": True,
            }
        }
        mock_post.return_value = mock_resp

        SessionService().login(
            username="emp_show_test",
            role="User",
            device_token="TOKEN_XYZ",
            allow_start_stop_activity_tracking=False,
        )

        # 1. Fetch settings from API
        sync = SyncService(api_url="https://mock.api")
        settings = sync.fetch_settings()

        self.assertEqual(settings.get("allow_start_stop_activity_tracking"), True)
        self.assertTrue(SessionService().current_user.allow_start_stop_activity_tracking)

        # 2. Verify Dashboard rendering
        dashboard = DashboardPage(self.mock_service)
        dashboard.show()
        dashboard.set_workpulse_active(True)

        self.assertTrue(dashboard.start_stop_section.isVisible())
        self.assertTrue(dashboard.workpulse_toggle_button.isVisible())
        self.assertTrue(dashboard.last_update_label.isVisible())
        self.assertTrue(dashboard.workpulse_toggle_button.isEnabled())
        self.assertEqual(dashboard.workpulse_toggle_button.text(), "Pause")

        dashboard._shutdown()

    @patch("services.sync_service.requests.post")
    def test_api_string_values_and_aliases(self, mock_post):
        """Handles string values ('false', '0') and key aliases for start/stop."""
        sync = SyncService(api_url="https://mock.api")

        SessionService().login(
            username="emp_alias_test",
            role="User",
            device_token="TOKEN_ALIAS",
        )

        # String false/false
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"allow_start": "false", "allow_stop": "0"}
        }
        mock_post.return_value = mock_resp

        sync.fetch_settings()
        self.assertFalse(SessionService().current_user.allow_start_stop_activity_tracking)

        # String true/true
        mock_resp.json.return_value = {
            "data": {"allow_start": "true", "allow_stop": "1"}
        }
        sync.fetch_settings()
        self.assertTrue(SessionService().current_user.allow_start_stop_activity_tracking)

    def test_dynamic_transition_on_api_permission_change(self):
        """Dashboard dynamically hides and restores Pause button and Last Update section."""
        SessionService().login(
            username="emp_dynamic_ui",
            role="User",
            allow_start_stop_activity_tracking=True,
        )

        dashboard = DashboardPage(self.mock_service)
        dashboard.show()
        dashboard.set_workpulse_active(True)

        # Initially visible
        self.assertTrue(dashboard.start_stop_section.isVisible())
        self.assertTrue(dashboard.workpulse_toggle_button.isVisible())
        self.assertTrue(dashboard.last_update_label.isVisible())

        # API changes permission to False (start=false, stop=false)
        SessionService().update_permissions(allow_start_stop_activity_tracking=False)
        QApplication.processEvents()

        # Dynamically hidden
        self.assertFalse(dashboard.start_stop_section.isVisible())
        self.assertFalse(dashboard.workpulse_toggle_button.isVisible())
        self.assertFalse(dashboard.last_update_label.isVisible())

        # API changes permission back to True
        SessionService().update_permissions(allow_start_stop_activity_tracking=True)
        QApplication.processEvents()

        # Dynamically restored
        self.assertTrue(dashboard.start_stop_section.isVisible())
        self.assertTrue(dashboard.workpulse_toggle_button.isVisible())
        self.assertTrue(dashboard.last_update_label.isVisible())
        self.assertTrue(dashboard.workpulse_toggle_button.isEnabled())

        dashboard._shutdown()

    @patch("services.sync_service.requests.post")
    def test_missing_or_failed_api_preserves_existing_state(self, mock_post):
        """Missing or failed API response does not treat values as False."""
        SessionService().login(
            username="emp_missing_test",
            role="User",
            device_token="TOKEN_MISS",
            allow_start_stop_activity_tracking=True,
        )

        # Response without start/stop keys
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "sync_interval_seconds": 300,
            }
        }
        mock_post.return_value = mock_resp

        sync = SyncService(api_url="https://mock.api")
        sync.fetch_settings()

        # Must preserve True
        self.assertTrue(SessionService().current_user.allow_start_stop_activity_tracking)


if __name__ == "__main__":
    unittest.main()

