"""Unit tests verifying Status card UI updates and Logo assets across the application."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton

_app = QApplication.instance() or QApplication([])

from services.session_service import SessionService
from services.activity_service import ActivityService
from services.sync_service import SyncService
from tracker.activity_tracker import TrackerState
from ui.dashboard import DashboardPage, _format_last_update_display
from ui.main_window import MainWindow, _asset_path
from ui.attendance_page import AttendancePage
from ui.leave_balance_dialog import LeaveBalanceDialog
from ui.update_dialog import UpdateDialog


class TestStatusCardAndLogo(unittest.TestCase):
    def setUp(self):
        SessionService().clear()
        SessionService().login(
            username="testuser",
            role="User",
            full_name="John Doe",
        )
        self.mock_service = MagicMock(spec=ActivityService)
        self.mock_service.get_today_total_seconds.return_value = 100
        self.mock_service.get_persisted_daily_active_seconds.return_value = 100
        self.mock_service.get_uploaded_records_count.return_value = 5
        self.mock_service.get_today_total_idle_seconds.return_value = 20
        self.mock_service.get_today_timeline.return_value = []

    def tearDown(self):
        SessionService().clear()

    # ------------------------------------------------------------------
    # 1. Heading Renamed: "Tracking Status" -> "Status"
    # ------------------------------------------------------------------

    def test_status_card_heading_renamed_to_status(self):
        """Verify the card heading is exactly 'Status' and not 'Tracking Status'."""
        page = DashboardPage(self.mock_service)
        try:
            group_boxes = page.findChildren(QGroupBox)
            titles = [gb.title() for gb in group_boxes]
            self.assertIn("Status", titles)
            self.assertNotIn("Tracking Status", titles)
            self.assertNotIn("Tracking & Sync Status", titles)
        finally:
            page.close()
            page.deleteLater()

    # ------------------------------------------------------------------
    # 2. Display Only These Fields: Status, Version, Idle Time, Last Update
    # ------------------------------------------------------------------

    def test_status_card_displayed_fields(self):
        """Verify the Status card displays Status, Version, Idle Time, and Last Update, and NOT Records Uploaded."""
        page = DashboardPage(self.mock_service)
        try:
            status_card = None
            for gb in page.findChildren(QGroupBox):
                if gb.title() == "Status":
                    status_card = gb
                    break
            self.assertIsNotNone(status_card, "Status group box not found")

            # Check visible labels inside the Status card
            visible_labels = [
                lbl.text()
                for lbl in status_card.findChildren(QLabel)
                if lbl.isVisibleTo(status_card)
            ]

            # Visible fields must contain:
            # - Status prefix and indicator
            self.assertTrue(any("Status" in t for t in visible_labels))
            self.assertTrue(any("Online" in t or "Offline" in t for t in visible_labels))
            # - Version
            self.assertTrue(any("Version:" in t for t in visible_labels))
            # - Idle Time
            self.assertTrue(any("Idle Time:" in t for t in visible_labels))
            # - Last Update
            self.assertTrue(any("Last Update:" in t for t in visible_labels))

            # Must NOT display Records Uploaded or Last Successful Sync
            for text in visible_labels:
                self.assertNotIn("Records Uploaded", text)
                self.assertNotIn("Last Successful Sync", text)

            # Paused/Resume button must be present in the Status card
            btn = status_card.findChild(QPushButton, "WorkPulseToggleButton")
            self.assertIsNotNone(btn)
            self.assertTrue(btn.isVisibleTo(status_card))
        finally:
            page.close()
            page.deleteLater()

    # ------------------------------------------------------------------
    # 3. Online/Offline Logic
    # ------------------------------------------------------------------

    def test_dynamic_online_offline_transitions(self):
        """Verify dynamic Online/Offline transitions with green/red styling."""
        page = DashboardPage(self.mock_service)
        try:
            page.set_network_status(True)
            self.assertEqual(page.network_status_label.text(), "● Online")
            self.assertIn("#10b981", page.network_status_label.styleSheet())

            page.set_network_status(False)
            self.assertEqual(page.network_status_label.text(), "● Offline")
            self.assertIn("#ef4444", page.network_status_label.styleSheet())

            page.set_network_status(True)
            self.assertEqual(page.network_status_label.text(), "● Online")
            self.assertIn("#10b981", page.network_status_label.styleSheet())
        finally:
            page.close()
            page.deleteLater()

    # ------------------------------------------------------------------
    # 4. Version, Idle Time, and Last Update Formatting
    # ------------------------------------------------------------------

    def test_version_updates(self):
        """Verify version is obtained and updates dynamically."""
        page = DashboardPage(self.mock_service)
        try:
            page.set_version("1.2.5")
            self.assertEqual(page.version_label.text(), "Version: 1.2.5")
        finally:
            page.close()
            page.deleteLater()

    def test_idle_time_updates(self):
        """Verify idle time updates dynamically via tracker state."""
        page = DashboardPage(self.mock_service)
        try:
            state = TrackerState(
                is_workpulse=True,
                is_idle=True,
                idle_seconds=45,
                current_application="Code",
                current_window_title="file.py",
            )
            page.update_tracker_state(state)
            self.assertEqual(page.idle_time_label.text(), "Idle Time: 45 seconds")

            state_min = TrackerState(
                is_workpulse=True,
                is_idle=True,
                idle_seconds=125,
                current_application="Code",
                current_window_title="file.py",
            )
            page.update_tracker_state(state_min)
            self.assertEqual(page.idle_time_label.text(), "Idle Time: 2 minutes 5 seconds")
        finally:
            page.close()
            page.deleteLater()

    def test_last_update_date_format_and_empty_state(self):
        """Verify Last Update formats dates to DD-MM-YYYY and shows Not available when empty."""
        # Empty / Never -> Not available
        self.assertEqual(_format_last_update_display("Never"), "Not available")
        self.assertEqual(_format_last_update_display(""), "Not available")
        self.assertEqual(_format_last_update_display(None), "Not available")

        # Standard timestamps -> DD-MM-YYYY
        res = _format_last_update_display("15 Sep 2026, 10:32:45 AM")
        self.assertIn("15-09-2026", res)
        self.assertIn("10:32 AM", res)

        res2 = _format_last_update_display("29 Sep 2026, 05:31:36 PM")
        self.assertIn("29-09-2026", res2)
        self.assertIn("05:31 PM", res2)

        page = DashboardPage(self.mock_service)
        try:
            SyncService.last_successful_sync_time = "13 Oct 2026, 09:53:00 AM"
            page.refresh(async_mode=False)
            self.assertIn("13-10-2026, 09:53 AM", page.last_update_label.text())
        finally:
            page.close()
            page.deleteLater()

    # ------------------------------------------------------------------
    # 5. Preserve Paused Button
    # ------------------------------------------------------------------

    def test_paused_button_preserved_and_functional(self):
        """Verify Paused button toggles workpulse pause state as expected."""
        page = DashboardPage(self.mock_service)
        try:
            page.set_paused(False)
            page.set_workpulse_active(True)
            btn = page.workpulse_toggle_button
            self.assertIsNotNone(btn)
            self.assertEqual(btn.text(), "Paused")

            btn.click()
            self.assertEqual(btn.text(), "Resume")
            self.assertTrue(page.is_paused())

            btn.click()
            self.assertEqual(btn.text(), "Paused")
            self.assertFalse(page.is_paused())
        finally:
            page.close()
            page.deleteLater()

    # ------------------------------------------------------------------
    # 6. Logo Assets Consistency
    # ------------------------------------------------------------------

    def test_restored_original_logo_assets(self):
        """Verify restored original logo PNG and multi-resolution ICO exist and have valid properties."""
        logo_path = _asset_path(os.path.join("assets", "ihrms_icon.png"))
        self.assertTrue(os.path.isfile(logo_path))
        with Image.open(logo_path) as img:
            self.assertEqual(img.mode, "RGBA")
            self.assertEqual(img.size, (1024, 914))

        ico_path = _asset_path(os.path.join("assets", "ihrms-logo-icon.ico"))
        self.assertTrue(os.path.isfile(ico_path))
        with Image.open(ico_path) as img:
            sizes = img.info.get("sizes", set())
            self.assertIn((16, 16), sizes)
            self.assertIn((32, 32), sizes)
            self.assertIn((64, 64), sizes)
            self.assertIn((256, 256), sizes)

    # ------------------------------------------------------------------
    # 7. Attendance Rate Card Single-Line Display
    # ------------------------------------------------------------------

    def test_attendance_rate_displayed_on_single_line(self):
        """Verify Attendance Rate label displays on a single line without wrapping or newline."""
        page = AttendancePage()
        try:
            self.assertTrue(hasattr(page, "rate_label"))
            self.assertEqual(page.rate_label.text(), "Attendance Rate")
            self.assertNotIn("\n", page.rate_label.text())
            self.assertFalse(page.rate_label.wordWrap())
        finally:
            page.close()
            page.deleteLater()

    def test_needs_improvement_badge_preserved(self):
        """Verify Needs Improvement badge and styling are preserved when attendance rate is below 75%."""
        page = AttendancePage()
        try:
            # Simulate low attendance (e.g. 5 present out of 20 working days = 25%)
            mock_data = {
                "month": "October",
                "days": [
                    {"status_code": "P"} for _ in range(5)
                ] + [
                    {"status_code": "A"} for _ in range(15)
                ],
                "summary": {
                    "total_days": 20,
                    "present": 5,
                    "absent": 15,
                    "holiday": 0,
                    "weekoff": 0,
                },
            }
            page._apply_attendance_data(mock_data)
            self.assertEqual(page.rating_badge.text(), "Needs Improvement")
            style = page.rating_badge.styleSheet()
            self.assertIn("#FEF3C7", style)  # background
            self.assertIn("#92400E", style)  # text color
            self.assertIn("#FCD34D", style)  # border color
        finally:
            page.close()
            page.deleteLater()


if __name__ == "__main__":
    unittest.main()
