"""Unit and integration tests for Attendance Record API and UI."""

import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from config.api_config import ApiConfig
from services.attendance_service import AttendanceService
from services.session_service import SessionService, UserSession
from ui.attendance_page import AttendancePage
from ui.dashboard import DashboardPage
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)


class TestAttendanceRecordApiAndUi(unittest.TestCase):
    """Test suite for Attendance record fetching, parsing, and UI rendering."""

    def setUp(self):
        self.service = AttendanceService()
        self.api_config = ApiConfig()

    def test_01_api_config_endpoint_resolution(self):
        """Verify get_attendance_record_url returns correct endpoint."""
        with patch.object(self.api_config, "_base_url", "https://test.api/ci4/api"):
            url = self.api_config.get_attendance_record_url
            self.assertEqual(url, "https://test.api/ci4/api/attendance/get_attendance_record")

    def test_02_get_monthly_attendance_record_payload_and_freezed_parsing(self):
        """Verify get_monthly_attendance_record correctly builds request and parses freezed response."""
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    "EL", "P", "P", "P", "P", "P", "P", "P", "P", "P",
                    "P", "Week Off", "A", "A", "P", "A", "A", "A", "Week Off", "A",
                    "P", "A", "P", "P", "P", "Week Off", "A", "A", "A", "A"
                ]
            },
            "freezed": "1"
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = mock_response_data
            mock_post.return_value = mock_resp

            res = self.service.get_monthly_attendance_record(
                month="September",
                year=2025,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            # Verify POST was called with expected dynamic parameters
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            req_data = kwargs["data"]
            self.assertEqual(req_data["indo_code"], "EC-100")
            self.assertEqual(req_data["key"], "testapikey111")
            self.assertEqual(req_data["month"], "September")
            self.assertEqual(req_data["year"], "2025")

            # Verify parsed output structure
            self.assertEqual(res["month"], "September")
            self.assertEqual(res["year"], 2025)
            self.assertTrue(res["freezed"])
            self.assertEqual(len(res["days"]), 30) # September has 30 days

            # Check specific days
            day_1 = res["days"][0]
            self.assertEqual(day_1["day_num"], 1)
            self.assertEqual(day_1["date"], "2025-09-01")
            self.assertEqual(day_1["day_name"], "Mon")
            self.assertEqual(day_1["status_code"], "EL")
            self.assertIn("Leave", day_1["status_label"])

            day_2 = res["days"][1]
            self.assertEqual(day_2["status_code"], "P")
            self.assertEqual(day_2["status_label"], "Present")

            day_12 = res["days"][11]
            self.assertEqual(day_12["status_code"], "Week Off")
            self.assertEqual(day_12["status_label"], "Week Off")

            # Check summary calculation
            summary = res["summary"]
            self.assertEqual(summary["total_days"], 30)
            self.assertGreater(summary["present"], 0)
            self.assertGreater(summary["absent"], 0)
            self.assertGreater(summary["week_off"], 0)

    def test_03_get_monthly_attendance_record_unfreezed_parsing(self):
        """Verify get_monthly_attendance_record parses unfreezed response with holidays and weekoffs."""
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [None],
                "holiday_days": [
                    {"name": "Independence Day", "date": "2025-08-15"}
                ],
                "weekoff": [
                    {"date": "2025-08-02"},
                    {"date": "2025-08-03"}
                ],
                "leave_days": [],
                "comp_off_days": []
            },
            "freezed": "0"
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = mock_response_data
            mock_post.return_value = mock_resp

            res = self.service.get_monthly_attendance_record(
                month="August",
                year=2025,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            self.assertEqual(len(res["days"]), 31) # August has 31 days
            self.assertFalse(res["freezed"])

            # Verify holiday mapping
            day_15 = res["days"][14]
            self.assertEqual(day_15["date"], "2025-08-15")
            self.assertIn("Independence Day", day_15["status_label"])

    def test_04_get_monthly_attendance_record_graceful_error_handling(self):
        """Verify network error returns clean failure response instead of throwing."""
        with patch("requests.post", side_effect=Exception("Connection timed out")):
            res = self.service.get_monthly_attendance_record(
                month="September",
                year=2025,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )
            self.assertEqual(res["status"], 0)
            self.assertIsNotNone(res["error"])
            self.assertEqual(len(res["days"]), 0)

    def test_05_attendance_page_ui_rendering(self):
        """Verify AttendancePage renders header, statistics, and calendar grid."""
        page = AttendancePage(service=self.service)
        self.assertIsNotNone(page.month_combo)
        self.assertIsNotNone(page.year_combo)
        self.assertIsNotNone(page.calendar_grid)
        self.assertIsNotNone(page.present_val_label)
        self.assertIsNotNone(page.absent_val_label)

        # Apply sample data
        sample_data = {
            "response": 200,
            "status": 1,
            "month": "September",
            "year": 2025,
            "days": [
                {
                    "day_num": 1,
                    "date": "2025-09-01",
                    "day_name": "Mon",
                    "status_code": "P",
                    "status_label": "Present",
                    "status_badge": "P",
                    "color": "#16a34a",
                    "bg_color": "#dcfce7",
                    "is_today": False,
                },
                {
                    "day_num": 2,
                    "date": "2025-09-02",
                    "day_name": "Tue",
                    "status_code": "A",
                    "status_label": "Absent",
                    "status_badge": "A",
                    "color": "#dc2626",
                    "bg_color": "#fee2e2",
                    "is_today": False,
                }
            ],
            "summary": {
                "present": 1,
                "absent": 1,
                "week_off": 0,
                "leave": 0,
                "holiday": 0,
                "total_days": 2,
            },
            "freezed": True,
            "error": None,
        }

        page._apply_attendance_data(sample_data)
        self.assertEqual(page.present_val_label.text(), "1 Days")
        self.assertEqual(page.absent_val_label.text(), "1 Days")
        # In September 2025, there are 30 days rendered as day cards
        self.assertEqual(len(page._day_cards), 30)
        self.assertEqual(page._day_cards[0].num_label.text(), "01")
        self.assertIn("Present", page._day_cards[0].status_badge.text())
        self.assertEqual(page._day_cards[1].num_label.text(), "02")
        self.assertIn("Absent", page._day_cards[1].status_badge.text())

    def test_06_attendance_page_empty_and_error_states(self):
        """Verify AttendancePage handles empty and error states cleanly."""
        page = AttendancePage(service=self.service)

        # 1. Error state
        page._apply_attendance_data({"error": "Unable to reach server", "days": []})
        self.assertFalse(page.error_banner.isHidden())
        self.assertFalse(page.empty_state.isHidden())
        self.assertTrue(page.calendar_grid_container.isHidden())

        # 2. Empty state (no error)
        page._apply_attendance_data({"error": None, "days": [], "summary": {}})
        self.assertTrue(page.error_banner.isHidden())
        self.assertFalse(page.empty_state.isHidden())
        self.assertTrue(page.calendar_grid_container.isHidden())

    def test_06b_month_navigation_and_today(self):
        """Verify Previous Month, Next Month, and Today navigation."""
        page = AttendancePage(service=self.service)
        page.month_combo.setCurrentText("September")
        page.year_combo.setCurrentText("2026")

        # Next Month -> October 2026
        page._on_next_month()
        self.assertEqual(page.month_combo.currentText(), "October")
        self.assertEqual(page.year_combo.currentText(), "2026")

        # Prev Month -> September 2026
        page._on_prev_month()
        self.assertEqual(page.month_combo.currentText(), "September")
        self.assertEqual(page.year_combo.currentText(), "2026")

        # Today button
        now = datetime.now()
        page.month_combo.setCurrentText("January")
        page.year_combo.setCurrentText("2020")
        page._on_today()
        self.assertEqual(page.year_combo.currentText(), str(now.year))
        self.assertEqual(page.month_combo.currentIndex(), now.month - 1)

    def test_07_dashboard_and_main_window_tab_replacement(self):
        """Verify Weekly Timeline is replaced with Attendance across dashboard and main window tabs."""
        mock_session = UserSession(
            username="testuser",
            role="employee",
            company_code="COMP123",
            api_key="testapikey111",
            device_token="dev_tok_1",
            full_name="Test User",
            user_type="employee",
            employee_id="EC-100",
            indo_code="EC-100",
            allow_user_device=True,
            allow_logout=True,
            tracking_permitted=True,
        )

        mock_act_svc = MagicMock()
        mock_act_svc.get_daily_summary.return_value = {"total_seconds": 3600, "idle_seconds": 300}
        mock_act_svc.get_weekly_timeline_data.return_value = []

        mock_set_svc = MagicMock()
        mock_set_svc.get_effective_setting.return_value = 300

        with patch("services.session_service.SessionService.current_user", mock_session):
            dash = DashboardPage(activity_service=mock_act_svc)
            self.assertIn("Attendance", dash.attendance_button.text())

            win = MainWindow()

            # Verify Tab 0 is Dashboard and Tab 1 is Attendance
            self.assertEqual(win.tabs.tabText(0), "Dashboard")
            self.assertEqual(win.tabs.tabText(1), "Attendance")

            # Verify switching to Attendance tab
            win.dashboard_page.attendance_button.click()
            self.assertEqual(win.tabs.currentWidget(), win.attendance_page)

    def test_08_extract_nested_dict_status_without_raw_json(self):
        """Verify present_days elements containing dictionaries with punchTime, lastUpdate etc. are parsed into clean status."""
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {
                        "status": "P",
                        "punchTime": "10:36:42",
                        "lastUpdate": "2025-09-01 19:00:00",
                        "punch_in": "10:36:42",
                        "punch_out": "18:45:10"
                    },
                    {
                        "attendance_status": "Absent",
                        "lastUpdate": "2025-09-02 00:00:00"
                    },
                    {
                        "status": "Week Off"
                    }
                ]
            },
            "freezed": "1"
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = mock_response_data
            mock_post.return_value = mock_resp

            res = self.service.get_monthly_attendance_record(
                month="September",
                year=2025,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            # Day 1 should be Present, NOT raw JSON string
            day_1 = res["days"][0]
            self.assertEqual(day_1["status_label"], "Present")
            self.assertNotIn("punchTime", day_1["status_label"])
            self.assertNotIn("{", day_1["status_label"])
            self.assertEqual(day_1["color"], "#16a34a") # Green
            self.assertIn("10:36:42", day_1["details"])

            # Day 2 should be Absent
            day_2 = res["days"][1]
            self.assertEqual(day_2["status_label"], "Absent")
            self.assertNotIn("lastUpdate", day_2["status_label"])
            self.assertEqual(day_2["color"], "#dc2626") # Red

            # Day 3 should be Week Off
            day_3 = res["days"][2]
            self.assertEqual(day_3["status_label"], "Week Off")
            self.assertEqual(day_3["color"], "#2563eb") # Blue


if __name__ == "__main__":
    unittest.main()
