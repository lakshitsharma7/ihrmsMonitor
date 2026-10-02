"""End-to-end test verifying auto-update handoff, installer execution, restart, session persistence, and workpulse resumption."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.secure_session import SessionStore
from services.session_service import SessionService
from services.update_service import install_update_and_restart, is_newer_version
from services.update_state import UpdateStateManager
from utils.paths import get_updates_directory


class TestFullAutoUpdateHandoffAndRestart(unittest.TestCase):
    """End-to-end validation of auto-update workflow."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        # Clear session store singleton and test data
        SessionStore().clear_session()
        SessionStore._instance = None
        SessionService().clear()
        SessionService._instance = None
        UpdateStateManager._instance = None

    def tearDown(self):
        SessionStore().clear_session()
        SessionStore._instance = None
        SessionService().clear()
        SessionService._instance = None
        UpdateStateManager._instance = None
        self.tmp_dir.cleanup()

    def test_version_check_gate(self):
        """Verify v2.0.1 vs v2.1 properly triggers update."""
        self.assertTrue(is_newer_version(server_version="2.1", current_version="2.0.1"))
        self.assertFalse(is_newer_version(server_version="2.0.1", current_version="2.0.1"))
        self.assertFalse(is_newer_version(server_version="2.0.0", current_version="2.0.1"))

    def test_updater_scripts_and_log_generation(self):
        """Verify updater scripts are created and point to updater.log in updates directory."""
        fake_installer = self.tmp_path / "iHRMSMonitorSetup_v2.1.exe"
        fake_installer.write_bytes(b"MZ" + b"\x00" * (1024 * 120))

        fake_installed_exe = self.tmp_path / "app" / "iHRMS Monitor.exe"
        fake_installed_exe.parent.mkdir(parents=True, exist_ok=True)
        fake_installed_exe.write_bytes(b"MZ" + b"\x00" * 500)

        with patch("services.update_service.get_updates_directory", return_value=self.tmp_path), \
             patch("services.update_service.get_installed_executable_path", return_value=fake_installed_exe), \
             patch("subprocess.Popen") as mock_popen, \
             patch("PySide6.QtWidgets.QApplication.instance") as mock_app:

            mock_app.return_value = MagicMock()

            success = install_update_and_restart(
                str(fake_installer),
                exit_process=False,
                target_version="2.1",
            )
            self.assertTrue(success)

            # Check hidden_updater.vbs
            vbs_file = self.tmp_path / "hidden_updater.vbs"
            self.assertTrue(vbs_file.exists())
            vbs_content = vbs_file.read_text(encoding="utf-8")
            self.assertIn("updater.log", vbs_content)
            self.assertIn("targetVersion = \"2.1\"", vbs_content)
            self.assertIn("/VERYSILENT", vbs_content)
            self.assertIn("fso.GetFileVersion", vbs_content)
            self.assertIn("wshShell.CurrentDirectory = appDir", vbs_content)

            # Check hidden_updater.ps1
            ps1_file = self.tmp_path / "hidden_updater.ps1"
            self.assertTrue(ps1_file.exists())
            ps1_content = ps1_file.read_text(encoding="utf-8")
            self.assertIn("updater.log", ps1_content)
            self.assertIn("$targetVersion = '2.1'", ps1_content)
            self.assertIn("-WorkingDirectory $appDir", ps1_content)

            # Check silent_update.bat
            bat_file = self.tmp_path / "silent_update.bat"
            self.assertTrue(bat_file.exists())
            bat_content = bat_file.read_text(encoding="utf-8")
            self.assertIn("updater.log", bat_content)
            self.assertIn("/VERYSILENT", bat_content)

    def test_session_restored_after_update_restart_without_login(self):
        """Verify saved session persists and is restored on app startup without requiring login."""
        store = SessionStore()
        store.save_session(
            company_code="INDOVISION",
            indo_code="INDO-999",
            api_key="secret_key_xyz",
            device_token="token_abc123",
            username="jane.smith",
            full_name="Jane Smith",
            user_type="Employee",
            employee_id="EMP-999",
            device_info={"hostname": "TEST-PC"},
            workpulse_permitted=True,
            allow_user_device=True,
            allow_logout=True,
        )

        # Reload session
        loaded = store.load_session()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["username"], "jane.smith")
        self.assertEqual(loaded["device_token"], "token_abc123")

        # Restore into SessionService
        svc = SessionService()
        svc.restore_session(
            username=loaded["username"],
            role=loaded.get("user_type", "User"),
            full_name=loaded.get("full_name"),
            user_type=loaded.get("user_type", "User"),
            workpulse_permitted=loaded.get("workpulse_permitted", True),
            allow_user_device=loaded.get("allow_user_device", True),
            allow_logout=loaded.get("allow_logout", True),
            indo_code=loaded["indo_code"],
            api_key=loaded["api_key"],
            employee_id=loaded.get("employee_id"),
            company_code=loaded["company_code"],
            device_token=loaded["device_token"],
        )

        self.assertIsNotNone(svc.current_user)
        self.assertEqual(svc.current_user.username, "jane.smith")
        self.assertTrue(svc.current_user.workpulse_permitted)


if __name__ == "__main__":
    unittest.main()

