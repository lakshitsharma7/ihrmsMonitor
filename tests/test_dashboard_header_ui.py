"""Tests for Dashboard Header UI enhancements: HRMS button with embedded logo icon."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from services.session_service import SessionService
from ui.main_window import MainWindow, _asset_path


class TestDashboardHeaderUI(unittest.TestCase):
    def setUp(self):
        SessionService().clear()
        SessionService().login(
            username="testuser",
            role="User",
            full_name="John Doe",
        )

    def tearDown(self):
        SessionService().clear()

    def test_hrms_button_exists_and_has_logo_icon(self):
        """Verify HRMS button exists in header and has logo icon loaded from assets/ihrms_icon.png."""
        window = MainWindow()
        try:
            self.assertTrue(hasattr(window, "hrms_button"))
            self.assertIsNotNone(window.hrms_button)
            self.assertIn("HRMS", window.hrms_button.text())

            # Asset exists on disk
            asset_file = _asset_path(os.path.join("assets", "ihrms_icon.png"))
            self.assertTrue(os.path.isfile(asset_file), f"Asset file missing: {asset_file}")

            # Icon assigned to HRMS button
            icon = window.hrms_button.icon()
            self.assertFalse(icon.isNull(), "HRMS button icon should not be null")
        finally:
            window.close()
            window.deleteLater()

    def test_header_welcome_label(self):
        """Verify Welcome label displays the current user's name."""
        window = MainWindow()
        try:
            self.assertTrue(hasattr(window, "user_label"))
            self.assertEqual(window.user_label.text(), "Welcome, John Doe")
        finally:
            window.close()
            window.deleteLater()

    @patch("ui.main_window.QDesktopServices.openUrl")
    def test_open_hrms_portal_desktop_services(self, mock_open_url):
        """Verify _open_hrms_portal opens https://ihrms.indovisionservices.in via QDesktopServices."""
        mock_open_url.return_value = True
        window = MainWindow()
        try:
            window._open_hrms_portal()
            mock_open_url.assert_called_once()
            called_url = mock_open_url.call_args[0][0]
            self.assertEqual(called_url.toString(), "https://ihrms.indovisionservices.in")
        finally:
            window.close()
            window.deleteLater()

    @patch("ui.main_window.webbrowser.open")
    @patch("ui.main_window.QDesktopServices.openUrl")
    def test_open_hrms_portal_fallback_to_webbrowser(self, mock_open_url, mock_browser_open):
        """Verify fallback to webbrowser if QDesktopServices fails or returns False."""
        mock_open_url.return_value = False
        window = MainWindow()
        try:
            window._open_hrms_portal()
            mock_browser_open.assert_called_once_with("https://ihrms.indovisionservices.in")
        finally:
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
