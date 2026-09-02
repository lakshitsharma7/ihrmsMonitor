"""Unit tests for Login/Session persistence, offline restoration, and Dashboard startup."""

import unittest
from unittest.mock import patch, MagicMock
from services.secure_session import SessionStore
from config.api_config import ApiConfig, ApiConfigError
from services.session_service import SessionService


class TestSessionPersistence(unittest.TestCase):

    def setUp(self):
        self.store = SessionStore()
        self.store.clear_session()
        ApiConfig().reset()
        SessionService().clear()

    def tearDown(self):
        self.store.clear_session()
        ApiConfig().reset()
        SessionService().clear()

    def test_save_and_load_session_with_base_url(self):
        """Verify that save_session securely persists all fields including base_url and company_id."""
        saved = self.store.save_session(
            company_code="INDO",
            indo_code="EMP_001",
            api_key="API_KEY_SECRET",
            device_token="DEV_TOKEN_123",
            username="john_doe",
            full_name="John Doe",
            user_type="User",
            employee_id="101",
            device_info={"os": "Windows", "hostname": "WORKSTATION"},
            tracking_permitted=True,
            base_url="https://hrms.indovision.in/api",
            company_id="42",
        )
        self.assertTrue(saved)

        loaded = self.store.load_session()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["company_code"], "INDO")
        self.assertEqual(loaded["indo_code"], "EMP_001")
        self.assertEqual(loaded["api_key"], "API_KEY_SECRET")
        self.assertEqual(loaded["device_token"], "DEV_TOKEN_123")
        self.assertEqual(loaded["username"], "john_doe")
        self.assertEqual(loaded["full_name"], "John Doe")
        self.assertEqual(loaded["user_type"], "User")
        self.assertEqual(loaded["employee_id"], "101")
        self.assertEqual(loaded["base_url"], "https://hrms.indovision.in/api")
        self.assertEqual(loaded["company_id"], "42")
        self.assertTrue(loaded["tracking_permitted"])

    def test_clear_session_removes_all_keys(self):
        """Explicit logout/clear removes all persisted keys."""
        self.store.save_session(
            company_code="INDO",
            indo_code="EMP_001",
            api_key="API_KEY_SECRET",
            device_token="DEV_TOKEN_123",
            username="john_doe",
            full_name="John Doe",
            user_type="User",
            employee_id="101",
            device_info={},
            tracking_permitted=True,
            base_url="https://hrms.indovision.in/api",
            company_id="42",
        )
        self.assertTrue(self.store.validate_session())

        self.store.clear_session()
        self.assertFalse(self.store.validate_session())
        self.assertIsNone(self.store.load_session())

    def test_apiconfig_set_cached_configuration(self):
        """Verify ApiConfig can adopt pre-verified configuration directly."""
        api_cfg = ApiConfig()
        api_cfg.set_cached_configuration(
            company_code="INDO",
            base_url="https://hrms.indovision.in/api",
            company_id="42",
        )
        self.assertTrue(api_cfg.is_verified)
        self.assertEqual(api_cfg.company_code, "INDO")
        self.assertEqual(api_cfg.base_url, "https://hrms.indovision.in/api")
        self.assertEqual(api_cfg.company_id, "42")

    def test_apiconfig_offline_fallback(self):
        """When online verification fails, ApiConfig falls back to cached configuration if available."""
        api_cfg = ApiConfig()
        
        # Pre-seed cache in settings
        from PySide6.QtCore import QSettings
        st = QSettings("Indovision", "iHRMSMonitor")
        st.setValue("ApiConfig/last_verified_code", "INDO")
        st.setValue("ApiConfig/last_base_url", "https://hrms.indovision.in/api")
        st.setValue("ApiConfig/last_company_id", "42")

        # Mock network request failing (e.g. offline on system boot)
        with patch("requests.post", side_effect=Exception("Connection timed out")):
            api_cfg.load(company_code="INDO", force=False)

        self.assertTrue(api_cfg.is_verified)
        self.assertEqual(api_cfg.company_code, "INDO")
        self.assertEqual(api_cfg.base_url, "https://hrms.indovision.in/api")
        self.assertEqual(api_cfg.company_id, "42")

    def test_session_restoration_to_dashboard(self):
        """Simulate app startup restoring session directly into Dashboard without login."""
        # 1. Save valid session
        self.store.save_session(
            company_code="INDO",
            indo_code="EMP_001",
            api_key="KEY_123",
            device_token="TOKEN_ABC",
            username="john_doe",
            full_name="John Doe",
            user_type="User",
            employee_id="101",
            device_info={},
            tracking_permitted=True,
            base_url="https://hrms.indovision.in/api",
            company_id="42",
        )

        # 2. Simulate startup logic
        loaded = self.store.load_session()
        self.assertIsNotNone(loaded)

        api_cfg = ApiConfig()
        api_cfg.set_cached_configuration(
            company_code=loaded["company_code"],
            base_url=loaded["base_url"],
            company_id=loaded.get("company_id"),
        )

        session_svc = SessionService()
        session_svc.restore_session(
            username=loaded["username"],
            role=loaded["user_type"],
            full_name=loaded.get("full_name"),
            user_type=loaded["user_type"],
            tracking_permitted=loaded.get("tracking_permitted", True),
            indo_code=loaded["indo_code"],
            api_key=loaded["api_key"],
            employee_id=loaded.get("employee_id"),
            company_code=loaded["company_code"],
            device_token=loaded["device_token"],
        )

        # 3. Verify user and device context are fully restored
        self.assertIsNotNone(session_svc.current_user)
        self.assertEqual(session_svc.current_user.username, "john_doe")
        self.assertEqual(session_svc.current_user.employee_id, "101")
        self.assertEqual(session_svc.device_token, "TOKEN_ABC")
        self.assertEqual(api_cfg.base_url, "https://hrms.indovision.in/api")


if __name__ == "__main__":
    unittest.main()
