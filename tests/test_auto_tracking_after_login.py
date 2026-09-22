"""Unit and integration tests for automatic activity tracking startup after login.

Verifies:
1. Backend settings with allow_start_stop_activity_tracking: False and tracking_enabled: True
   do NOT suppress tracking_permitted.
2. TrackerWorker starts tracking and immediately emits state_changed with is_tracking=True.
3. TrackerWorker handles timer creation safely even if start_tracking is invoked before setup.
4. MainWindow auto-starts tracking and immediately reflects Active status on Dashboard.
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject

from services.session_service import SessionService
from services.sync_service import SyncService
from tracker.activity_tracker import ActivityTracker, TrackerState
from tracker.tracker_worker import TrackerWorker, build_tracker_thread


class TestAutoTrackingAfterLogin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        SessionService().clear()

    @patch("services.sync_service.requests.post")
    def test_fetch_settings_does_not_suppress_tracking_when_manual_start_stop_disabled(self, mock_post):
        """When backend returns allow_start_stop_activity_tracking=False and tracking_enabled=True,
        tracking_permitted MUST remain True so automatic tracking continues to run."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Success",
            "data": {
                "tracking_enabled": True,
                "allow_start_stop_activity_tracking": False,
                "sync_interval_seconds": 300,
                "idle_threshold_seconds": 300,
                "allow_logout": False,
                "allow_user_device": True,
            }
        }
        mock_post.return_value = mock_response

        SessionService().login(
            username="test_emp",
            role="User",
            device_token="TOKEN_ABC",
            tracking_permitted=True,
        )

        svc = SyncService(api_url="https://mock.api")
        settings = svc.fetch_settings()

        curr = SessionService().current_user
        self.assertIsNotNone(curr)
        self.assertTrue(curr.tracking_permitted, "tracking_permitted must remain True despite allow_start_stop_activity_tracking=False")
        self.assertFalse(curr.allow_logout)
        self.assertTrue(curr.allow_user_device)

    def test_tracker_worker_start_tracking_resilient_to_setup_order(self):
        """TrackerWorker creates timer if setup hasn't run yet, starts timer, and immediately emits state_changed."""
        mock_tracker = MagicMock(spec=ActivityTracker)
        mock_tracker.is_tracking = True
        mock_state = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Code.exe",
            current_window_title="test_file.py",
            idle_seconds=0.0,
        )
        stopped_state = TrackerState(
            is_tracking=False,
            is_idle=False,
            current_application=None,
            current_window_title=None,
            idle_seconds=0.0,
        )
        mock_tracker.poll.side_effect = [mock_state, stopped_state]

        worker = TrackerWorker(mock_tracker, poll_interval_seconds=1.0)
        self.assertIsNone(worker._timer)

        received_states = []
        worker.state_changed.connect(lambda state: received_states.append(state))

        # Invoke start_tracking without prior setup()
        worker.start_tracking()

        self.assertIsNotNone(worker._timer)
        self.assertTrue(worker._timer.isActive())
        mock_tracker.start.assert_called_once()
        self.assertEqual(len(received_states), 1)
        self.assertTrue(received_states[0].is_tracking)
        self.assertEqual(received_states[0].current_application, "Code.exe")

        worker.stop_tracking()
        self.assertFalse(worker._timer.isActive())
        self.assertEqual(len(received_states), 2)
        self.assertFalse(received_states[1].is_tracking)

    def test_main_window_auto_starts_tracking_and_updates_dashboard(self):
        """MainWindow.__init__ automatically starts tracking and updates dashboard labels."""
        from ui.main_window import MainWindow

        SessionService().login(
            username="emp_auto_track",
            role="User",
            device_token="TOKEN_XYZ",
            tracking_permitted=True,
            allow_user_device=True,
            allow_logout=True,
        )

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            try:
                # Dashboard labels should be Active, button Paused, and network Online
                self.assertEqual(win.status_badge.text(), "Online")
                self.assertIn("Active", win.dashboard_page.tracking_status_label.text())
                self.assertEqual(win.dashboard_page.tracking_toggle_button.text(), "Paused")
                self.assertEqual(win.dashboard_page.network_status_label.text(), "● Online")
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
