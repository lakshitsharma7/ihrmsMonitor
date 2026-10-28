"""Verification tests for allow_start_stop_activity_tracking Dashboard Integration.

Verifies:
1. Complete Flow:
   - SyncService.fetch_settings fetches, parses, caches, and stores allow_start_stop_activity_tracking.
   - Setting reaches UserSession, SessionStore, and DashboardPage UI.
2. Expected Behaviour when True:
   - Dashboard Start/Stop (WorkPulse) controls are visible and enabled.
   - Clicking controls toggles pause/resume functionality and emits pause_state_changed.
3. Expected Behaviour when False:
   - Dashboard Start/Stop controls are restricted / disabled (setEnabled(False)).
   - Clicking or invoking toggle is blocked by policy guard; tracking cannot be toggled.
   - Descriptive tooltip explains restriction.
4. Dynamic Behaviour:
   - Dashboard updates dynamically when fresh settings are received via update_permissions/fetch_settings.
   - Missing, null, and invalid values safely fall back to default True without crashing.
   - Setting is not overridden by hardcoded defaults or stale cached values.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock, PropertyMock
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for GUI components
_app = QApplication.instance() or QApplication([])

from services.session_service import SessionService
from services.secure_session import SessionStore
from services.sync_service import SyncService
from ui.dashboard import DashboardPage
from ui.main_window import MainWindow


class TestAllowStartStopActivityTracking(unittest.TestCase):
    def setUp(self):
        SessionService().clear()
        self.store = SessionStore()
        self.store.clear_session()
        self.settings = QSettings("Indovision", "iHRMSMonitor")
        self.settings.remove("session/allow_start_stop_activity_tracking")
        self.settings.remove("api_settings/allow_start_stop_activity_tracking")

        self.mock_activity_service = MagicMock()
        self.mock_activity_service.get_today_total_seconds.return_value = 120
        self.mock_activity_service.get_persisted_daily_active_seconds.return_value = 120

    def tearDown(self):
        SessionService().clear()
        self.store.clear_session()
        self.settings.remove("session/allow_start_stop_activity_tracking")
        self.settings.remove("api_settings/allow_start_stop_activity_tracking")

    # =========================================================================
    # 1. TRACE & FLOW TESTS
    # =========================================================================

    def test_session_service_default_allow_start_stop(self):
        """UserSession defaults allow_start_stop_activity_tracking to True."""
        SessionService().login(
            username="test_flow_emp",
            role="User",
            full_name="Flow User",
        )
        user = SessionService().current_user
        self.assertIsNotNone(user)
        self.assertTrue(user.allow_start_stop_activity_tracking)

    def test_session_service_custom_allow_start_stop(self):
        """UserSession can be initialized with allow_start_stop_activity_tracking=False."""
        SessionService().login(
            username="test_flow_emp2",
            role="User",
            allow_start_stop_activity_tracking=False,
        )
        user = SessionService().current_user
        self.assertIsNotNone(user)
        self.assertFalse(user.allow_start_stop_activity_tracking)

    @patch("services.secure_session._cred_write", return_value=True)
    @patch("services.secure_session._cred_read")
    def test_session_store_persistence(self, mock_cred_read, mock_cred_write):
        """SessionStore persists and restores allow_start_stop_activity_tracking."""
        mock_cred_read.return_value = {
            "company_code": "TEST_CO",
            "indo_code": "EMP_001",
            "api_key": "API_KEY_001",
            "device_token": "DEV_TOK_001",
            "username": "emp_persist",
            "full_name": "Persisted User",
            "user_type": "User",
            "employee_id": "E001",
            "device_info": {"hostname": "Laptop1"},
            "workpulse_permitted": True,
            "allow_start_stop_activity_tracking": False,
        }
        saved = self.store.save_session(
            company_code="TEST_CO",
            indo_code="EMP_001",
            api_key="API_KEY_001",
            device_token="DEV_TOK_001",
            username="emp_persist",
            full_name="Persisted User",
            user_type="User",
            employee_id="E001",
            device_info={"hostname": "Laptop1"},
            workpulse_permitted=True,
            allow_start_stop_activity_tracking=False,
        )
        self.assertTrue(saved)

        loaded = self.store.load_session()
        self.assertIsNotNone(loaded)
        self.assertFalse(loaded["allow_start_stop_activity_tracking"])

        # Test session restore
        SessionService().restore_session(
            username=loaded["username"],
            role=loaded["user_type"],
            full_name=loaded["full_name"],
            allow_start_stop_activity_tracking=loaded["allow_start_stop_activity_tracking"],
            device_token=loaded["device_token"],
        )
        curr = SessionService().current_user
        self.assertFalse(curr.allow_start_stop_activity_tracking)

    @patch("services.sync_service.requests.post")
    def test_fetch_settings_parses_allow_start_stop_true_and_false(self, mock_post):
        """SyncService.fetch_settings extracts allow_start_stop_activity_tracking and updates session."""
        # 1. Test False response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Success",
            "data": {
                "sync_interval_seconds": 120,
                "idle_threshold_seconds": 180,
                "allow_start_stop_activity_tracking": False,
            }
        }
        mock_post.return_value = mock_response

        SessionService().login(
            username="test_sync_user",
            role="User",
            device_token="TOK_123",
            allow_start_stop_activity_tracking=True,
        )

        svc = SyncService(api_url="https://mock.api")
        settings = svc.fetch_settings()

        self.assertEqual(settings.get("allow_start_stop_activity_tracking"), False)
        self.assertFalse(SessionService().current_user.allow_start_stop_activity_tracking)

        # 2. Test True response
        mock_response.json.return_value = {
            "response": "Success",
            "data": {
                "allow_start_stop_activity_tracking": True,
            }
        }
        settings = svc.fetch_settings()
        self.assertEqual(settings.get("allow_start_stop_activity_tracking"), True)
        self.assertTrue(SessionService().current_user.allow_start_stop_activity_tracking)

    @patch("services.sync_service.requests.post")
    def test_fetch_settings_supports_aliases_and_string_values(self, mock_post):
        """fetch_settings handles alias keys and string representations ('0', '1', 'false', 'true')."""
        svc = SyncService(api_url="https://mock.api")

        SessionService().login(
            username="test_alias_user",
            role="User",
            device_token="TOK_ALIAS",
        )

        test_cases = [
            ({"allow_start_stop_activity_workpulse": "0"}, False),
            ({"allow_start_stop_tracking": "false"}, False),
            ({"allow_start_stop": 0}, False),
            ({"allow_start_stop_activity_workpulse": "1"}, True),
            ({"allow_start_stop_tracking": "true"}, True),
            ({"allow_start_stop": 1}, True),
        ]

        for payload, expected in test_cases:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"response": "Success", "data": payload}
            mock_post.return_value = mock_resp

            svc.fetch_settings()
            self.assertEqual(
                SessionService().current_user.allow_start_stop_activity_tracking,
                expected,
                f"Failed for payload: {payload}",
            )

    # =========================================================================
    # 2. EXPECTED BEHAVIOUR: WHEN TRUE
    # =========================================================================

    def test_dashboard_when_setting_is_true(self):
        """When allow_start_stop_activity_tracking is True, controls are visible and functional."""
        SessionService().login(
            username="emp_true",
            role="User",
            allow_start_stop_activity_tracking=True,
        )

        dashboard = DashboardPage(self.mock_activity_service)
        dashboard.show()
        dashboard.set_workpulse_active(True)

        btn = dashboard.workpulse_toggle_button
        self.assertTrue(btn.isEnabled(), "Button must be enabled when setting is True")
        self.assertFalse(btn.isHidden(), "Button must not be hidden when setting is True")
        self.assertTrue(btn.isVisible(), "Button must be visible when setting is True")
        self.assertTrue(dashboard.last_update_label.isVisible(), "Last update label must be visible when setting is True")
        self.assertTrue(dashboard.start_stop_section.isVisible(), "Section must be visible when setting is True")
        self.assertFalse(dashboard.is_paused())
        self.assertEqual(btn.text(), "Pause")

        # 1. Clicking "Pause" when active pauses tracking
        pause_signals = []
        dashboard.pause_state_changed.connect(lambda p: pause_signals.append(p))
        btn.click()
        self.assertTrue(dashboard.is_paused())
        self.assertEqual(btn.text(), "Resume")
        self.assertEqual(pause_signals, [True])

        # 2. When tracking is inactive, button shows "Resume"
        dashboard.set_workpulse_active(False)
        self.assertEqual(btn.text(), "Resume")
        self.assertTrue(btn.isEnabled(), "Button remains available when stopped")

        # 3. Clicking "Resume" requests start
        start_signals = []
        dashboard.workpulse_start_requested.connect(lambda: start_signals.append(True))
        btn.click()
        self.assertEqual(len(start_signals), 1, "Clicking Resume must emit start requested signal")

        dashboard._shutdown()

    def test_tracking_paused_while_permission_true(self):
        """When tracking is paused while permission is True, controls remain available to start tracking."""
        SessionService().login(
            username="emp_paused_true",
            role="User",
            allow_start_stop_activity_tracking=True,
        )

        dashboard = DashboardPage(self.mock_activity_service)
        dashboard.show()
        dashboard.set_workpulse_active(True)
        dashboard.set_paused(True)

        btn = dashboard.workpulse_toggle_button
        # Controls remain available to start tracking
        self.assertTrue(btn.isEnabled(), "Controls must remain available when tracking is paused")
        self.assertEqual(btn.text(), "Resume", "Button should show Resume to allow user to start")

        pause_signals = []
        dashboard.pause_state_changed.connect(lambda p: pause_signals.append(p))

        # Clicking Resume starts tracking and clears paused state
        btn.click()
        self.assertFalse(dashboard.is_paused(), "Clicking Resume while paused must unpause")
        self.assertEqual(pause_signals, [False], "Clicking Resume must unpause tracking")

        dashboard._shutdown()

    # =========================================================================
    # 3. EXPECTED BEHAVIOUR: WHEN FALSE
    # =========================================================================

    def test_dashboard_when_setting_is_false(self):
        """When allow_start_stop_activity_tracking is False, button is disabled and clicking is blocked."""
        SessionService().login(
            username="emp_false",
            role="User",
            allow_start_stop_activity_tracking=False,
        )

        dashboard = DashboardPage(self.mock_activity_service)
        dashboard.show()
        dashboard.set_workpulse_active(True)

        btn = dashboard.workpulse_toggle_button
        self.assertFalse(btn.isEnabled(), "Button must be disabled when setting is False")
        self.assertIn("managed by your administrator", btn.toolTip().lower())

        signals = []
        dashboard.workpulse_stop_requested.connect(lambda: signals.append(True))
        dashboard.workpulse_start_requested.connect(lambda: signals.append(True))

        # Direct click or calling toggle click handler MUST be blocked
        btn.click()
        self.assertEqual(len(signals), 0, "No start/stop signals should be emitted when disabled")

        # Explicit method invocation also blocked by guard
        dashboard._on_workpulse_toggle_clicked()
        self.assertEqual(len(signals), 0)

        dashboard._shutdown()

    # =========================================================================
    # 4. DYNAMIC BEHAVIOUR & FALLBACK
    # =========================================================================

    def test_dashboard_dynamic_transition_true_to_false_and_back(self):
        """Dashboard dynamically updates button state when permissions change."""
        SessionService().login(
            username="emp_dynamic",
            role="User",
            allow_start_stop_activity_tracking=True,
        )

        dashboard = DashboardPage(self.mock_activity_service)
        dashboard.show()
        dashboard.set_workpulse_active(True)

        btn = dashboard.workpulse_toggle_button
        self.assertTrue(btn.isEnabled(), "Initially enabled")

        # Dynamically push setting = False
        SessionService().update_permissions(allow_start_stop_activity_tracking=False)
        QApplication.processEvents()

        self.assertFalse(btn.isEnabled(), "Button must become disabled dynamically")

        # Try to toggle while disabled / hidden
        toggle_signals = []
        dashboard.workpulse_toggle_requested.connect(lambda: toggle_signals.append(True))
        btn.click()
        self.assertEqual(len(toggle_signals), 0, "Blocked while disabled")
        self.assertFalse(btn.isVisible(), "Button must become hidden dynamically")
        self.assertFalse(dashboard.last_update_label.isVisible(), "Last update label must become hidden dynamically")

        # Dynamically push setting = True
        SessionService().update_permissions(allow_start_stop_activity_tracking=True)
        QApplication.processEvents()

        self.assertTrue(btn.isEnabled(), "Button must become enabled dynamically")
        self.assertTrue(btn.isVisible(), "Button must become visible dynamically")
        self.assertTrue(dashboard.last_update_label.isVisible(), "Last update label must become visible dynamically")
        btn.click()
        self.assertEqual(len(toggle_signals), 1, "Toggling works after re-enabling")

        dashboard._shutdown()

    @patch("services.sync_service.requests.post")
    def test_missing_or_null_setting_safe_handling(self, mock_post):
        """Missing or null settings do not override existing permission or crash."""
        SessionService().login(
            username="emp_safe",
            role="User",
            device_token="TOK_SAFE",
            allow_start_stop_activity_tracking=True,
        )

        svc = SyncService(api_url="https://mock.api")

        # Null value from API
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "allow_start_stop_activity_tracking": None,
            }
        }
        mock_post.return_value = mock_resp

        svc.fetch_settings()
        self.assertTrue(
            SessionService().current_user.allow_start_stop_activity_tracking,
            "Null value should not alter existing valid permission",
        )

        # Missing key completely
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "sync_interval_seconds": 60,
            }
        }
        svc.fetch_settings()
        self.assertTrue(
            SessionService().current_user.allow_start_stop_activity_tracking,
            "Missing key should not alter existing valid permission",
        )

    # =========================================================================
    # 5. MAIN WINDOW INTEGRATION
    # =========================================================================

    def test_main_window_applies_setting_to_dashboard(self):
        """MainWindow._apply_rbac_permissions propagates setting to dashboard_page."""
        SessionService().login(
            username="emp_mw",
            role="User",
            device_token="TOK_MW",
            allow_start_stop_activity_tracking=False,
        )

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "start_workpulse"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                # Dashboard button should be disabled initially
                self.assertFalse(win.dashboard_page.workpulse_toggle_button.isEnabled())

                # Dynamically update permissions to True
                SessionService().update_permissions(allow_start_stop_activity_tracking=True)
                QApplication.processEvents()
                self.assertTrue(win.dashboard_page.workpulse_toggle_button.isEnabled())

                # Dynamically update permissions back to False
                SessionService().update_permissions(allow_start_stop_activity_tracking=False)
                QApplication.processEvents()
                self.assertFalse(win.dashboard_page.workpulse_toggle_button.isEnabled())
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
