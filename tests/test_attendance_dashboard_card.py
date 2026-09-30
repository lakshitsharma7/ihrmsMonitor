"""Unit tests for Attendance card on Dashboard."""

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from config.api_config import ApiConfig
from services.activity_service import ActivityService
from services.attendance_service import AttendanceService
from services.session_service import SessionService
from ui.dashboard import DashboardPage, _format_time_ampm

app = QApplication.instance() or QApplication([])


class TestAttendanceDashboardCard(unittest.TestCase):
    def setUp(self):
        ApiConfig().reset()
        SessionService().clear()
        AttendanceService().clear_state()

    def tearDown(self):
        ApiConfig().reset()
        SessionService().clear()
        AttendanceService().clear_state()

    def test_format_time_ampm_helper(self):
        """Verify _format_time_ampm formats standard strings into HH:MM AM/PM."""
        self.assertEqual(_format_time_ampm("2026-09-11 09:32:15"), "09:32 AM")
        self.assertEqual(_format_time_ampm("2026-09-11 14:45:00"), "02:45 PM")
        self.assertEqual(_format_time_ampm("10:36:42"), "10:36 AM")
        self.assertEqual(_format_time_ampm("14:39:41"), "02:39 PM")
        self.assertEqual(_format_time_ampm("09:32 AM"), "09:32 AM")
        self.assertIsNone(_format_time_ampm(None))
        self.assertIsNone(_format_time_ampm(""))
        self.assertIsNone(_format_time_ampm("null"))
        self.assertIsNone(_format_time_ampm("-"))

    def test_dashboard_attendance_card_rendering_and_defaults(self):
        """Verify dashboard displays Start Time and Not Punched by default."""
        mock_svc = MagicMock(spec=ActivityService)
        mock_svc.get_today_total_seconds.return_value = 0
        mock_svc.get_uploaded_records_count.return_value = 0
        mock_svc.get_today_total_idle_seconds.return_value = 0
        mock_svc.get_today_timeline.return_value = []

        # Record daily tracking start
        AttendanceService().record_tracking_start()

        dashboard = DashboardPage(activity_service=mock_svc)
        self.assertTrue(hasattr(dashboard, "start_time_label"))
        self.assertTrue(hasattr(dashboard, "punch_time_label"))

        # Start time should be displayed with AM/PM
        start_txt = dashboard.start_time_label.text()
        self.assertTrue(start_txt.startswith("Start Time: "))
        self.assertNotIn("--:--", start_txt)

        # Punch time should show "Not Punched"
        self.assertEqual(dashboard.punch_time_label.text(), "Punch Time: Not Punched")

    def test_dashboard_attendance_card_with_punches(self):
        """Verify dashboard updates Punch Time when punch is recorded."""
        mock_svc = MagicMock(spec=ActivityService)
        mock_svc.get_today_total_seconds.return_value = 0
        mock_svc.get_uploaded_records_count.return_value = 0
        mock_svc.get_today_total_idle_seconds.return_value = 0
        mock_svc.get_today_timeline.return_value = []

        # Record daily tracking start and punch in
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        AttendanceService().record_tracking_start()
        AttendanceService().record_punch_in(f"{today_str} 09:45:00", date_str=today_str)

        dashboard = DashboardPage(activity_service=mock_svc)
        dashboard.refresh(async_mode=False)

        self.assertEqual(dashboard.punch_time_label.text(), "Punch Time: 09:45 AM")
        self.assertEqual(dashboard.attendance_punch_val_label.text(), "🟢 09:45 AM")
        self.assertEqual(dashboard.attendance_status_badge.text(), "● Punched In")

    def test_dashboard_attendance_card_ui_structure_and_states(self):
        """Verify modern 2-column attendance card UI elements and status badge."""
        mock_svc = MagicMock(spec=ActivityService)
        mock_svc.get_today_total_seconds.return_value = 0
        mock_svc.get_uploaded_records_count.return_value = 0
        mock_svc.get_today_total_idle_seconds.return_value = 0
        mock_svc.get_today_timeline.return_value = []

        dashboard = DashboardPage(activity_service=mock_svc)
        self.assertTrue(hasattr(dashboard, "attendance_header_title"))
        self.assertTrue(hasattr(dashboard, "attendance_header_subtitle"))
        self.assertTrue(hasattr(dashboard, "attendance_start_val_label"))
        self.assertTrue(hasattr(dashboard, "attendance_punch_val_label"))
        self.assertTrue(hasattr(dashboard, "attendance_status_badge"))

        self.assertIn("Attendance", dashboard.attendance_header_title.text())
        self.assertEqual(dashboard.attendance_header_subtitle.text(), "Today's Attendance")

        # Initial unpunched state
        dashboard._update_attendance_ui({
            "tracking_started_at": "2026-09-30 14:53:00",
            "punch_in": None,
            "punch_out": None,
        })
        self.assertEqual(dashboard.attendance_start_val_label.text(), "🖥 02:53 PM")
        self.assertEqual(dashboard.attendance_punch_val_label.text(), "Not Punched")
        self.assertEqual(dashboard.attendance_status_badge.text(), "● Not Punched")

        # Punched In state
        dashboard._update_attendance_ui({
            "tracking_started_at": "2026-09-30 14:53:00",
            "punch_in": "2026-09-30 14:55:00",
            "punch_out": None,
        })
        self.assertEqual(dashboard.attendance_punch_val_label.text(), "🟢 02:55 PM")
        self.assertEqual(dashboard.attendance_status_badge.text(), "● Punched In")

        # Punched Out state
        dashboard._update_attendance_ui({
            "tracking_started_at": "2026-09-30 14:53:00",
            "punch_in": "2026-09-30 14:55:00",
            "punch_out": "2026-09-30 18:30:00",
        })
        self.assertEqual(dashboard.attendance_status_badge.text(), "● Punched Out")


if __name__ == "__main__":
    unittest.main()

