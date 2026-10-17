"""Tests for iHRMS Desktop background-running behavior, window visibility, and startup registration."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QDir
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from config.settings import APP_NAME
from system import startup


# Ensure single QApplication exists across test suite
app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestBackgroundModeAndVisibility(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(__file__).resolve().parent / "temp_test_bg"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.fake_exe = self.temp_dir / "iHRMS-Desktop.exe"
        self.fake_exe.write_text("MZ fake executable header")

    def tearDown(self):
        try:
            if self.fake_exe.exists():
                self.fake_exe.unlink()
            if self.temp_dir.exists():
                self.temp_dir.rmdir()
        except Exception:
            pass

    def test_01_background_cli_flags_recognition(self):
        """Verify all supported background startup CLI arguments are properly detected."""
        valid_startup_flags = [
            "--startup",
            "/startup",
            "--background",
            "/background",
            "--minimized",
            "/minimized",
            "--autostart",
            "/autostart",
            "--hidden",
            "/hidden",
            "--silent",
            "/silent",
            "-s",
            "/s",
            "-b",
            "/b",
        ]

        def check_is_startup(argv):
            return any(
                arg.lower() in (
                    "--startup",
                    "/startup",
                    "-startup",
                    "--minimized",
                    "/minimized",
                    "-minimized",
                    "--background",
                    "/background",
                    "-background",
                    "--autostart",
                    "/autostart",
                    "-autostart",
                    "--hidden",
                    "/hidden",
                    "-hidden",
                    "--silent",
                    "/silent",
                    "-silent",
                    "-s",
                    "/s",
                    "-b",
                    "/b",
                )
                for arg in argv[1:]
            )

        for flag in valid_startup_flags:
            self.assertTrue(
                check_is_startup(["app.py", flag]),
                f"Flag {flag} should be recognized as background startup",
            )

        # Normal launch without background flags should evaluate to False
        self.assertFalse(check_is_startup(["app.py"]))
        self.assertFalse(check_is_startup(["app.py", "--normal-arg"]))

    def test_02_startup_registration_uses_ihrms_desktop_identity(self):
        """Verify Windows startup registry key uses 'iHRMS Desktop' and clean command."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.CreateKeyEx.return_value.__enter__.return_value = mock_key

        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            success = startup._windows_set_enabled(True, exe_path=str(self.fake_exe))
            self.assertTrue(success)
            mock_winreg.SetValueEx.assert_called_once()
            args = mock_winreg.SetValueEx.call_args[0]
            # Key name must be 'iHRMS Desktop' for Windows Task Manager Startup list
            self.assertEqual(args[1], "iHRMS Desktop")
            self.assertIn("--startup", args[4])
            self.assertIn(str(self.fake_exe), args[4])

    def test_03_mainwindow_is_background_hidden_on_init(self):
        """Verify MainWindow(is_background=True) starts with window hidden and tray icon active."""
        from ui.main_window import MainWindow

        with patch("win32gui.ShowWindow") as mock_show_window, \
             patch("tracker.tracker_worker.build_tracker_thread"), \
             patch("services.sync_service.SyncService.fetch_settings"):

            window = MainWindow(login_window=None, is_background=True)
            try:
                self.assertTrue(window._is_background)
                self.assertFalse(window.isVisible())
                # Verify tray was initialized and available
                self.assertIsNotNone(window.tray)
                # Verify native ShowWindow SW_HIDE was invoked if on Windows
                if sys.platform.startswith("win"):
                    mock_show_window.assert_called()
                    last_show_arg = mock_show_window.call_args[0][1]
                    import win32con
                    self.assertEqual(last_show_arg, win32con.SW_HIDE)
            finally:
                window._shutdown()
                window.deleteLater()

    def test_04_show_and_raise_restores_visibility_and_taskbar(self):
        """Verify _show_and_raise makes the window visible and marks is_background as False."""
        from ui.main_window import MainWindow

        with patch("win32gui.ShowWindow") as mock_show_window, \
             patch("win32gui.SetForegroundWindow"), \
             patch("tracker.tracker_worker.build_tracker_thread"), \
             patch("services.sync_service.SyncService.fetch_settings"):

            window = MainWindow(login_window=None, is_background=True)
            try:
                self.assertFalse(window.isVisible())
                # Trigger show and raise (user clicks tray icon or launches app shortcut)
                window._show_and_raise()
                self.assertFalse(window._is_background)
                self.assertTrue(window.isVisible())
                if sys.platform.startswith("win"):
                    mock_show_window.assert_called()
            finally:
                window._shutdown()
                window.deleteLater()

    def test_05_close_event_minimizes_to_tray_without_killing_tracker(self):
        """Verify closing the window hides it back to tray without killing tracking or exiting."""
        from ui.main_window import MainWindow

        with patch("win32gui.ShowWindow") as mock_show_window, \
             patch("tracker.tracker_worker.build_tracker_thread"), \
             patch("services.sync_service.SyncService.fetch_settings"):

            window = MainWindow(login_window=None, is_background=False)
            try:
                window.show()
                self.assertTrue(window.isVisible())

                # Simulate user clicking close button [X]
                close_event = QCloseEvent()
                window.closeEvent(close_event)

                # The event should be ignored (not closing app) and window hidden
                self.assertFalse(close_event.isAccepted())
                self.assertFalse(window.isVisible())
                self.assertFalse(window._really_quit)
            finally:
                window._shutdown()
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
