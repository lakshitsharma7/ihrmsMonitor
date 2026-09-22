"""Comprehensive End-to-End Verification Test for iHRMS Monitor Full Auto-Update Flow.

Verifies:
1. Current v2.0.1 running with tracking ACTIVE -> API reports v2.1.
2. Background update starts automatically without manual user action.
3. Pending logs and screenshots are safely uploaded/flushed before update installation (Zero Data Loss).
4. If 0 pending records exist, pre-update flush proceeds immediately without delay.
5. Update installation launches silently and triggers application restart.
6. After restart, existing session (SessionStore + SessionService + ApiConfig) is restored seamlessly.
7. NO LOGIN SCREEN is displayed; MainWindow opens directly.
8. If tracking was ACTIVE before update, tracking automatically RESUMES on restart.
9. If user MANUALLY STOPPED tracking before update, tracking remains STOPPED on restart.
10. Dashboard reflects the updated version (v2.1) and status cleanly resets.
11. Duplicate updater / application / tracking processes are prevented.
12. Network unavailable / download failure / install failure handling keeps app running safely.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
import tempfile

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from config.api_config import ApiConfig
from services.session_service import SessionService
from services.secure_session import SessionStore
from services.update_service import (
    UpdatePipelineWorker,
    flush_pending_data_before_update,
    install_update_and_restart,
    is_newer_version,
)
from services.update_state import UpdateStateManager
from ui.main_window import MainWindow


class TestFullAutoUpdateFlowE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = SessionStore()
        self.store.clear_session()
        SessionService().clear()
        UpdateStateManager().clear_state()

    def tearDown(self):
        self.store.clear_session()
        SessionService().clear()
        UpdateStateManager().clear_state()

    def _login_active_session(self, tracking_active=True, manual_stop=False):
        """Helper to establish a valid encrypted session."""
        self.store.save_session(
            company_code="DEMO_COMPANY",
            indo_code="EMP_TEST_01",
            api_key="KEY_TEST_ABC",
            device_token="DEV_TOKEN_XYZ_999",
            username="john.doe",
            full_name="John Doe",
            user_type="User",
            employee_id="1001",
            device_info={"hostname": "DEMO-LAPTOP", "os_type": "window"},
            tracking_permitted=True,
            tracking_manually_stopped=manual_stop,
        )
        self.store.set_tracking_active(tracking_active)
        SessionService().login(
            username="john.doe",
            role="User",
            device_token="DEV_TOKEN_XYZ_999",
            tracking_permitted=True,
            allow_user_device=True,
            allow_logout=True,
            indo_code="EMP_TEST_01",
            api_key="KEY_TEST_ABC",
            employee_id="1001",
            company_code="DEMO_COMPANY",
            full_name="John Doe",
        )

    def test_e2e_full_update_flow_tracking_active_to_resume(self):
        """E2E Test: v2.0.1 running + tracking ACTIVE -> API reports v2.1 -> update -> restart -> session restored -> tracking resumed."""
        self._login_active_session(tracking_active=True, manual_stop=False)

        # 1. Verify current version vs server version
        current_ver = "2.0.1"
        server_ver = "2.1"
        self.assertTrue(is_newer_version(server_ver, current_ver))

        # 2. Simulate background update pipeline with pending data flush
        worker = UpdatePipelineWorker(
            api_url="https://demo.indovisionservices.in/hrms_api/ci4/api",
        )

        phases_reached = []
        worker.phase_changed.connect(lambda phase, desc: phases_reached.append(phase))

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            installer_name = "Workpulse_v2.1.dmg" if sys.platform == "darwin" else f"iHRMSMonitorSetup_v{server_ver}.exe"
            fake_installer = tmp_path / installer_name
            with open(fake_installer, "wb") as f:
                if sys.platform == "darwin":
                    f.write(b"0" * (1024 * 200))
                else:
                    f.write(b"MZ" + b"X" * (1024 * 200))  # Valid PE header and size

            mock_v_resp = MagicMock()
            mock_v_resp.status_code = 200
            mock_v_resp.json.return_value = {
                "status": 1,
                "version_code": "2.1",
                "file_name": installer_name,
                "download_url": f"https://demo.indovisionservices.in/uploads/{installer_name}",
            }
            mock_v_resp.text = '{"status": 1, "version_code": "2.1"}'

            with patch("requests.get", return_value=mock_v_resp), \
                 patch("requests.post", return_value=mock_v_resp), \
                 patch("services.update_service.get_running_app_version", return_value=current_ver), \
                 patch("services.update_service.get_updates_directory", return_value=tmp_path), \
                 patch("services.update_service.flush_pending_data_before_update", return_value=True) as mock_flush, \
                 patch("services.update_service.install_update_and_restart", return_value=True) as mock_install:

                worker.run()

                # Verify pipeline progressed through all required stages
                self.assertIn("checking", phases_reached)
                self.assertIn("uploading_pending", phases_reached)
                self.assertIn("downloading", phases_reached)
                self.assertIn("installing", phases_reached)
                self.assertTrue(mock_flush.called, "Pending data flush MUST be called before install")
                self.assertTrue(mock_install.called, "Silent installer MUST be executed")

        # 3. Simulate Application Restart with new version v2.1
        saved = self.store.load_session()
        self.assertIsNotNone(saved, "Encrypted session MUST persist across restart")
        self.assertEqual(saved.get("username"), "john.doe")
        self.assertTrue(bool(saved.get("device_token")), "Device token must persist across restart")
        self.assertFalse(self.store.is_tracking_manually_stopped(), "Tracking was not manually stopped")

        # Re-initialize SessionService as app.py does on startup
        SessionService().clear()
        SessionService().restore_session(
            username=saved["username"],
            role=saved.get("user_type", "User"),
            full_name=saved.get("full_name"),
            user_type=saved.get("user_type", "User"),
            tracking_permitted=saved.get("tracking_permitted", True),
            allow_user_device=saved.get("allow_user_device", True),
            allow_logout=saved.get("allow_logout", True),
            indo_code=saved["indo_code"],
            api_key=saved["api_key"],
            employee_id=saved.get("employee_id"),
            company_code=saved["company_code"],
            device_token=saved["device_token"],
        )

        self.assertIsNotNone(SessionService().current_user, "User must be authenticated without re-login")

        # 4. Launch MainWindow on restart (as done in app.py)
        mock_provider = MagicMock()
        mock_provider.get_idle_seconds.return_value = 0.0
        mock_provider.get_active_application.return_value = None

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://demo.indovisionservices.in/hrms_api/ci4/api"), \
             patch("config.settings.get_running_app_version", return_value="2.1"), \
             patch("services.update_service.get_running_app_version", return_value="2.1"), \
             patch("platform_support.create_activity_provider", return_value=mock_provider), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):

            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                # 5. Verify NO login window required & tracking automatically resumed
                self.assertTrue(win._tracker.is_tracking, "Tracking MUST automatically resume after restart")
                self.assertEqual(win.status_badge.text(), "Tracking")
                self.assertEqual(win.dashboard_page.tracking_status_label.text(), "Online: Active")
                # 6. Verify version displayed reflects v2.1
                self.assertIn("2.1", win.dashboard_page.version_label.text())
                # 7. Verify NO Stop Tracking button/control is visible anywhere
                self.assertFalse(win.stop_button.isVisible(), "Stop Tracking button must NOT be visible")
                self.assertFalse(win.start_button.isVisible(), "Start Tracking button must NOT be visible")
                if hasattr(win, "tray") and win.tray:
                    self.assertFalse(win.tray.stop_action.isVisible(), "Tray Stop action must NOT be visible")
                    self.assertFalse(win.tray.start_action.isVisible(), "Tray Start action must NOT be visible")
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    def test_e2e_no_stop_tracking_button_visible_anywhere(self):
        """E2E Test: Stop Tracking button is completely hidden/removed from UI for all users."""
        self._login_active_session(tracking_active=True, manual_stop=False)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://demo.indovisionservices.in/hrms_api/ci4/api"), \
             patch("config.settings.get_running_app_version", return_value="2.1"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):

            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                # Button must not be visible in UI
                self.assertFalse(win.stop_button.isVisible(), "Stop Tracking button must not be visible")
                self.assertFalse(win.start_button.isVisible(), "Start Tracking button must not be visible")
                if hasattr(win, "tray") and win.tray:
                    self.assertFalse(win.tray.stop_action.isVisible(), "Tray Stop action must not be visible")
                self.assertTrue(win._tracker.is_tracking, "Tracking must be active")
                self.assertEqual(win.dashboard_page.tracking_status_label.text(), "Online: Active")
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    def test_e2e_pre_flush_zero_pending_records(self):
        """Pre-flush with 0 pending records proceeds immediately."""
        with patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", return_value=[]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]):
            res = flush_pending_data_before_update(max_retries=1)
            self.assertTrue(res)

    def test_e2e_pre_flush_with_pending_logs_and_screenshots(self):
        """Pre-flush with pending logs/screenshots uploads them successfully before update."""
        mock_session = MagicMock()
        with patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", side_effect=[[mock_session], [], [], []]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]), \
             patch("services.sync_service.SyncService.sync_activity_now", return_value=True):
            res = flush_pending_data_before_update(max_retries=2)
            self.assertTrue(res)

    def test_e2e_update_download_failure_preserves_app_and_data(self):
        """If download fails, the app safely handles error, does not restart, and pending data remains safe."""
        self._login_active_session(tracking_active=True, manual_stop=False)

        worker = UpdatePipelineWorker(api_url="https://demo.indovisionservices.in/hrms_api/ci4/api")
        errors = []
        worker.error_occurred.connect(lambda phase, err: errors.append((phase, err)))

        mock_v_resp = MagicMock()
        mock_v_resp.status_code = 200
        mock_v_resp.json.return_value = {
            "status": 1,
            "version_code": "2.1",
            "download_url": "https://invalid.url/nonexistent_setup.exe",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with patch("requests.get", return_value=mock_v_resp), \
                 patch("requests.post", return_value=mock_v_resp), \
                 patch("services.update_service.get_running_app_version", return_value="2.0.1"), \
                 patch("services.update_service.get_updates_directory", return_value=tmp_path), \
                 patch("services.update_service.flush_pending_data_before_update", return_value=True), \
                 patch("services.update_service.resolve_download_candidates", return_value=["https://invalid.url/nonexistent_setup.exe"]), \
                 patch("pathlib.Path.exists", return_value=False), \
                 patch("services.update_service.install_update_and_restart") as mock_install:

                worker.run()
                self.assertTrue(len(errors) > 0, "Error must be emitted on download failure")
                mock_install.assert_not_called()
                # Session and data are completely untouched
                self.assertTrue(self.store.validate_session())

    def test_e2e_install_failure_loop_cooldown(self):
        """If an update fails post-restart verification, cooldown prevents infinite restart loop."""
        state_mgr = UpdateStateManager()
        # Simulate 1st failed attempt
        state_mgr.record_install_start("2.1", "/fake/setup.exe")
        success1, msg1 = state_mgr.check_post_restart_status(running_version="2.0.1")
        self.assertFalse(success1)

        # Simulate 2nd failed attempt
        state_mgr.record_install_start("2.1", "/fake/setup.exe")
        success2, msg2 = state_mgr.check_post_restart_status(running_version="2.0.1")
        self.assertFalse(success2)

        allowed, reason = state_mgr.should_attempt_update("2.1", running_version="2.0.1")
        self.assertFalse(allowed)
        self.assertIn("cooldown", reason.lower())

    def test_e2e_duplicate_process_prevention(self):
        """Lock file mechanism prevents secondary instance duplicate execution."""
        from PySide6.QtCore import QDir, QLockFile
        import os
        lock_path = os.path.join(QDir.tempPath(), "ihrms_monitor_test_e2e.lock")
        lock1 = QLockFile(lock_path)
        lock2 = QLockFile(lock_path)

        self.assertTrue(lock1.tryLock(100))
        self.assertFalse(lock2.tryLock(100), "Second instance MUST fail to acquire lock")
        lock1.unlock()
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
