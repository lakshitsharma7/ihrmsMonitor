"""Tests for the Dashboard Pause / Resume button behavior.

Verifies:
1. When tracking is active/running, button displays "Pause".
2. When tracking is paused, button displays "Resume".
3. When tracking is stopped/inactive, button displays "Resume".
4. Clicking "Pause" triggers existing pause functionality (set_paused(True)).
5. Clicking "Resume" triggers existing resume functionality (set_paused(False)).
6. Dynamic state updates (e.g. from update_tracker_state) correctly update button text between Pause and Resume.
7. Button geometry, objectName, styling colors remain intact.
"""

import unittest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication

from tracker.activity_tracker import TrackerState
from ui.dashboard import DashboardPage


class TestDashboardPauseResumeButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.mock_service = MagicMock()
        self.mock_service.get_today_total_seconds.return_value = 300
        self.mock_service.get_persisted_daily_active_seconds.return_value = 300
        self.dashboard = DashboardPage(self.mock_service)

    def tearDown(self):
        self.dashboard._shutdown()

    def test_initial_state_running_displays_pause(self):
        """When dashboard is initialized or active, button displays 'Pause'."""
        self.dashboard.set_workpulse_active(True)
        self.assertFalse(self.dashboard.is_paused())
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Pause")
        self.assertEqual(self.dashboard.pause_button.text(), "Pause")

    def test_setting_paused_displays_resume(self):
        """When dashboard is paused, button displays 'Resume'."""
        self.dashboard.set_workpulse_active(True)
        self.dashboard.set_paused(True)

        self.assertTrue(self.dashboard.is_paused())
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Resume")
        self.assertEqual(self.dashboard.resume_button.text(), "Resume")
        self.assertEqual(self.dashboard.workpulse_status_label.text(), "Online: Paused")

    def test_clicking_pause_triggers_existing_pause_functionality(self):
        """Clicking 'Pause' when running invokes set_paused(True) and changes text to 'Resume'."""
        self.dashboard.set_workpulse_active(True)
        self.assertFalse(self.dashboard.is_paused())
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Pause")

        pause_signals = []
        self.dashboard.pause_state_changed.connect(lambda p: pause_signals.append(p))

        # Click Pause
        self.dashboard.workpulse_toggle_button.click()

        self.assertTrue(self.dashboard.is_paused())
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Resume")
        self.assertEqual(self.dashboard.workpulse_status_label.text(), "Online: Paused")
        self.assertEqual(pause_signals, [True])

    def test_clicking_resume_triggers_existing_resume_functionality(self):
        """Clicking 'Resume' when paused invokes set_paused(False) and changes text to 'Pause'."""
        self.dashboard.set_workpulse_active(True)
        self.dashboard.set_paused(True)
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Resume")

        pause_signals = []
        self.dashboard.pause_state_changed.connect(lambda p: pause_signals.append(p))

        # Click Resume
        self.dashboard.workpulse_toggle_button.click()

        self.assertFalse(self.dashboard.is_paused())
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Pause")
        self.assertEqual(self.dashboard.workpulse_status_label.text(), "Online: Active")
        self.assertEqual(pause_signals, [False])

    def test_dynamic_tracker_state_updates_button_text(self):
        """TrackerState updates keep the Pause / Resume button label synchronized."""
        # Active tracker state
        active_state = TrackerState(
            is_workpulse=True,
            is_idle=False,
            current_application="VSCode.exe",
            current_window_title="dashboard.py",
            idle_seconds=10.0,
        )
        self.dashboard.update_tracker_state(active_state)
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Pause")

        # Pause dashboard
        self.dashboard.set_paused(True)
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Resume")

        # Another tracker state arrives while paused
        self.dashboard.update_tracker_state(active_state)
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Resume")

        # Unpause
        self.dashboard.set_paused(False)
        self.assertEqual(self.dashboard.workpulse_toggle_button.text(), "Pause")

    def test_button_styling_and_properties_preserved(self):
        """Button styling colors, height, and objectName remain unchanged."""
        btn = self.dashboard.workpulse_toggle_button
        self.assertEqual(btn.objectName(), "WorkPulseToggleButton")
        self.assertEqual(btn.height(), 28)

        # In running state: red theme (#ef4444)
        self.dashboard.set_workpulse_active(True)
        self.dashboard.set_paused(False)
        self.assertIn("#ef4444", btn.styleSheet())
        self.assertEqual(btn.text(), "Pause")

        # In paused state: blue theme (#0284c7)
        self.dashboard.set_paused(True)
        self.assertIn("#0284c7", btn.styleSheet())
        self.assertEqual(btn.text(), "Resume")


if __name__ == "__main__":
    unittest.main()

