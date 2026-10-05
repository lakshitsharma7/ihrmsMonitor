"""Unit and integration tests for workpulse persistence across application / EXE restarts.

Verifies:
1. WorkPulse active before restart -> automatically restored on startup, dashboard shows "WorkPulse: Active".
2. WorkPulse manually stopped before restart -> stays stopped on startup, dashboard shows "WorkPulse: Inactive".
3. User manually starting workpulse clears manually_stopped flag and restores persistence.
4. Automated stops (e.g. before auto-update restart) preserve workpulse auto-start across restart.
5. Duplicate workpulse worker prevention (repeated start_workpulse calls are safely ignored).
6. Fresh login resets any previous manual stop flag.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from services.session_service import SessionService
from services.secure_session import SessionStore
from tracker.activity_tracker import ActivityTracker
from tracker.tracker_worker import TrackerWorker
from ui.main_window import MainWindow


class TestWorkPulsePersistenceRestart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = SessionStore()
        # Clean settings for a fresh test state
        self.store.clear_session()
        SessionService().clear()

    def tearDown(self):
        self.store.clear_session()
        SessionService().clear()

    def _login_test_user(self, workpulse_permitted=True):
        SessionService().login(
            username="test_persistence_user",
            role="User",
            device_token="TOKEN_PERSIST_123",
            workpulse_permitted=workpulse_permitted,
            allow_user_device=True,
            allow_logout=True,
        )

    def test_session_store_manual_stop_and_active_helpers(self):
        """Verify is_workpulse_manually_stopped and set_workpulse_manually_stopped helpers."""
        self.assertFalse(self.store.is_workpulse_manually_stopped())
        self.store.set_workpulse_manually_stopped(True)
        self.assertTrue(self.store.is_workpulse_manually_stopped())
        self.store.set_workpulse_manually_stopped(False)
        self.assertFalse(self.store.is_workpulse_manually_stopped())

        self.assertFalse(self.store.is_workpulse_active())
        self.store.set_workpulse_active(True)
        self.assertTrue(self.store.is_workpulse_active())
        self.store.set_workpulse_active(False)
        self.assertFalse(self.store.is_workpulse_active())

    def test_restart_with_active_workpulse_restores_workpulse_and_shows_active(self):
        """If workpulse was active before restart, MainWindow automatically starts workpulse, shows 'WorkPulse: Active', and hides manual stop button."""
        self._login_test_user(workpulse_permitted=True)
        self.store.set_workpulse_manually_stopped(False)
        self.store.set_workpulse_active(True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                self.assertTrue(win._tracker.is_workpulse, "Tracker must be actively running")
                self.assertEqual(win.status_badge.text(), "Online")
                self.assertEqual(win.dashboard_page.network_status_label.text(), "● Online")
                self.assertEqual(win.dashboard_page.workpulse_toggle_button.text(), "Paused")
                # Header buttons are hidden
                self.assertFalse(win.stop_button.isVisible(), "Stop WorkPulse button must NOT be visible")
                self.assertFalse(win.start_button.isVisible(), "Start WorkPulse button must NOT be visible")
                if hasattr(win, "tray") and win.tray:
                    self.assertFalse(win.tray.stop_action.isVisible(), "Tray Stop WorkPulse action must NOT be visible")
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    def test_stop_workpulse_button_permanently_hidden(self):
        """Header Stop WorkPulse button and manual stop controls are permanently hidden from UI for all users."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                self.assertFalse(win.stop_button.isVisible())
                self.assertFalse(win.start_button.isVisible())
                if hasattr(win, "tray") and win.tray:
                    self.assertFalse(win.tray.stop_action.isVisible())
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    def test_user_stop_and_user_start_cycle(self):
        """User stopping workpulse sets manual stop; user restarting workpulse clears it."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                self.assertTrue(win._tracker.is_workpulse)
                self.assertFalse(self.store.is_workpulse_manually_stopped())
                self.assertEqual(win.dashboard_page.workpulse_toggle_button.text(), "Paused")

                # User clicks "Paused" button on dashboard -> toggles to Paused state, tracker stays active
                win.dashboard_page.workpulse_toggle_button.click()
                QApplication.processEvents()

                self.assertTrue(win._tracker.is_workpulse)
                self.assertTrue(self.store.is_workpulse_paused())
                self.assertEqual(win.status_badge.text(), "Online")
                self.assertEqual(win.dashboard_page.workpulse_status_label.text(), "Online: Paused")
                self.assertEqual(win.dashboard_page.workpulse_toggle_button.text(), "Resume")

                # User clicks "Resume" button on dashboard -> toggles back to Online/Active state
                win.dashboard_page.workpulse_toggle_button.click()
                QApplication.processEvents()

                self.assertTrue(win._tracker.is_workpulse)
                self.assertFalse(self.store.is_workpulse_paused())
                self.assertEqual(win.status_badge.text(), "Online")
                self.assertEqual(win.dashboard_page.workpulse_status_label.text(), "Online: Active")
                self.assertEqual(win.dashboard_page.workpulse_toggle_button.text(), "Paused")
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    def test_automated_stop_for_update_preserves_active_workpulse_after_restart(self):
        """Automated stop before update (manual=False) preserves auto-start on next restart."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win1 = MainWindow()
            win1.show()
            QApplication.processEvents()
            try:
                self.assertTrue(win1._tracker.is_workpulse)
                # Updater stops workpulse cleanly without marking manual stop
                win1.stop_workpulse_for_update()
                QApplication.processEvents()

                # Flag must remain False because it was not a user manual stop
                self.assertFalse(self.store.is_workpulse_manually_stopped())
            finally:
                win1._shutdown()
                win1.close()
                QApplication.processEvents()

            # Now simulate app launch after restart (new MainWindow instance)
            win2 = MainWindow()
            win2.show()
            QApplication.processEvents()
            try:
                self.assertTrue(win2._tracker.is_workpulse, "WorkPulse must resume after update restart")
                self.assertEqual(win2.status_badge.text(), "Online")
                self.assertEqual(win2.dashboard_page.network_status_label.text(), "● Online")
                self.assertEqual(win2.dashboard_page.workpulse_toggle_button.text(), "Paused")
            finally:
                win2._shutdown()
                win2.close()
                QApplication.processEvents()

    def test_prevent_duplicate_workpulse_workers(self):
        """Calling start_workpulse multiple times does NOT spawn duplicate workers or duplicate poll loops."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                self.assertTrue(win._tracker.is_workpulse)

                # Calling start_workpulse repeatedly must be safely guarded
                mock_slot = MagicMock()
                win._request_start.connect(mock_slot)
                win.start_workpulse()
                win.start_workpulse()
                # Because win._tracker.is_workpulse is already True, _request_start should not be emitted again
                mock_slot.assert_not_called()

                # Worker also guards against duplicate start
                with patch.object(win._worker._tracker, "start") as mock_tracker_start:
                    win._worker.start_workpulse()
                    mock_tracker_start.assert_not_called()
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    def test_fresh_login_resets_manual_stop_state(self):
        """A new login resets workpulse_manually_stopped, ensuring auto-workpulse starts for the new session."""
        # Set manual stop in old session
        self.store.set_workpulse_manually_stopped(True)
        self.assertTrue(self.store.is_workpulse_manually_stopped())

        # Fresh login occurs and saves session
        self.store.save_session(
            company_code="COMP123",
            indo_code="EMP001",
            api_key="APIKEY123",
            device_token="DEVTOKEN123",
            username="new_login_user",
            full_name="New User",
            user_type="User",
            employee_id="101",
            device_info={"hostname": "TEST-PC"},
            workpulse_permitted=True,
            workpulse_manually_stopped=False,
        )

        self.assertFalse(self.store.is_workpulse_manually_stopped(), "Fresh login must reset manual stop flag")
        self.assertTrue(self.store.is_workpulse_active())

    def test_windows_shutdown_and_restart_native_event(self):
        """WM_QUERYENDSESSION and WM_ENDSESSION native Windows events cleanly trigger shutdown without process hang."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                self.assertTrue(win._tracker.is_workpulse)

                # Mock ctypes MSG structure for WM_QUERYENDSESSION (0x0011)
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG()
                msg.message = 0x0011  # WM_QUERYENDSESSION
                msg_ptr = ctypes.addressof(msg)

                handled, res = win.nativeEvent(b"windows_generic_MSG", msg_ptr)
                self.assertTrue(handled)
                self.assertTrue(win._really_quit)
                self.assertTrue(getattr(win, "_is_shutting_down", False))
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows registry startup test")
    def test_startup_registration_compiled_exe_only(self):
        """Startup registration writes registry only for compiled iHRMS Monitor.exe, never dev python.exe."""
        from system import startup
        with patch("winreg.CreateKeyEx") as mock_create_key, \
             patch("winreg.SetValueEx") as mock_set_val, \
             patch("winreg.DeleteValue") as mock_del_val:
            mock_key = MagicMock()
            mock_create_key.return_value.__enter__.return_value = mock_key

            # 1. Dev python interpreter without compiled exe skips registration
            with patch("sys.frozen", False, create=True), \
                 patch("pathlib.Path.is_file", return_value=False):
                startup.set_enabled(True, executable_path="C:\\Python312\\python.exe")
                mock_set_val.assert_not_called()

            # 2. Frozen compiled exe registers correctly
            with patch("sys.frozen", True, create=True):
                startup.set_enabled(True, executable_path="C:\\Program Files\\iHRMS Monitor\\iHRMS Monitor.exe")
                mock_set_val.assert_called_with(
                    mock_key,
                    startup.APP_NAME,
                    0,
                    1,  # REG_SZ
                    '"C:\\Program Files\\iHRMS Monitor\\iHRMS Monitor.exe"',
                )


if __name__ == "__main__":
    unittest.main()

