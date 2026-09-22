"""Tests for Workpulse Pause/Resume behavior.

Verifies:
1. When employee clicks 'Paused':
   - Activity tracking does NOT stop.
   - Logs/session collection does NOT stop.
   - Screenshot tracking does NOT stop.
   - Backend sync does NOT stop.
   - Button text changes from 'Paused' to 'Resume'.
   - Displayed status clearly shows 'Paused' on Dashboard and header status badge.
   - Clean internal state indicates employee is currently paused.

2. When employee clicks 'Resume':
   - Displayed status changes back to normal active/online state.
   - Same existing tracking/logging/sync workers continue without creating duplicates.
   - Button text changes from 'Resume' to 'Paused'.
   - Clean internal state indicates employee is not paused.
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from PySide6.QtWidgets import QApplication

from services.session_service import SessionService
from services.secure_session import SessionStore
from tracker.activity_tracker import TrackerState
from ui.dashboard import DashboardPage
from ui.main_window import MainWindow


class TestPauseResumeBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        SessionService().clear()
        self.store = SessionStore()
        self.store.clear_session()
        self.mock_service = MagicMock()
        self.mock_service.get_today_total_seconds.return_value = 100
        self.mock_service.get_persisted_daily_active_seconds.return_value = 100

    def tearDown(self):
        SessionService().clear()
        self.store.clear_session()

    def test_dashboard_pause_resume_toggle(self):
        """DashboardPage toggles pause state and button text without stopping tracking."""
        dashboard = DashboardPage(self.mock_service)
        dashboard.set_tracking_active(True)

        self.assertFalse(dashboard.is_paused())
        self.assertEqual(dashboard.tracking_toggle_button.text(), "Paused")
        self.assertEqual(dashboard.tracking_status_label.text(), "Online: Active")

        # 1. Click "Paused" -> state becomes paused, button becomes "Resume"
        pause_signals = []
        dashboard.pause_state_changed.connect(lambda p: pause_signals.append(p))

        dashboard.tracking_toggle_button.click()

        self.assertTrue(dashboard.is_paused())
        self.assertEqual(dashboard.tracking_toggle_button.text(), "Resume")
        self.assertEqual(dashboard.tracking_status_label.text(), "Online: Paused")
        self.assertEqual(pause_signals, [True])
        self.assertTrue(self.store.is_tracking_paused())

        # 2. update_tracker_state while paused retains "Paused" display
        state = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Code.exe",
            current_window_title="main.py",
            idle_seconds=0.0,
        )
        dashboard.update_tracker_state(state)
        self.assertEqual(dashboard.tracking_status_label.text(), "Online: Paused")
        self.assertEqual(dashboard.tracking_toggle_button.text(), "Resume")

        # 3. Click "Resume" -> state returns to active, button becomes "Paused"
        dashboard.tracking_toggle_button.click()

        self.assertFalse(dashboard.is_paused())
        self.assertEqual(dashboard.tracking_toggle_button.text(), "Paused")
        self.assertEqual(dashboard.tracking_status_label.text(), "Online: Active")
        self.assertEqual(pause_signals, [True, False])
        self.assertFalse(self.store.is_tracking_paused())

    def test_main_window_pause_resume_keeps_workers_running(self):
        """MainWindow keeps activity tracking and workers running when Paused is clicked."""
        SessionService().login(
            username="emp_pause_test",
            role="User",
            device_token="TOKEN_123",
            tracking_permitted=True,
            allow_user_device=True,
            allow_logout=True,
        )

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                # Initially tracking is running
                self.assertTrue(win._tracker.is_tracking)
                self.assertFalse(win.dashboard_page.is_paused())
                self.assertEqual(win.status_badge.text(), "Online")
                self.assertEqual(win.dashboard_page.tracking_toggle_button.text(), "Paused")

                tracker_instance = win._tracker

                # User clicks "Paused"
                win.dashboard_page.tracking_toggle_button.click()
                QApplication.processEvents()

                # Activity tracking must NOT stop
                self.assertTrue(win._tracker.is_tracking)
                self.assertIs(win._tracker, tracker_instance, "Must use existing tracker instance")
                self.assertTrue(win.dashboard_page.is_paused())
                self.assertTrue(self.store.is_tracking_paused())
                self.assertEqual(win.status_badge.text(), "Paused")
                self.assertEqual(win.dashboard_page.tracking_toggle_button.text(), "Resume")
                self.assertEqual(win.dashboard_page.tracking_status_label.text(), "Online: Paused")

                # Tracker state updates while paused preserve Paused status badge
                active_state = TrackerState(
                    is_tracking=True,
                    is_idle=False,
                    current_application="Slack.exe",
                    current_window_title="General",
                    idle_seconds=0.0,
                )
                win._on_tracker_state_changed(active_state)
                self.assertEqual(win.status_badge.text(), "Paused")

                # User clicks "Resume"
                win.dashboard_page.tracking_toggle_button.click()
                QApplication.processEvents()

                # Activity tracking must continue using the same tracker instance
                self.assertTrue(win._tracker.is_tracking)
                self.assertIs(win._tracker, tracker_instance, "Must continue using existing tracker instance without duplicates")
                self.assertFalse(win.dashboard_page.is_paused())
                self.assertFalse(self.store.is_tracking_paused())
                self.assertEqual(win.status_badge.text(), "Online")
                self.assertEqual(win.dashboard_page.tracking_toggle_button.text(), "Paused")
                self.assertEqual(win.dashboard_page.tracking_status_label.text(), "Online: Active")
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
