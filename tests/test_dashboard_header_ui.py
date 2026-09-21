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

    def test_hrms_button_exists_and_has_globe_icon(self):
        """Verify HRMS button exists in header and has globe icon loaded from assets/icons/globe."""
        window = MainWindow()
        try:
            self.assertTrue(hasattr(window, "hrms_button"))
            self.assertIsNotNone(window.hrms_button)
            self.assertIn("HRMS", window.hrms_button.text())

            # Asset exists on disk
            asset_svg = _asset_path(os.path.join("assets", "icons", "globe.svg"))
            asset_png = _asset_path(os.path.join("assets", "icons", "globe.png"))
            self.assertTrue(
                os.path.isfile(asset_svg) or os.path.isfile(asset_png),
                "Globe asset file missing from assets/icons/",
            )

            # Icon assigned to HRMS button
            icon = window.hrms_button.icon()
            self.assertFalse(icon.isNull(), "HRMS button globe icon should not be null")
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

    def test_header_welcome_label_dynamic_user_name(self):
        """Verify Welcome label dynamically displays actual logged in user name or username."""
        SessionService().login(
            username="lakshit.sharma",
            role="User",
            full_name="Lakshit Sharma",
        )
        window = MainWindow()
        try:
            self.assertEqual(window.user_label.text(), "Welcome, Lakshit Sharma")
        finally:
            window.close()
            window.deleteLater()

    def test_header_welcome_label_ignores_persisted_user_placeholder(self):
        """Verify Welcome label does not display 'Persisted User' and falls back to actual username/employee_id."""
        SessionService().login(
            username="lakshit.s",
            role="User",
            full_name="Persisted User",
            employee_id="EMP_9988",
        )
        window = MainWindow()
        try:
            self.assertEqual(window.user_label.text(), "Welcome, lakshit.s")
        finally:
            window.close()
            window.deleteLater()

    def test_header_welcome_label_updates_on_user_switch(self):
        """Verify Welcome label updates dynamically when user session changes."""
        SessionService().login(
            username="user_first",
            role="User",
            full_name="First User",
        )
        window = MainWindow()
        try:
            self.assertEqual(window.user_label.text(), "Welcome, First User")
            
            # Switch to new user
            SessionService().login(
                username="user_second",
                role="User",
                full_name="Second User",
            )
            window._apply_rbac_permissions()
            self.assertEqual(window.user_label.text(), "Welcome, Second User")
        finally:
            window.close()
            window.deleteLater()



    @patch("services.hrms_portal_service.QDesktopServices.openUrl")
    def test_open_hrms_portal_desktop_services(self, mock_open_url):
        """Verify _open_hrms_portal opens portal auto-login bridge via QDesktopServices for logged-in user."""
        mock_open_url.return_value = True
        window = MainWindow()
        try:
            window._open_hrms_portal()
            mock_open_url.assert_called_once()
            called_url = mock_open_url.call_args[0][0]
            # Since user is authenticated in setUp, local file bridge is generated
            self.assertTrue(called_url.isLocalFile())
            self.assertTrue(called_url.toLocalFile().endswith(".html"))
            with open(called_url.toLocalFile(), "r", encoding="utf-8") as f:
                html_body = f.read()
            self.assertIn("indovisionservices.in", html_body)
            self.assertIn("testuser", html_body)
        finally:
            window.close()
            window.deleteLater()

    @patch("services.hrms_portal_service.webbrowser.open")
    @patch("services.hrms_portal_service.QDesktopServices.openUrl")
    def test_open_hrms_portal_fallback_to_webbrowser(self, mock_open_url, mock_browser_open):
        """Verify fallback to webbrowser if QDesktopServices fails or returns False."""
        mock_open_url.return_value = False
        window = MainWindow()
        try:
            window._open_hrms_portal()
            mock_browser_open.assert_called_once()
            called_arg = mock_browser_open.call_args[0][0]
            self.assertTrue(called_arg.startswith("file:///") and called_arg.endswith(".html"))
        finally:
            window.close()
            window.deleteLater()



if __name__ == "__main__":
    unittest.main()
