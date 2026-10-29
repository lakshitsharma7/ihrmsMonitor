"""Tests for application instance management, supervisor lifecycle, and restart resilience."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from system.supervisor import (
    ProcessSupervisor,
    MAX_CRASH_RESTARTS,
    CRASH_WINDOW_SECONDS,
    acquire_supervisor_lock,
    release_supervisor_lock,
)
from services.secure_session import SessionStore


class TestInstanceManagementAndLifecycle(unittest.TestCase):
    def setUp(self):
        SessionStore._fallback_cache.clear()

    def tearDown(self):
        SessionStore._fallback_cache.clear()

    def test_01_early_supervisor_dispatch_does_not_initialize_qapplication(self):
        """Verifies that passing --supervisor dispatches directly to run_supervisor without GUI initialization."""
        import app

        with patch("sys.argv", ["app.py", "--supervisor", "--monitor-pid", "12345"]), \
             patch("app.QApplication") as mock_qapp, \
             patch("system.supervisor.run_supervisor", return_value=0) as mock_sup:
            exit_code = app.main()
            self.assertEqual(exit_code, 0)
            mock_sup.assert_called_once()
            # QApplication must NOT have been instantiated
            mock_qapp.assert_not_called()

    def test_02_named_mutex_blocks_duplicate_instance_without_qapplication(self):
        """Verifies that when Windows Named Mutex is held, second launch exits 0 without creating QApplication."""
        import app

        with patch("sys.argv", ["app.py"]), \
             patch("app.QApplication") as mock_qapp, \
             patch("app._acquire_app_mutex", return_value=False), \
             patch("app._activate_existing_window") as mock_activate:
            exit_code = app.main()
            self.assertEqual(exit_code, 0)
            mock_activate.assert_called_once()
            # QApplication must NOT have been created
            mock_qapp.assert_not_called()

    def test_03_cleanup_stale_lock_preserves_lock_when_active_process_running(self):
        """_cleanup_stale_lock must NOT unlink ihrms_monitor.lock if an active desktop PID is running."""
        supervisor = ProcessSupervisor()

        with patch("system.supervisor._find_running_desktop_pid", return_value=99999), \
             patch("os.path.isfile", return_value=True), \
             patch("os.remove") as mock_remove:
            supervisor._cleanup_stale_lock()
            mock_remove.assert_not_called()

    def test_04_cleanup_stale_lock_unlinks_when_no_active_process_running(self):
        """_cleanup_stale_lock unlinks ihrms_monitor.lock when no active desktop PID exists."""
        supervisor = ProcessSupervisor()

        with patch("system.supervisor._find_running_desktop_pid", return_value=None), \
             patch("os.path.isfile", return_value=True), \
             patch("os.remove") as mock_remove:
            supervisor._cleanup_stale_lock()
            mock_remove.assert_called_once()

    def test_05_supervisor_attaches_to_existing_pid_instead_of_spawning_duplicate(self):
        """In Phase 2, if an active desktop instance is already alive, supervisor attaches rather than spawning."""
        supervisor = ProcessSupervisor()
        SessionStore._fallback_cache["session/clean_shutdown"] = True

        existing_pid = 44444
        with patch("system.supervisor.acquire_supervisor_lock", return_value=True), \
             patch("system.supervisor.release_supervisor_lock"), \
             patch("system.supervisor._find_running_desktop_pid", return_value=existing_pid), \
             patch.object(supervisor, "_wait_for_pid", return_value=0) as mock_wait_pid, \
             patch("system.supervisor.spawn_detached_process") as mock_spawn:
            exit_code = supervisor.run()
            self.assertEqual(exit_code, 0)
            mock_wait_pid.assert_called_with(existing_pid)
            mock_spawn.assert_not_called()

    def test_06_supervisor_exit_code_zero_with_other_process_running_continues_monitoring(self):
        """When a child exits with code 0 (duplicate launch detection), supervisor attaches to the primary instance."""
        supervisor = ProcessSupervisor()
        SessionStore._fallback_cache["session/clean_shutdown"] = False

        # Simulate first child exiting with 0 (duplicate launch detected existing instance)
        # and on the next iteration primary instance 55555 exits cleanly
        mock_child = MagicMock()
        mock_child.pid = 11111
        mock_child.wait.return_value = 0

        call_count = 0
        def _mock_find_desktop(exclude_pid=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Primary instance 55555 is alive
                return 55555
            # Now primary exits
            SessionStore._fallback_cache["session/clean_shutdown"] = True
            return None

        with patch("system.supervisor.acquire_supervisor_lock", return_value=True), \
             patch("system.supervisor.release_supervisor_lock"), \
             patch("system.supervisor._find_running_desktop_pid", side_effect=_mock_find_desktop), \
             patch.object(supervisor, "_wait_for_pid", return_value=0), \
             patch("subprocess.Popen", return_value=mock_child):
            exit_code = supervisor.run()
            self.assertEqual(exit_code, 0)
            # Must NOT have treated code 0 as a crash
            self.assertEqual(len(supervisor._crash_timestamps), 0)

    def test_07_unexpected_termination_task_manager_kill_triggers_recovery(self):
        """Exit code 1 (Task Manager termination) triggers unexpected crash recovery and spawns replacement."""
        supervisor = ProcessSupervisor(target_args=["--startup"], monitor_pid=66666)
        SessionStore._fallback_cache["session/clean_shutdown"] = False

        recovered_child = MagicMock()
        recovered_child.pid = 77777
        def _on_recovered_wait():
            SessionStore._fallback_cache["session/clean_shutdown"] = True
            return 0
        recovered_child.wait.side_effect = _on_recovered_wait

        with patch("system.supervisor.acquire_supervisor_lock", return_value=True), \
             patch("system.supervisor.release_supervisor_lock"), \
             patch.object(supervisor, "_wait_for_pid", return_value=1) as mock_wait_pid, \
             patch("system.supervisor._find_running_desktop_pid", return_value=None), \
             patch("subprocess.Popen", return_value=recovered_child) as mock_popen, \
             patch("time.sleep"):
            exit_code = supervisor.run()
            self.assertEqual(exit_code, 0)
            mock_wait_pid.assert_called_once_with(66666)
            mock_popen.assert_called_once()
            self.assertEqual(len(supervisor._crash_timestamps), 1)

    def test_08_scheduled_task_does_not_have_five_minute_repetition(self):
        """Verify scheduled task registration only uses -AtLogOn trigger without repetition interval."""
        from pathlib import Path
        import system.startup as startup

        fake_exe = Path("C:/fake/iHRMS-Desktop.exe")

        with patch("sys.platform", "win32"), \
             patch("system.startup._is_windows_scheduled_task_registered", return_value=False), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            startup._register_windows_scheduled_task(fake_exe)
            mock_run.assert_called_once()
            cmd_args = mock_run.call_args[0][0]
            ps_script = cmd_args[-1]
            self.assertIn("-AtLogOn", ps_script)
            self.assertNotIn("-RepetitionInterval", ps_script)
            self.assertNotIn("New-TimeSpan -Minutes 5", ps_script)


if __name__ == "__main__":
    unittest.main()
