"""Unit tests for macOS Startup, Recovery (KeepAlive), LaunchAgent, and Keychain Session persistence."""

import os
import sys
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from system import startup
from services import secure_session


class TestMacOSStartupAndRecovery(unittest.TestCase):
    """Test macOS-specific LaunchAgent generation, recovery configuration, and Keychain persistence."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_home = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_launch_agent_template_content_and_recovery(self):
        """Verify that LaunchAgent plist contains required recovery, KeepAlive, and interactive settings."""
        template = startup._LAUNCH_AGENT_TEMPLATE
        formatted = template.format(
            label="com.indovision.ihrms-desktop",
            exe_path="/Applications/iHRMS-Desktop.app/Contents/MacOS/iHRMS-Desktop",
        )

        # Must parse as valid Apple property list
        parsed = plistlib.loads(formatted.encode("utf-8"))

        self.assertEqual(parsed["Label"], "com.indovision.ihrms-desktop")
        self.assertEqual(
            parsed["ProgramArguments"],
            ["/Applications/iHRMS-Desktop.app/Contents/MacOS/iHRMS-Desktop", "--startup"],
        )
        self.assertTrue(parsed["RunAtLoad"])
        self.assertEqual(parsed["ProcessType"], "Interactive")
        self.assertEqual(parsed["ThrottleInterval"], 10)

        # KeepAlive configuration for crash & unexpected termination recovery
        keep_alive = parsed["KeepAlive"]
        self.assertFalse(keep_alive["SuccessfulExit"])
        self.assertTrue(keep_alive["Crashed"])

    @patch("pathlib.Path.home")
    @patch("subprocess.run")
    def test_macos_set_enabled_creates_plist_and_calls_launchctl(self, mock_run, mock_home):
        """Test enabling macOS auto-start generates plist and invokes launchctl."""
        mock_home.return_value = self.mock_home
        mock_run.return_value = MagicMock(returncode=0)

        target_exe = "/Applications/iHRMS-Desktop.app/Contents/MacOS/iHRMS-Desktop"
        ok = startup._macos_set_enabled(True, exe_path=target_exe)
        self.assertTrue(ok)

        plist_file = self.mock_home / "Library" / "LaunchAgents" / "com.indovision.ihrms-desktop.plist"
        self.assertTrue(plist_file.is_file(), "LaunchAgent plist file should exist")

        data = plistlib.loads(plist_file.read_bytes())
        self.assertEqual(data["Label"], "com.indovision.ihrms-desktop")
        self.assertIn("--startup", data["ProgramArguments"])
        self.assertEqual(data["ProgramArguments"][0], target_exe)

        # Verify launchctl commands were called
        called_cmds = [call[0][0] for call in mock_run.call_args_list]
        self.assertTrue(any("load" in cmd for cmd in called_cmds))

    @patch("pathlib.Path.home")
    @patch("subprocess.run")
    def test_macos_set_enabled_cleans_legacy_plist(self, mock_run, mock_home):
        """Test enabling macOS auto-start cleans up legacy com.activitytracker.app plist."""
        mock_home.return_value = self.mock_home
        mock_run.return_value = MagicMock(returncode=0)

        # Create legacy plist
        legacy_dir = self.mock_home / "Library" / "LaunchAgents"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = legacy_dir / "com.activitytracker.app.plist"
        legacy_file.write_text("dummy legacy", encoding="utf-8")

        target_exe = "/Applications/iHRMS-Desktop.app/Contents/MacOS/iHRMS-Desktop"
        startup._macos_set_enabled(True, exe_path=target_exe)

        self.assertFalse(legacy_file.exists(), "Legacy plist file should have been removed")

    @patch("pathlib.Path.home")
    @patch("subprocess.run")
    def test_macos_set_disabled_unloads_and_removes_plist(self, mock_run, mock_home):
        """Test disabling macOS auto-start removes plist and unloads via launchctl."""
        mock_home.return_value = self.mock_home
        mock_run.return_value = MagicMock(returncode=0)

        plist_file = self.mock_home / "Library" / "LaunchAgents" / "com.indovision.ihrms-desktop.plist"
        plist_file.parent.mkdir(parents=True, exist_ok=True)
        plist_file.write_text("test", encoding="utf-8")

        ok = startup._macos_set_enabled(False)
        self.assertTrue(ok)
        self.assertFalse(plist_file.exists(), "Plist file should be removed on disable")

        called_cmds = [call[0][0] for call in mock_run.call_args_list]
        self.assertTrue(any("unload" in cmd for cmd in called_cmds))

    @patch("pathlib.Path.home")
    def test_macos_is_enabled_checks_binary_existence(self, mock_home):
        """Test _macos_is_enabled checks if target binary exists on disk."""
        mock_home.return_value = self.mock_home

        # 1. No plist -> False
        self.assertFalse(startup._macos_is_enabled())

        # 2. Plist exists pointing to non-existent binary
        plist_file = self.mock_home / "Library" / "LaunchAgents" / "com.indovision.ihrms-desktop.plist"
        plist_file.parent.mkdir(parents=True, exist_ok=True)
        content = startup._LAUNCH_AGENT_TEMPLATE.format(
            label="com.indovision.ihrms-desktop",
            exe_path="/nonexistent/path/to/binary",
        )
        plist_file.write_text(content, encoding="utf-8")

        # In non-frozen dev mode, it returns True if plist exists;
        # In frozen mode it verifies file on disk.
        with patch.object(sys, "frozen", True, create=True):
            self.assertFalse(startup._macos_is_enabled())

        # When pointing to a real file on disk
        real_file = self.mock_home / "fake_binary"
        real_file.write_text("binary", encoding="utf-8")
        content_real = startup._LAUNCH_AGENT_TEMPLATE.format(
            label="com.indovision.ihrms-desktop",
            exe_path=str(real_file),
        )
        plist_file.write_text(content_real, encoding="utf-8")

        with patch.object(sys, "frozen", True, create=True):
            self.assertTrue(startup._macos_is_enabled())

    @patch("sys.platform", "darwin")
    @patch("subprocess.run")
    def test_macos_keychain_write_read_delete(self, mock_run):
        """Test session storage via macOS /usr/bin/security Keychain commands."""
        test_data = {
            "company_code": "INDO",
            "indo_code": "SEC_123",
            "api_key": "KEY_ABC",
            "device_token": "TOK_XYZ",
            "username": "employee1",
        }

        # 1. Test _cred_write
        mock_run.return_value = MagicMock(returncode=0)
        write_ok = secure_session._cred_write("iHRMS_Test_Target", "employee1", test_data)
        self.assertTrue(write_ok)

        write_args = mock_run.call_args[0][0]
        self.assertEqual(write_args[0], "/usr/bin/security")
        self.assertEqual(write_args[1], "add-generic-password")
        self.assertIn("-a", write_args)
        self.assertIn("-s", write_args)
        self.assertIn("-w", write_args)
        self.assertIn("-U", write_args)

        # 2. Test _cred_read
        import json
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(test_data))
        loaded_data = secure_session._cred_read("iHRMS_Test_Target")
        self.assertEqual(loaded_data, test_data)

        read_args = mock_run.call_args[0][0]
        self.assertEqual(read_args[0], "/usr/bin/security")
        self.assertEqual(read_args[1], "find-generic-password")
        self.assertIn("-w", read_args)

        # 3. Test _cred_delete
        mock_run.return_value = MagicMock(returncode=0)
        delete_ok = secure_session._cred_delete("iHRMS_Test_Target")
        self.assertTrue(delete_ok)

        delete_args = mock_run.call_args[0][0]
        self.assertEqual(delete_args[0], "/usr/bin/security")
        self.assertEqual(delete_args[1], "delete-generic-password")


if __name__ == "__main__":
    unittest.main()
