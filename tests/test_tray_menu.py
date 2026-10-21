"""Unit tests for System Tray menu.

Verifies:
1. Exit action is removed from the background system tray context menu by default.
2. Other necessary menu actions (Show Dashboard, Start WorkPulse, Stop WorkPulse, Today's Activity, Settings, Check for Updates) remain present.
"""

import unittest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication, QWidget
from system.tray import TrayController


class TestTrayMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_exit_option_removed_from_tray_menu(self):
        parent = QWidget()
        on_show_dashboard = MagicMock()
        on_start_workpulse = MagicMock()
        on_stop_workpulse = MagicMock()
        on_show_today = MagicMock()
        on_show_settings = MagicMock()
        on_exit = MagicMock()
        on_check_updates = MagicMock()

        tray = TrayController(
            parent=parent,
            on_show_dashboard=on_show_dashboard,
            on_start_workpulse=on_start_workpulse,
            on_stop_workpulse=on_stop_workpulse,
            on_show_today_activity=on_show_today,
            on_show_settings=on_show_settings,
            on_exit=on_exit,
            on_check_updates=on_check_updates,
        )

        menu = tray.tray_icon.contextMenu()
        self.assertIsNotNone(menu)

        action_texts = [action.text() for action in menu.actions() if not action.isSeparator()]
        
        # Verify Exit is NOT present
        self.assertNotIn("Exit", action_texts, "Exit option should be removed from the background tray menu")
        self.assertIsNone(tray.exit_action)

        # Verify other essential actions are present
        self.assertIn("Show Dashboard", action_texts)
        self.assertIn("Start Tracking", action_texts)
        self.assertIn("Stop Tracking", action_texts)
        self.assertIn("Today's Activity", action_texts)
        self.assertIn("Settings", action_texts)
        self.assertIn("Check for Updates", action_texts)


if __name__ == "__main__":
    unittest.main()
