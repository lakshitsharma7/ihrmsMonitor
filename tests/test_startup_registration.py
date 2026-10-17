"""Unit and integration tests for Windows auto-start registration and startup behavior."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from system import startup


class TestStartupRegistration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(__file__).resolve().parent / "temp_test_startup"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.fake_exe = self.temp_dir / "Workpulse.exe"
        self.fake_exe.write_text("MZ fake executable header")

    def tearDown(self):
        try:
            if self.fake_exe.exists():
                self.fake_exe.unlink()
            if self.temp_dir.exists():
                self.temp_dir.rmdir()
        except Exception:
            pass

    def test_01_find_windows_executable_explicit(self):
        """Verify _find_windows_executable finds explicit executable path."""
        exe = startup._find_windows_executable(str(self.fake_exe))
        self.assertEqual(exe, self.fake_exe)

    def test_02_find_windows_executable_installed_path(self):
        """Verify _find_windows_executable discovers installed path in local appdata."""
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.temp_dir)}):
            installed_dir = self.temp_dir / "Programs" / "Workpulse"
            installed_dir.mkdir(parents=True, exist_ok=True)
            installed_exe = installed_dir / "Workpulse.exe"
            installed_exe.write_text("MZ test executable")

            try:
                exe = startup._find_windows_executable(None)
                self.assertEqual(exe, installed_exe)
            finally:
                if installed_exe.exists():
                    installed_exe.unlink()
                if installed_dir.exists():
                    installed_dir.rmdir()

    def test_03_windows_is_enabled_true_for_valid_binary(self):
        """Verify _windows_is_enabled returns True when registry entry points to existing binary."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
        mock_winreg.QueryValueEx.return_value = (f'"{self.fake_exe}" --startup', 1)

        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            self.assertTrue(startup._windows_is_enabled())

    def test_04_windows_is_enabled_false_for_missing_binary(self):
        """Verify _windows_is_enabled returns False when registry entry points to deleted binary."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
        non_existent = str(self.temp_dir / "Deleted_Workpulse.exe")
        mock_winreg.QueryValueEx.return_value = (f'"{non_existent}" --startup', 1)

        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            self.assertFalse(startup._windows_is_enabled())

    def test_05_windows_set_enabled_creates_registry_entry(self):
        """Verify _windows_set_enabled sets the Run key value with --startup argument."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.CreateKeyEx.return_value.__enter__.return_value = mock_key

        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            success = startup._windows_set_enabled(True, exe_path=str(self.fake_exe))
            mock_winreg.SetValueEx.assert_called_once()
            args = mock_winreg.SetValueEx.call_args[0]
            self.assertEqual(args[1], startup.APP_NAME)
            self.assertIn("--startup", args[4])
            self.assertIn(str(self.fake_exe), args[4])

    def test_06_windows_set_enabled_false_removes_entry(self):
        """Verify _windows_set_enabled(False) deletes the Run key values."""
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.CreateKeyEx.return_value.__enter__.return_value = mock_key

        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            success = startup._windows_set_enabled(False)
            self.assertTrue(success)
            self.assertTrue(mock_winreg.DeleteValue.called)

    def test_07_ensure_startup_registered_repairs_when_missing(self):
        """Verify ensure_startup_registered automatically enables startup if not active."""
        with patch.object(startup, "is_enabled", return_value=False), \
             patch.object(startup, "set_enabled", return_value=True) as mock_set:
            result = startup.ensure_startup_registered(str(self.fake_exe))
            self.assertTrue(result)
            mock_set.assert_called_once_with(True, str(self.fake_exe))


if __name__ == "__main__":
    unittest.main()
