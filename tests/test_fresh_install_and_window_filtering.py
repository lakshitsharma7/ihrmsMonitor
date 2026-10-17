"""Tests for fresh installation empty company-code behavior and single-instance window filtering."""

import unittest
from unittest.mock import patch, MagicMock
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for UI tests
app = QApplication.instance() or QApplication([])

from services.secure_session import SessionStore
from services.session_service import SessionService
from ui.login_window import LoginWindow


class TestFreshInstallAndWindowFiltering(unittest.TestCase):

    def setUp(self):
        self.store = SessionStore()
        self.settings = self.store.settings
        self.store.clear_session()
        SessionService().clear()
        self.settings.remove("last_company_code")
        self.settings.remove("last_username")
        self.settings.remove("last_employee_id")
        self.settings.remove("ApiConfig/last_verified_code")
        self.settings.sync()

    def tearDown(self):
        self.store.clear_session()
        SessionService().clear()
        self.settings.remove("last_company_code")
        self.settings.remove("last_username")
        self.settings.remove("last_employee_id")
        self.settings.remove("ApiConfig/last_verified_code")
        self.settings.sync()

    def test_fresh_installation_company_code_and_credentials_empty(self):
        """On a fresh installation with no saved session, all fields must be empty."""
        win = LoginWindow()
        self.assertEqual(win.company_code_input.text(), "")
        self.assertEqual(win.username_input.text(), "")
        self.assertEqual(win.password_input.text(), "")
        self.assertIsNone(self.store.get_last_company_code())
        win.close()
        win.deleteLater()

    def test_fresh_installation_ignores_stale_apiconfig_or_last_code(self):
        """Even if stale registry entries exist, fresh launch must show empty fields and get_last_company_code returns None."""
        self.settings.setValue("ApiConfig/last_verified_code", "STALE_CODE_999")
        self.settings.setValue("last_company_code", "STALE_CODE_999")
        self.settings.sync()

        # get_last_company_code must only return from active session, NOT from stale ApiConfig cache
        self.assertIsNone(self.store.get_last_company_code())

        win = LoginWindow()
        self.assertEqual(win.company_code_input.text(), "", "Company code field must start strictly empty on launch")
        self.assertEqual(win.username_input.text(), "")
        self.assertEqual(win.password_input.text(), "")
        win.close()
        win.deleteLater()

    def test_clear_session_purges_stale_markers(self):
        """clear_session must purge last_company_code and ApiConfig/last_verified_code."""
        self.settings.setValue("last_company_code", "INDO")
        self.settings.setValue("last_username", "dinesh")
        self.settings.setValue("last_employee_id", "EC-098")
        self.settings.setValue("ApiConfig/last_verified_code", "INDO")
        self.settings.sync()

        self.store.clear_session()

        self.assertIsNone(self.settings.value("last_company_code"))
        self.assertIsNone(self.settings.value("last_username"))
        self.assertIsNone(self.settings.value("last_employee_id"))
        self.assertIsNone(self.settings.value("ApiConfig/last_verified_code"))

    def test_window_filtering_excludes_all_internal_helper_windows(self):
        """Simulate Windows EnumWindows and verify only genuine top-level application windows are selected."""
        target_pid = 1234

        mock_windows = [
            # hwnd, pid, parent, class_name, title
            (101, target_pid, 0, "Qt6112ThemeChangeObserverWindow", ""),
            (102, target_pid, 0, "Qt6112ScreenChangeObserverWindow", ""),
            (103, target_pid, 0, "_q_titlebar", "_q_titlebar"),
            (104, target_pid, 0, "CicLoaderWndClass", ""),
            (105, target_pid, 0, "QTrayIconMessageWindow", "Tray"),
            (106, target_pid, 0, "IME", "Default IME"),
            (107, target_pid, 0, "MSCTFIME UI", "MSCTFIME UI"),
            (108, target_pid, 0, "UAC_InputIndicatorOverlayWnd", ""),
            (109, target_pid, 0, "UAC Input Indicator", ""),
            (110, target_pid, 100, "Qt6112QWindowIcon", "iHRMS Desktop - Login"),  # child of 100
            (111, 9999, 0, "Qt6112QWindowIcon", "iHRMS Desktop - Login"),          # different pid
            (112, target_pid, 0, "Qt6112QWindowIcon", "iHRMS Desktop - Login"),    # GENUINE LoginWindow
            (113, target_pid, 0, "Qt6112QWindowIcon", "Workpulse"),                 # GENUINE MainWindow
        ]

        # Apply exact filtering logic from app.py
        filtered_hwnds = []
        for hwnd, win_pid, parent, cls_name, title in mock_windows:
            # 1. Must be a top-level window (no parent)
            if parent != 0:
                continue

            # 2. Match PID if known
            if target_pid and win_pid != target_pid:
                continue

            # 3. Class name must NOT be internal Qt helper or observer window
            cls = cls_name.lower()
            if any(k in cls for k in ("observer", "titlebar", "cicloader", "trayicon", "ime", "uac", "indicator", "message")):
                continue

            # 4. Title must be non-empty and match application window title
            t = (title or "").strip()
            if not t or not any(x in t for x in ("iHRMS Desktop", "Workpulse", "iHRMS Monitor")):
                continue

            filtered_hwnds.append(hwnd)

        self.assertEqual(filtered_hwnds, [112, 113], "Only genuine LoginWindow and MainWindow must be selected")


if __name__ == "__main__":
    unittest.main()
