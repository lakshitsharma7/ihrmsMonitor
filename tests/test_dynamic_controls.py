"""Comprehensive tests for dynamic User/Device and Logout controls."""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

# Ensure QApplication instance exists for GUI tests
_app = QApplication.instance() or QApplication([])

from services.session_service import SessionService
from services.secure_session import SessionStore
from services.sync_service import SyncService


class TestDynamicControls(unittest.TestCase):
    def setUp(self):
        SessionService().clear()
        self.settings = QSettings("Indovision", "iHRMSMonitor")
        # Clean test keys
        self.settings.remove("session/allow_user_device")
        self.settings.remove("session/allow_logout")
        self.settings.remove("api_settings/allow_user_device")
        self.settings.remove("api_settings/allow_logout")

    def tearDown(self):
        SessionService().clear()
        self.settings.remove("session/allow_user_device")
        self.settings.remove("session/allow_logout")
        self.settings.remove("api_settings/allow_user_device")
        self.settings.remove("api_settings/allow_logout")

    def test_session_service_default_permissions(self):
        """UserSession defaults allow_user_device and allow_logout to True."""
        SessionService().login(
            username="emp1",
            role="User",
            full_name="Employee One",
        )
        user = SessionService().current_user
        self.assertIsNotNone(user)
        self.assertTrue(user.allow_user_device)
        self.assertTrue(user.allow_logout)

    def test_session_service_custom_permissions(self):
        """UserSession can be initialized with disabled permissions."""
        SessionService().login(
            username="emp2",
            role="User",
            allow_user_device=False,
            allow_logout=False,
        )
        user = SessionService().current_user
        self.assertIsNotNone(user)
        self.assertFalse(user.allow_user_device)
        self.assertFalse(user.allow_logout)

    def test_session_service_update_permissions_and_listeners(self):
        """update_permissions modifies user permissions and notifies listeners."""
        SessionService().login(
            username="emp3",
            role="User",
            allow_user_device=True,
            allow_logout=True,
        )

        listener_called = []
        def listener():
            listener_called.append(True)

        SessionService().register_permission_listener(listener)

        # Update both permissions
        SessionService().update_permissions(
            allow_user_device=False,
            allow_logout=False,
        )

        user = SessionService().current_user
        self.assertFalse(user.allow_user_device)
        self.assertFalse(user.allow_logout)
        self.assertGreater(len(listener_called), 0)

        # Unregister listener
        SessionService().unregister_permission_listener(listener)
        count_before = len(listener_called)
        SessionService().update_permissions(allow_logout=True)
        self.assertEqual(len(listener_called), count_before)
        self.assertTrue(SessionService().current_user.allow_logout)

    def test_secure_session_persistence(self):
        """SessionStore saves and restores allow_user_device and allow_logout."""
        store = SessionStore()
        saved = store.save_session(
            company_code="TEST_CO",
            indo_code="EMP_001",
            api_key="API_KEY_001",
            device_token="DEV_TOK_001",
            username="emp_persist",
            full_name="Persisted User",
            user_type="User",
            employee_id="E001",
            device_info={"hostname": "Laptop1"},
            tracking_permitted=True,
            allow_user_device=False,
            allow_logout=False,
        )
        self.assertTrue(saved)

        loaded = store.load_session()
        self.assertIsNotNone(loaded)
        self.assertFalse(loaded["allow_user_device"])
        self.assertFalse(loaded["allow_logout"])

        # Test session restore
        SessionService().restore_session(
            username=loaded["username"],
            role=loaded["user_type"],
            full_name=loaded["full_name"],
            allow_user_device=loaded["allow_user_device"],
            allow_logout=loaded["allow_logout"],
            device_token=loaded["device_token"],
        )
        curr = SessionService().current_user
        self.assertFalse(curr.allow_user_device)
        self.assertFalse(curr.allow_logout)

        store.clear_session()
        self.assertIsNone(store.load_session())

    @patch("services.sync_service.requests.post")
    def test_sync_service_fetch_settings_disabled_controls(self, mock_post):
        """fetch_settings parses allow_logout: false and allow_user_device: false and updates session."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Success",
            "data": {
                "sync_interval_seconds": 120,
                "idle_threshold_seconds": 180,
                "allow_logout": False,
                "allow_user_device": False,
                "allow_start_stop_activity_tracking": False,
            }
        }
        mock_post.return_value = mock_response

        SessionService().login(
            username="test_sync_user",
            role="User",
            device_token="TOK_123",
            allow_user_device=True,
            allow_logout=True,
        )

        svc = SyncService(api_url="https://mock.api")
        settings = svc.fetch_settings()

        self.assertEqual(settings.get("allow_logout"), False)
        self.assertEqual(settings.get("allow_user_device"), False)

        curr = SessionService().current_user
        self.assertFalse(curr.allow_logout)
        self.assertFalse(curr.allow_user_device)

    @patch("services.sync_service.requests.post")
    def test_sync_service_fetch_settings_string_and_int_representations(self, mock_post):
        """fetch_settings handles '0', '1', 0, 1, 'true', 'false' from backend."""
        # Test disabled with '0'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Success",
            "data": {
                "allow_logout": "0",
                "allow_user_device_info": 0,
            }
        }
        mock_post.return_value = mock_response

        SessionService().login(
            username="test_str_user",
            role="User",
            device_token="TOK_STR",
        )

        svc = SyncService(api_url="https://mock.api")
        svc.fetch_settings()

        curr = SessionService().current_user
        self.assertFalse(curr.allow_logout)
        self.assertFalse(curr.allow_user_device)

        # Test re-enabled with '1' and 'true'
        mock_response.json.return_value = {
            "response": "Success",
            "data": {
                "allow_logout": "1",
                "allow_user_device": "true",
            }
        }
        svc.fetch_settings()
        self.assertTrue(curr.allow_logout)
        self.assertTrue(curr.allow_user_device)

    def test_main_window_apply_rbac_permissions_hides_and_shows_controls(self):
        """MainWindow._apply_rbac_permissions dynamically toggles visibility and access."""
        from unittest.mock import PropertyMock
        from ui.main_window import MainWindow

        SessionService().login(
            username="test_mw_user",
            role="User",
            allow_user_device=False,
            allow_logout=False,
        )

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "start_tracking"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                # Should be hidden initially due to allow_user_device=False, allow_logout=False
                self.assertTrue(win.user_button.isHidden())
                self.assertTrue(win.logout_button.isHidden())

                # Dynamically update permissions to True
                SessionService().update_permissions(
                    allow_user_device=True,
                    allow_logout=True,
                )
                QApplication.processEvents()

                # Should now be visible and enabled
                self.assertFalse(win.user_button.isHidden())
                self.assertTrue(win.user_button.isEnabled())
                self.assertFalse(win.logout_button.isHidden())
                self.assertTrue(win.logout_button.isEnabled())

                # Dynamically update permissions back to False
                SessionService().update_permissions(
                    allow_user_device=False,
                    allow_logout=False,
                )
                QApplication.processEvents()

                self.assertTrue(win.user_button.isHidden())
                self.assertTrue(win.logout_button.isHidden())
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    def test_controls_guard_blocks_when_disabled(self):
        """_show_user_device_info and logout return early when permissions are False."""
        from unittest.mock import PropertyMock
        from ui.main_window import MainWindow

        SessionService().login(
            username="test_guard_user",
            role="User",
            allow_user_device=False,
            allow_logout=False,
        )

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "start_tracking"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"), \
             patch("ui.main_window.UserDeviceDialog") as mock_dialog, \
             patch.object(MainWindow, "stop_tracking") as mock_stop_tracking:
            win = MainWindow()
            try:
                # Attempt to open user device info
                win._show_user_device_info()
                mock_dialog.assert_not_called()

                # Attempt to logout
                win.logout()
                mock_stop_tracking.assert_not_called()
                # User should still be logged in
                self.assertIsNotNone(SessionService().current_user)
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
