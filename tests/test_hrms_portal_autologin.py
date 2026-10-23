"""Unit tests for HRMS Web Portal dynamic auto-login service and Dashboard integration."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from config.api_config import ApiConfig
from services.session_service import SessionService
from services.hrms_portal_service import HrmsPortalService, DEFAULT_PORTAL_URL
from ui.main_window import MainWindow


class TestHrmsPortalAutoLogin(unittest.TestCase):
    def setUp(self):
        SessionService().clear()
        ApiConfig().reset()

    def tearDown(self):
        SessionService().clear()
        ApiConfig().reset()

    def test_session_service_get_portal_credentials(self):
        """Verify SessionService returns dynamic portal credentials."""
        # Unauthenticated
        self.assertIsNone(SessionService().get_portal_credentials())

        # Authenticated with session_credential
        SessionService().login(
            username="dinesh",
            role="User",
            full_name="Dinesh Kumar",
            session_credential="my_secure_password_123",
        )
        creds = SessionService().get_portal_credentials()
        self.assertIsNotNone(creds)
        self.assertEqual(creds["user_name"], "dinesh")
        self.assertEqual(creds["password"], "my_secure_password_123")

    def test_get_resolved_portal_url_from_app_controller_details(self):
        """Verify portal URL is dynamically resolved from AppController details."""
        service = HrmsPortalService()

        # Without config details and unverified -> None (never leak Indovision)
        self.assertIsNone(service.get_resolved_portal_url())

        # With AppController portal_url
        ApiConfig().set_cached_configuration(
            company_code="TEST_CORP",
            base_url="https://api.testcorp.com/hrms_api/ci4/api",
            details={"portal_url": "https://hrms.testcorp.com/portal"},
        )
        self.assertEqual(service.get_resolved_portal_url(), "https://hrms.testcorp.com/portal/")

    def test_get_resolved_portal_url_derived_from_base_url(self):
        """Verify portal URL is derived from base_url if portal_url is absent in details."""
        service = HrmsPortalService()
        ApiConfig().set_cached_configuration(
            company_code="TEST_CORP",
            base_url="https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api",
            details={},
        )
        self.assertEqual(service.get_resolved_portal_url(), "https://softdev.indovisionservices.in/ihrms84/")

    def test_generate_autologin_html_contains_required_elements(self):
        """Verify generated auto-login HTML contains dynamic user details and portal endpoints."""
        service = HrmsPortalService()
        portal_url = "https://custom.hrms.com/"
        username = "emp_john"
        password = "secret_password"

        html_code = service.generate_autologin_html(
            portal_url=portal_url,
            username=username,
            password=password,
        )

        self.assertIn("emp_john", html_code)
        self.assertIn("https://custom.hrms.com/ajax/check-user.php", html_code)
        self.assertIn("https://custom.hrms.com/login.php", html_code)
        self.assertIn("fetch", html_code)
        self.assertIn("window.location.replace", html_code)

    @patch("services.hrms_portal_service.QDesktopServices.openUrl")
    def test_open_portal_with_autologin_authenticated(self, mock_open_url):
        """Verify open_portal_with_autologin creates temp HTML bridge and opens local file URL."""
        mock_open_url.return_value = True

        SessionService().login(
            username="emp_active",
            role="User",
            full_name="Active Employee",
            indo_code="EC-999",
            employee_id="999",
            company_code="CORP_X",
            portal_url="https://hrms.corpx.com/",
            raw_login_data={
                "data": {
                    "email": "active.emp@example.com",
                    "user_type": "Staff",
                }
            },
            session_credential="test_pwd_xyz",
        )

        service = HrmsPortalService()
        result = service.open_portal_with_autologin()

        self.assertTrue(result)
        mock_open_url.assert_called_once()
        opened_qurl = mock_open_url.call_args[0][0]
        self.assertTrue(opened_qurl.isLocalFile())
        self.assertTrue(opened_qurl.toLocalFile().endswith(".html"))

        # Verify contents of generated file
        with open(opened_qurl.toLocalFile(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("emp_active", content)
        self.assertIn("EC-999", content)
        self.assertIn("CORP_X", content)
        self.assertIn("active.emp@example.com", content)

    def test_session_service_extracts_nested_user_details(self):
        """Verify SessionService extracts non-sensitive fields from raw_login_data nested structure."""
        SessionService().login(
            username="test_nested",
            role="User",
            full_name="Nested User",
            raw_login_data={
                "data": {
                    "employee_id": "EMP-456",
                    "emp_code": "EC-456",
                    "company_code": "COMP_NESTED",
                    "email": "nested@example.com",
                    "user_type": "employee",
                }
            }
        )
        creds = SessionService().get_portal_credentials()
        self.assertIsNotNone(creds)
        self.assertEqual(creds["user_name"], "test_nested")
        self.assertEqual(creds["employee_id"], "EMP-456")
        self.assertEqual(creds["employee_code"], "EC-456")
        self.assertEqual(creds["indo_code"], "EC-456")
        self.assertEqual(creds["company_code"], "COMP_NESTED")
        self.assertEqual(creds["email"], "nested@example.com")
        self.assertEqual(creds["user_type"], "employee")
        self.assertEqual(creds["full_name"], "Nested User")

    @patch("services.hrms_portal_service.QDesktopServices.openUrl")
    def test_open_portal_fallback_when_unauthenticated(self, mock_open_url):
        """Verify open_portal_with_autologin falls back to direct URL when no credentials exist for verified company."""
        mock_open_url.return_value = True

        ApiConfig().set_cached_configuration(
            company_code="INDO_TEST",
            base_url="https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api",
            details={"portal_url": "https://softdev.indovisionservices.in/ihrms84/"},
        )

        service = HrmsPortalService()
        result = service.open_portal_with_autologin()

        self.assertTrue(result)
        mock_open_url.assert_called_once()
        opened_qurl = mock_open_url.call_args[0][0]
        self.assertFalse(opened_qurl.isLocalFile())
        self.assertIn("indovisionservices.in", opened_qurl.toString())

    @patch("services.hrms_portal_service.HrmsPortalService.open_portal_with_autologin")
    def test_main_window_hrms_button_triggers_portal_service(self, mock_auto_login):
        """Verify MainWindow._open_hrms_portal delegates to HrmsPortalService."""
        mock_auto_login.return_value = True
        ApiConfig().set_cached_configuration(
            company_code="TEST_CORP",
            base_url="https://api.testcorp.com/hrms_api/ci4/api",
            details={"portal_url": "https://hrms.testcorp.com/portal"},
        )
        with patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"), \
             patch.object(MainWindow, "_build_tracker"), \
             patch.object(MainWindow, "_build_tray"), \
             patch.object(MainWindow, "start_workpulse"):
            window = MainWindow()
            try:
                window._open_hrms_portal()
                mock_auto_login.assert_called_once()
            finally:
                window.close()
                window.deleteLater()

    def test_company_a_alphabridge_portal_url(self):
        """Company A login -> Company A portal URL."""
        ApiConfig().set_cached_configuration(
            company_code="ALPHA12C1R112021",
            base_url="https://www.alphabridge.tech/ihrms/hrms_api/ci4/api/",
            details={"portal_url": None},
        )
        service = HrmsPortalService()
        self.assertEqual(service.get_resolved_portal_url(), "https://www.alphabridge.tech/ihrms/")

    def test_company_b_indovision_portal_url(self):
        """Company B login -> Company B portal URL."""
        ApiConfig().set_cached_configuration(
            company_code="INDO_CORP",
            base_url="https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api",
            details={"portal_url": "https://softdev.indovisionservices.in/ihrms84/"},
        )
        service = HrmsPortalService()
        self.assertEqual(service.get_resolved_portal_url(), "https://softdev.indovisionservices.in/ihrms84/")

    def test_switching_companies_updates_portal_url_and_tooltip(self):
        """Switching companies -> URL and tooltip update."""
        # 1. Company A
        ApiConfig().set_cached_configuration(
            company_code="ALPHA12C1R112021",
            base_url="https://www.alphabridge.tech/ihrms/hrms_api/ci4/api/",
            details={},
        )
        service = HrmsPortalService()
        self.assertEqual(service.get_resolved_portal_url(), "https://www.alphabridge.tech/ihrms/")
        with patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"), \
             patch.object(MainWindow, "_build_tracker"), \
             patch.object(MainWindow, "_build_tray"), \
             patch.object(MainWindow, "start_workpulse"):
            win = MainWindow()
            try:
                win._update_portal_tooltip()
                self.assertIn("https://www.alphabridge.tech/ihrms/", win.hrms_button.toolTip())

                # 2. Switch to Company B
                ApiConfig().reset()
                ApiConfig().set_cached_configuration(
                    company_code="INDO_42",
                    base_url="https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api",
                    details={"portal_url": "https://softdev.indovisionservices.in/ihrms84/"},
                )
                self.assertEqual(service.get_resolved_portal_url(), "https://softdev.indovisionservices.in/ihrms84/")
                win._update_portal_tooltip()
                self.assertIn("https://softdev.indovisionservices.in/ihrms84/", win.hrms_button.toolTip())
                self.assertNotIn("alphabridge.tech", win.hrms_button.toolTip())
            finally:
                win.close()
                win.deleteLater()

    @patch("services.hrms_portal_service.QDesktopServices.openUrl")
    def test_missing_url_no_incorrect_portal_opens(self, mock_open_url):
        """Missing URL -> No incorrect portal opens and action returns False."""
        ApiConfig().reset()
        ApiConfig().set_cached_configuration(
            company_code="UNKNOWN_CO",
            base_url="",
            details={},
        )
        service = HrmsPortalService()
        self.assertIsNone(service.get_resolved_portal_url())
        result = service.open_portal_with_autologin()
        self.assertFalse(result)
        mock_open_url.assert_not_called()

    def test_logout_clears_portal_url(self):
        """Logout -> Previous company URL is cleared."""
        ApiConfig().set_cached_configuration(
            company_code="ALPHA12C1R112021",
            base_url="https://www.alphabridge.tech/ihrms/hrms_api/ci4/api/",
            details={},
        )
        service = HrmsPortalService()
        self.assertIsNotNone(service.get_resolved_portal_url())

        # Simulate logout / company context reset
        ApiConfig().reset()
        SessionService().clear()
        self.assertIsNone(service.get_resolved_portal_url())


if __name__ == "__main__":
    unittest.main()
