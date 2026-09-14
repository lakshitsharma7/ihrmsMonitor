"""Unit tests for UpdateStateManager, loop prevention, and hidden updater generation."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.update_state import UpdateStateManager, _is_version_ge
from services.update_service import (
    is_inno_setup_installer,
    install_update_and_restart,
    verify_post_restart_update,
)


class TestUpdateStateAndExecution(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.tmp_dir.name) / "update_state.json"
        # Reset singleton state
        UpdateStateManager._instance = None
        self.mgr = UpdateStateManager(state_file=self.state_file)

    def tearDown(self):
        UpdateStateManager._instance = None
        self.tmp_dir.cleanup()

    def test_version_ge_utility(self):
        self.assertTrue(_is_version_ge("2.0.1", "2.0.1"))
        self.assertTrue(_is_version_ge("2.0.2", "2.0.1"))
        self.assertTrue(_is_version_ge("2.1.0", "2.0.9"))
        self.assertTrue(_is_version_ge("3.0.0", "2.9.9"))
        self.assertFalse(_is_version_ge("2.0.0", "2.0.1"))
        self.assertFalse(_is_version_ge("1.9.9", "2.0.0"))

    def test_post_restart_verification_success(self):
        """When running version >= target version, status becomes 'success' and temp files cleaned."""
        self.mgr.record_install_start("2.0.2", "C:\\fake\\Setup.exe")
        
        # Simulate running app now report 2.0.2
        success, msg = self.mgr.check_post_restart_status(running_version="2.0.2")
        self.assertTrue(success)
        self.assertIn("SUCCESSFUL", msg)

        state = self.mgr.get_state()
        self.assertEqual(state["status"], "success")
        self.assertEqual(state["last_installed_version"], "2.0.2")
        self.assertEqual(state["install_attempts"], 0)

    def test_post_restart_verification_failure_and_cooldown(self):
        """When running version < target version after restart, increments attempts and triggers cooldown on max attempts."""
        self.mgr.record_install_start("2.0.2", "C:\\fake\\Setup.exe")

        # Attempt 1: app restarted but running version is still 2.0.1
        success, msg = self.mgr.check_post_restart_status(running_version="2.0.1")
        self.assertFalse(success)
        self.assertIn("FAILED", msg)
        self.assertEqual(self.mgr.get_state()["install_attempts"], 1)

        # Attempt 2: still failed
        self.mgr.record_install_start("2.0.2", "C:\\fake\\Setup.exe")
        success2, msg2 = self.mgr.check_post_restart_status(running_version="2.0.1")
        self.assertFalse(success2)
        self.assertEqual(self.mgr.get_state()["install_attempts"], 2)
        self.assertEqual(self.mgr.get_state()["status"], "failed")
        self.assertGreater(self.mgr.get_state()["cooldown_until"], time.time())

        # Should now be blocked by loop guard
        allowed, reason = self.mgr.should_attempt_update("2.0.2", manual=False)
        self.assertFalse(allowed)
        self.assertIn("cooldown", reason.lower())

        # Manual check should bypass/reset cooldown
        allowed_manual, _ = self.mgr.should_attempt_update("2.0.2", manual=True)
        self.assertTrue(allowed_manual)

    def test_should_attempt_update_already_installed(self):
        """If running version is already >= server version, update is blocked."""
        with patch("services.update_state.get_running_app_version", return_value="2.0.2"):
            allowed, reason = self.mgr.should_attempt_update("2.0.2", manual=False)
            self.assertFalse(allowed)
            self.assertIn("already up to date", reason)

    def test_is_inno_setup_installer_detection(self):
        """Verify installer identification by name, metadata, or signature."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            # 1. By name containing setup
            f1 = tmp_path / "iHRMSMonitorSetup_v2.0.2.exe"
            f1.write_bytes(b"MZ" + b"\x00" * 1000)
            self.assertTrue(is_inno_setup_installer(f1))

            # 2. By name containing installer
            f2 = tmp_path / "iHRMS-Monitor-Installer.exe"
            f2.write_bytes(b"MZ" + b"\x00" * 1000)
            self.assertTrue(is_inno_setup_installer(f2))

            # 3. Direct executable without setup/installer keywords
            f3 = tmp_path / "iHRMS Monitor.exe"
            f3.write_bytes(b"MZ" + b"\x00" * 1000)
            self.assertFalse(is_inno_setup_installer(f3))

            # 4. Binary containing Inno Setup signature
            f4 = tmp_path / "app_bundle.exe"
            f4.write_bytes(b"MZ" + b"\x00" * 100 + b"Inno Setup" + b"\x00" * 100)
            self.assertTrue(is_inno_setup_installer(f4))

    def test_install_update_and_restart_generates_hidden_scripts(self):
        """Verify hidden VBS and PS1 scripts are generated with /DIR, PID wait, and lock cleanup."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            installer = tmp_path / "iHRMSMonitorSetup_v2.0.2.exe"
            installer.write_bytes(b"MZ" + b"x" * (1024 * 150))

            with patch("services.update_service.get_updates_directory", return_value=tmp_path), \
                 patch("services.update_service.get_app_data_directory", return_value=tmp_path), \
                 patch("subprocess.Popen") as mock_popen, \
                 patch("PySide6.QtWidgets.QApplication.instance") as mock_app:
                
                mock_app.return_value = MagicMock()

                success = install_update_and_restart(str(installer), exit_process=False, target_version="2.0.2")
                self.assertTrue(success)

                # 1. VBScript updater check
                vbs = tmp_path / "hidden_updater.vbs"
                self.assertTrue(vbs.exists())
                vbs_text = vbs.read_text(encoding="utf-8")
                self.assertIn("iHRMS Monitor Silent Background Updater", vbs_text)
                self.assertIn("updater.log", vbs_text)
                self.assertIn("/DIR=", vbs_text)
                self.assertIn("ihrms_monitor.lock", vbs_text)
                self.assertIn("taskkill /F /PID", vbs_text)
                self.assertIn("Select ProcessId from Win32_Process Where ProcessId =", vbs_text)
                self.assertIn("fso.GetFileVersion", vbs_text)
                self.assertIn("wshShell.CurrentDirectory = appDir", vbs_text)

                # 2. PowerShell fallback updater check
                ps1 = tmp_path / "hidden_updater.ps1"
                self.assertTrue(ps1.exists())
                ps1_text = ps1.read_text(encoding="utf-8")
                self.assertIn("iHRMS Monitor Silent Background Updater Fallback", ps1_text)
                self.assertIn("updater.log", ps1_text)
                self.assertIn("/DIR=", ps1_text)
                self.assertIn("-WorkingDirectory $appDir", ps1_text)

                # 3. Batch script compatibility check
                bat = tmp_path / "silent_update.bat"
                self.assertTrue(bat.exists())
                bat_text = bat.read_text(encoding="utf-8")
                self.assertIn("/VERYSILENT", bat_text)
                self.assertIn("updater.log", bat_text)
                self.assertIn('taskkill /F /IM "iHRMS Monitor.exe"', bat_text)


if __name__ == "__main__":
    unittest.main()

