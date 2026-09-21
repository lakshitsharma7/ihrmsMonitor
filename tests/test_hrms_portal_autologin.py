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

        # Without config details -> default
        self.assertEqual(service.get_resolved_portal_url(), DEFAULT_PORTAL_URL.rstrip("/") + "/")

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
        """Verify open_portal_with_autologin falls back to direct URL when no credentials exist."""
        mock_open_url.return_value = True

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
        window = MainWindow()
        try:
            window._open_hrms_portal()
            mock_auto_login.assert_called_once()
        finally:
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
