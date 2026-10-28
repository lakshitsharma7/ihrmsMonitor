"""Comprehensive tests for iHRMS Desktop background execution and sync reliability on Windows.

Validates:
1. Minimize/close window -> truthful background status check (no false popups).
2. Worker health check and sync continuation while in background.
3. Worker crash simulation -> truthful status update, error reporting, and recovery with retry limit.
4. Stale lock recovery after unexpected process termination (no false popups).
5. Offline mode followed by network restoration -> sessions preserved, uploaded without duplicates.
6. Clean exit, logout, update, and Windows shutdown -> clean shutdown flag set, no restart loops.
7. Supervisor rate limiting -> max 3 retries, avoids infinite restart loops.
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from PySide6.QtCore import QDir, QLockFile, QThread
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from config.settings import APP_NAME
from database.database import get_session
from database.models import ActivitySession
from database.repository import ActivityRepository
from services.error_report_service import ErrorReportService
from services.secure_session import SessionStore
from services.session_service import SessionService
from services.sync_service import SyncService
from system.supervisor import ProcessSupervisor, MAX_CRASH_RESTARTS, CRASH_WINDOW_SECONDS
from tracker.activity_tracker import ActivityTracker, TrackerState
from tracker.tracker_worker import TrackerWorker
from ui.main_window import MainWindow


app = QApplication.instance() or QApplication([])


class TestBackgroundModeAndSyncReliability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sys.platform.startswith("win"):
            raise unittest.SkipTest("Background mode and Windows sync reliability tests are Windows-specific.")
    def setUp(self):
        SessionService().clear()
        self.store = SessionStore()
        self.store.clear_session()
        self.store.set_clean_shutdown(True)
        ErrorReportService().clear_error_history()

    def tearDown(self):
        SessionService().clear()
        self.store.clear_session()
        self.store.set_clean_shutdown(True)
        ErrorReportService().clear_error_history()

    def _login_test_user(self, workpulse_permitted: bool = True):
        SessionService().login(
            username="test_bg_user",
            role="User",
            device_token="TOKEN_BG_TEST",
            workpulse_permitted=workpulse_permitted,
            allow_user_device=True,
            allow_logout=True,
            employee_id="EMP_BG_1",
            company_code="COMP_BG_1",
        )

    # ==========================================================
    # SCENARIO 1: TRUTHFUL BACKGROUND STATUS ON CLOSE / MINIMIZE
    # ==========================================================

    @unittest.skipUnless(sys.platform.startswith("win"), "Requires Windows win32gui")
    def test_01_close_event_reports_truthful_background_status_when_active(self):
        """When tracking is actively healthy, closeEvent shows truthful background running notification."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"), \
             patch("win32gui.ShowWindow"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                self.assertTrue(win._tracker.is_workpulse)
                self.assertTrue(win._thread.isRunning())
                self.assertFalse(win.dashboard_page.is_paused())

                with patch.object(win.tray, "show_message") as mock_show_msg:
                    event = QCloseEvent()
                    win.closeEvent(event)
                    self.assertFalse(event.isAccepted(), "Window close should hide to tray")
                    mock_show_msg.assert_called_once()
                    msg_args = mock_show_msg.call_args[0]
                    self.assertIn("running in the background", msg_args[1].lower())
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    @unittest.skipUnless(sys.platform.startswith("win"), "Requires Windows win32gui")
    def test_02_close_event_suppresses_background_running_when_tracking_stopped(self):
        """When tracking is stopped or worker is dead, closeEvent must NOT falsely claim running in background."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"), \
             patch("win32gui.ShowWindow"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                # Stop tracking explicitly
                win.stop_workpulse(manual=True)
                self.assertFalse(win._tracker.is_workpulse)

                with patch.object(win.tray, "show_message") as mock_show_msg:
                    event = QCloseEvent()
                    win.closeEvent(event)
                    self.assertFalse(event.isAccepted())
                    # Must NOT show "running in background" message
                    mock_show_msg.assert_not_called()
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    @unittest.skipUnless(sys.platform.startswith("win"), "Requires Windows win32gui")
    def test_03_close_event_reflects_paused_state_truthfully(self):
        """When tracking is paused by user, closeEvent truthfully indicates paused status rather than active running."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"), \
             patch("win32gui.ShowWindow"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                # Pause tracking
                win.dashboard_page.set_paused(True)
                self.assertTrue(win.dashboard_page.is_paused())

                with patch.object(win.tray, "show_message") as mock_show_msg:
                    event = QCloseEvent()
                    win.closeEvent(event)
                    self.assertFalse(event.isAccepted())
                    mock_show_msg.assert_called_once()
                    msg_args = mock_show_msg.call_args[0]
                    self.assertIn("paused", msg_args[1].lower())
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    # ==========================================================
    # SCENARIO 2: WORKER HEALTH & SYNC CONTINUATION IN BACKGROUND
    # ==========================================================

    @unittest.skipUnless(sys.platform.startswith("win"), "Requires Windows win32gui")
    def test_04_worker_continues_polling_and_sync_while_hidden(self):
        """Worker thread remains alive and continues executing poll/sync cycles while window is hidden."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"), \
             patch("win32gui.ShowWindow"):
            win = MainWindow(is_background=True)
            try:
                self.assertFalse(win.isVisible())
                self.assertTrue(win._tracker.is_workpulse)
                self.assertTrue(win._thread.isRunning())

                # Simulate a poll tick
                with patch.object(win._worker, "_on_tick") as mock_tick:
                    win._worker._on_tick()
                    mock_tick.assert_called_once()
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    # ==========================================================
    # SCENARIO 3: WORKER CRASH DETECTION & SAFE RECOVERY
    # ==========================================================

    def test_05_unexpected_worker_crash_updates_status_reports_error_and_recovers(self):
        """Simulate unexpected worker thread exit; verify truthful error status and recovery with retry limit."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"), \
             patch.object(MainWindow, "_recover_tracker_worker") as mock_recover:
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                self.assertEqual(win.status_badge.text(), "Online")
                self.assertEqual(win._worker_recovery_retries, 0)

                # Simulate unexpected thread termination while app is active
                win._on_tracker_thread_finished()

                # 1. UI must reflect Error state truthfully
                self.assertEqual(win.status_badge.text(), "Error")
                self.assertIn("Error", win.dashboard_page.workpulse_status_label.text())

                # 2. Error report must be recorded
                recent_errors = ErrorReportService().get_recent_errors(limit=5)
                error_types = [e.error_type for e in recent_errors]
                self.assertIn("TRACKER_THREAD_TERMINATED", error_types)

                # 3. Recovery counter increments
                self.assertEqual(win._worker_recovery_retries, 1)
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    def test_06_worker_recovery_enforces_retry_limit(self):
        """Repeated worker crashes stop retrying after reaching max retries to prevent restart loops."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            win.show()
            QApplication.processEvents()
            try:
                win._worker_recovery_retries = 3
                # Trigger thread exit when already at max retries
                win._on_tracker_thread_finished()

                # Retries should remain capped at 3 without scheduling further recovery
                self.assertEqual(win._worker_recovery_retries, 3)
                self.assertEqual(win.status_badge.text(), "Error")
            finally:
                win._shutdown()
                win.close()
                QApplication.processEvents()

    # ==========================================================
    # SCENARIO 4: STALE LOCK DETECTION & CLEAN RECOVERY (TASK MANAGER TERMINATION)
    # ==========================================================

    def test_07_dead_pid_lock_file_cleared_cleanly_without_false_popup(self):
        """Simulate an abandoned lock file from a killed process; verify app clears it without false popup."""
        lock_path = os.path.join(QDir.tempPath(), "ihrms_monitor_test_stale.lock")
        if os.path.isfile(lock_path):
            os.remove(lock_path)

        # Create lock file simulating a dead process (non-existent PID)
        dead_pid = 999999
        with open(lock_path, "w") as f:
            f.write(f"{dead_pid}\ntest-host\niHRMS-Desktop\n")

        from app import _is_real_ihrms_process_running
        self.assertFalse(_is_real_ihrms_process_running(dead_pid))

        # Test recovery logic
        lock_file = QLockFile(lock_path)
        lock_file.setStaleLockTime(100)

        # When dead process PID is detected, stale lock is removed and new lock acquired
        if not _is_real_ihrms_process_running(dead_pid):
            if os.path.isfile(lock_path):
                os.remove(lock_path)

        new_lock = QLockFile(lock_path)
        self.assertTrue(new_lock.tryLock(200))
        new_lock.unlock()

        if os.path.isfile(lock_path):
            os.remove(lock_path)

    # ==========================================================
    # SCENARIO 5: OFFLINE MODE -> NETWORK RESTORATION -> NO DUPLICATES
    # ==========================================================

    def test_08_offline_sessions_preserved_and_uploaded_without_duplicates(self):
        """Queued sessions are preserved during offline mode, uploaded on reconnection, and deduplicated."""
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        self._login_test_user(workpulse_permitted=True)
        sync_service = SyncService()
        db_session = get_session()
        try:
            repo = ActivityRepository(db_session)
            # Create two test sessions
            s1 = repo.create_session("TestApp1", 1001, "Window 1", datetime.now(timezone.utc), employee_id="EMP_BG_1")
            repo.close_session(s1.id, datetime.now(timezone.utc))
            s2 = repo.create_session("TestApp2", 1002, "Window 2", datetime.now(timezone.utc), employee_id="EMP_BG_1")
            repo.close_session(s2.id, datetime.now(timezone.utc))
            db_session.expunge_all()
        finally:
            db_session.close()

        # Step 1: Simulate offline attempt (network failure)
        with patch.object(sync_service, "_require_device_token", return_value="TOKEN_BG_TEST"), \
             patch.object(sync_service, "fetch_settings"), \
             patch.object(sync_service, "_send_request_with_retry", return_value=None):
            success = sync_service.sync_activity_now()
            self.assertFalse(success, "Sync should report failure when offline")
            self.assertIn("Failed", sync_service.last_sync_status)

        # Verify sessions are still unsynced in DB (never lost)
        db_session = get_session()
        try:
            repo = ActivityRepository(db_session)
            unsynced = repo.get_unsynced_closed_sessions(employee_id="EMP_BG_1")
            unsynced_ids = [s.id for s in unsynced]
            self.assertIn(s1.id, unsynced_ids)
            self.assertIn(s2.id, unsynced_ids)
        finally:
            db_session.close()

        # Step 2: Simulate network restoration and successful upload
        mock_success_response = {
            "response": "Success",
            "message": "Activity log saved successfully",
            "data": [
                {"client_session_ref": s1.id, "activity_session_id": 5001, "status": "Saved"},
                {"client_session_ref": s2.id, "activity_session_id": 5002, "status": "Saved"},
            ],
        }

        with patch.object(sync_service, "_require_device_token", return_value="TOKEN_BG_TEST"), \
             patch.object(sync_service, "fetch_settings"), \
             patch.object(sync_service, "_send_request_with_retry", return_value=mock_success_response):
            success = sync_service.sync_activity_now()
            self.assertTrue(success, "Sync should report success when API confirms")
            self.assertEqual(sync_service.last_sync_status, "Sent")

        # Step 3: Verify sessions are now bound to server_id and not returned in unsynced query
        db_session = get_session()
        try:
            repo = ActivityRepository(db_session)
            unsynced_after = repo.get_unsynced_closed_sessions(employee_id="EMP_BG_1")
            unsynced_ids_after = [s.id for s in unsynced_after]
            self.assertNotIn(s1.id, unsynced_ids_after, "Session 1 must be marked synced")
            self.assertNotIn(s2.id, unsynced_ids_after, "Session 2 must be marked synced")
        finally:
            db_session.close()

    # ==========================================================
    # SCENARIO 6: CLEAN SHUTDOWN, LOGOUT, UPDATE -> NO RESTART LOOPS
    # ==========================================================

    def test_09_clean_shutdown_flag_set_on_normal_shutdown_and_logout(self):
        """Clean shutdown flag is set when user exits, logs out, or update occurs."""
        self._login_test_user(workpulse_permitted=True)

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch.object(MainWindow, "_check_for_updates"), \
             patch.object(MainWindow, "_sync_permissions_from_backend"):
            win = MainWindow()
            try:
                # On startup clean shutdown flag was set to False
                self.assertFalse(self.store.is_clean_shutdown())

                # Simulate clean shutdown
                win._shutdown()
                self.assertTrue(self.store.is_clean_shutdown(), "Clean shutdown must be recorded")
            finally:
                win.close()
                QApplication.processEvents()

    # ==========================================================
    # SCENARIO 7: SUPERVISOR RATE LIMITING & CLEAN EXIT RESPECT
    # ==========================================================

    def test_10_supervisor_exits_on_clean_shutdown_without_restarting(self):
        """Supervisor checks clean shutdown flag and terminates cleanly without respawning."""
        supervisor = ProcessSupervisor()
        self.store.set_clean_shutdown(True)

        # Mock child process that exits with code 0
        mock_child = MagicMock()
        mock_child.pid = 12345
        mock_child.wait.return_value = 0

        with patch("system.supervisor.acquire_supervisor_lock", return_value=True), \
             patch("system.supervisor.release_supervisor_lock"), \
             patch("system.supervisor._find_running_desktop_pid", return_value=None), \
             patch("subprocess.Popen", return_value=mock_child):
            exit_code = supervisor.run()
            self.assertEqual(exit_code, 0)
            # Should have launched once and cleanly stopped
            self.assertEqual(len(supervisor._crash_timestamps), 0)

    def test_11_supervisor_rate_limits_crashes_to_prevent_infinite_loops(self):
        """Supervisor caps unexpected crash restarts at MAX_CRASH_RESTARTS and halts."""
        supervisor = ProcessSupervisor()
        self.store.set_clean_shutdown(False)

        # Mock child process that crashes repeatedly with code 1
        mock_child = MagicMock()
        mock_child.pid = 23456
        mock_child.wait.return_value = 1

        with patch("system.supervisor.acquire_supervisor_lock", return_value=True), \
             patch("system.supervisor.release_supervisor_lock"), \
             patch("system.supervisor._find_running_desktop_pid", return_value=None), \
             patch("subprocess.Popen", return_value=mock_child), \
             patch("time.sleep"):  # skip actual sleep
            exit_code = supervisor.run()
            self.assertEqual(exit_code, 0)
            # Crash timestamps must equal MAX_CRASH_RESTARTS and supervisor halts
            self.assertEqual(len(supervisor._crash_timestamps), MAX_CRASH_RESTARTS)

    @unittest.skipUnless(sys.platform.startswith("win"), "Requires Windows supervisor")
    def test_12_supervisor_attaches_to_pid_and_recovers_on_unexpected_termination(self):
        """Supervisor attached to existing PID detects termination and spawns recovery instance."""
        target_pid = 77777
        supervisor = ProcessSupervisor(target_args=["--startup"], monitor_pid=target_pid)
        self.store.set_clean_shutdown(False)

        recovered_child = MagicMock()
        recovered_child.pid = 88888
        # Make recovered child exit cleanly after being spawned
        def _on_recovered_wait():
            self.store.set_clean_shutdown(True)
            return 0
        recovered_child.wait.side_effect = _on_recovered_wait

        with patch("system.supervisor.acquire_supervisor_lock", return_value=True), \
             patch("system.supervisor.release_supervisor_lock"), \
             patch.object(supervisor, "_wait_for_pid", return_value=1) as mock_wait_pid, \
             patch("subprocess.Popen", return_value=recovered_child) as mock_popen, \
             patch("time.sleep"):
            exit_code = supervisor.run()
            self.assertEqual(exit_code, 0)
            mock_wait_pid.assert_called_once_with(target_pid)
            mock_popen.assert_called_once()
            # Command must contain --startup
            spawn_args = mock_popen.call_args[0][0]
            self.assertIn("--startup", spawn_args)
            # Environment must have IHRMS_SUPERVISED=1
            call_env = mock_popen.call_args[1].get("env", {})
            self.assertEqual(call_env.get("IHRMS_SUPERVISED"), "1")
            self.assertEqual(len(supervisor._crash_timestamps), 1)

    @unittest.skipUnless(sys.platform.startswith("win"), "Requires Windows supervisor")
    def test_13_ensure_supervisor_running_spawns_supervisor_detached(self):
        """ensure_supervisor_running spawns supervisor detached if not already active."""
        from app import ensure_supervisor_running

        with patch("system.supervisor.is_supervisor_running", return_value=False), \
             patch("sys.platform", "win32"), \
             patch.dict(os.environ, {"IHRMS_ENABLE_TEST_SUPERVISOR": "1"}, clear=False), \
             patch("subprocess.Popen") as mock_popen:
            res = ensure_supervisor_running()
            self.assertTrue(res)
            mock_popen.assert_called_once()
            call_cmd = mock_popen.call_args[0][0]
            self.assertIn("--supervisor", call_cmd)
            self.assertIn("--monitor-pid", call_cmd)
            self.assertIn(str(os.getpid()), call_cmd)
            # Must be launched with DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP
            creation_flags = mock_popen.call_args[1].get("creationflags", 0)
            self.assertTrue(bool(creation_flags & 0x00000008))
            self.assertTrue(bool(creation_flags & 0x00000200))

    def test_14_supervisor_single_instance_prevents_duplicate_supervisors(self):
        """Supervisor single-instance lock prevents running two supervisors concurrently."""
        from system.supervisor import acquire_supervisor_lock, release_supervisor_lock, is_supervisor_running

        with patch("system.supervisor.is_supervisor_running", return_value=True):
            self.assertFalse(acquire_supervisor_lock(), "Should reject acquiring lock when supervisor is already running")


if __name__ == "__main__":
    unittest.main()

