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
        """Verify Previous Month, removal of Next Month, and Today navigation with no future dates."""
        page = AttendancePage(service=self.service)
        now = datetime.now()

        # 1. Verify Next Month button does not exist, but Previous Month and Today exist
        self.assertFalse(hasattr(page, "next_month_btn"))
        self.assertTrue(hasattr(page, "prev_month_btn"))
        self.assertTrue(hasattr(page, "today_btn"))

        # 2. Verify year combo does not allow future years
        year_items = [int(page.year_combo.itemText(i)) for i in range(page.year_combo.count())]
        self.assertTrue(all(yr <= now.year for yr in year_items))
        self.assertEqual(max(year_items), now.year)

        # 3. Verify month combo for current year only allows months up to current month
        self.assertEqual(page.month_combo.count(), now.month)

        # 4. Navigate within past year (all 12 months available)
        past_year = now.year - 1
        page.year_combo.setCurrentText(str(past_year))
        page._on_year_changed()
        self.assertEqual(page.month_combo.count(), 12)

        page.month_combo.setCurrentText("February")
        page._on_prev_month()
        self.assertEqual(page.month_combo.currentText(), "January")
        self.assertEqual(page.year_combo.currentText(), str(past_year))

        # Test January -> December of previous year navigation
        page._on_prev_month()
        self.assertEqual(page.month_combo.currentText(), "December")
        self.assertEqual(page.year_combo.currentText(), str(past_year - 1))

        # 5. Today button jumps dynamically to current year and current month
        page._on_today()
        self.assertEqual(page.year_combo.currentText(), str(now.year))
        self.assertEqual(page.month_combo.currentIndex(), now.month - 1)

        # 6. Future state clamping protection in refresh()
        page.year_combo.addItem(str(now.year + 1))
        page.year_combo.setCurrentText(str(now.year + 1))
        page.refresh(async_mode=False)
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
            workpulse_permitted=True,
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

    def test_09_punch_time_overrides_absent_status(self):
        """Verify date with valid punch is marked Present even if API status says Absent."""
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {
                        "date": "2026-09-02",
                        "status": "Absent",
                        "punch_in": "11:35:11",
                        "punch_out": "11:38:19",
                    }
                ]
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
                month="September",
                year=2026,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            day_2 = res["days"][1]
            self.assertEqual(day_2["date"], "2026-09-02")
            self.assertEqual(day_2["status_label"], "Present")
            self.assertEqual(day_2["status_code"], "P")
            self.assertEqual(day_2["color"], "#16a34a") # Green
            self.assertIn("11:35:11 - 11:38:19", day_2["details"])

    def test_10_multiple_punch_formats_and_identical_punches(self):
        """Verify punch string with identical punch times formats as Missed Punch with single available punch."""
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {
                        "lastUpdate": "01-09-2026",
                        "punchTime": "11:37:19,11:37:19"
                    }
                ]
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
                month="September",
                year=2026,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            day_1 = res["days"][0]
            self.assertEqual(day_1["date"], "2026-09-01")
            self.assertEqual(day_1["status_label"], "Missed Punch")
            self.assertIn("Punch In: 11:37:19", day_1["details"])
            self.assertIn("Punch Out: Not Available", day_1["details"])

    def test_11_saturday_working_rules_1st_and_3rd_saturday(self):
        """Verify 1st and 3rd Saturdays are working days and non-working Saturdays are Week Offs."""
        # September 2026:
        # Day 5 (Sat) -> 1st Saturday -> Working Day (no record -> "-")
        # Day 12 (Sat) -> 2nd Saturday -> Week Off
        # Day 19 (Sat) -> 3rd Saturday -> Working Day (Present if both punches exist)
        # Day 26 (Sat) -> 4th Saturday -> Week Off
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {
                        "date": "2026-09-19",
                        "punch_in": "09:30:00",
                        "punch_out": "18:00:00"
                    }
                ],
                "weekoff": []
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
                month="September",
                year=2026,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            # Day 5 (1st Saturday, no record in API) -> Working day without punch -> Absent
            day_5 = res["days"][4]
            self.assertEqual(day_5["date"], "2026-09-05")
            self.assertEqual(day_5["status_label"], "Absent")

            # Day 12 (2nd Saturday, no record in API) -> Working day without punch -> Absent
            day_12 = res["days"][11]
            self.assertEqual(day_12["date"], "2026-09-12")
            self.assertEqual(day_12["status_label"], "Absent")

            # Day 19 (3rd Saturday, with both punches in API) -> Present
            day_19 = res["days"][18]
            self.assertEqual(day_19["date"], "2026-09-19")
            self.assertEqual(day_19["status_label"], "Present")
            self.assertEqual(day_19["details"], "Punch: 09:30:00 - 18:00:00")

            # Day 26 (4th Saturday, no record in API) -> Working day without punch -> Absent
            day_26 = res["days"][25]
            self.assertEqual(day_26["date"], "2026-09-26")
            self.assertEqual(day_26["status_label"], "Absent")

    def test_12_real_world_last_update_date_keyed_response(self):
        """Verify real API payload with lastUpdate keys (e.g. 09-09-2026 and 18-09-2026) maps correctly."""
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {
                        "punchTime": "11:37:19,11:37:19",
                        "lastUpdate": "09-09-2026"
                    },
                    {
                        "punchTime": "11:35:11,11:38:19",
                        "lastUpdate": "18-09-2026"
                    }
                ],
                "mispunch_days": [
                    "09-09-2026"
                ],
                "weekoff": [
                    {"date": "2026-09-05"},
                    {"date": "2026-09-06"},
                    {"date": "2026-09-12"},
                    {"date": "2026-09-13"},
                    {"date": "2026-09-19"},
                    {"date": "2026-09-20"},
                    {"date": "2026-09-26"},
                    {"date": "2026-09-27"}
                ]
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
                month="September",
                year=2026,
                indo_code="EC-098",
                key="testapikey111",
                force=True,
            )

            # Day 1 (01-09-2026) has no punch on a working day -> Absent
            day_1 = res["days"][0]
            self.assertEqual(day_1["date"], "2026-09-01")
            self.assertEqual(day_1["status_label"], "Absent")
            self.assertIsNone(day_1["details"])

            # Day 9 (09-09-2026 single punch) should be Missed Punch
            day_9 = res["days"][8]
            self.assertEqual(day_9["date"], "2026-09-09")
            self.assertEqual(day_9["status_label"], "Missed Punch")
            self.assertIn("Punch In: 11:37:19", day_9["details"])
            self.assertIn("Punch Out: Not Available", day_9["details"])

            # Day 18 (18-09-2026 both punches exist: 11:35:11 - 11:38:19) should be Present
            day_18 = res["days"][17]
            self.assertEqual(day_18["date"], "2026-09-18")
            self.assertEqual(day_18["status_label"], "Present")
            self.assertEqual(day_18["details"], "Punch: 11:35:11 - 11:38:19")

    def test_13_invalid_punch_sentinels_ignored(self):
        """Verify invalid punch sentinels like '00:00:00', 'null', '-' are not counted as punches."""
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {
                        "date": "2026-09-01",
                        "punch_in": "00:00:00",
                        "punch_out": "00:00:00",
                        "status": "Absent"
                    }
                ]
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
                month="September",
                year=2026,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            day_1 = res["days"][0]
            self.assertEqual(day_1["status_label"], "Absent")
            self.assertIsNone(day_1["details"])

    def test_15_calendar_day_card_full_status_styling(self):
        """Verify CalendarDayCard applies full-card status backgrounds for Present, Absent, Week Off, and Today."""
        from ui.attendance_page import CalendarDayCard

        # 1. Present Card -> Full Light Green background (#F0FDF4)
        present_card = CalendarDayCard(day_data={
            "day_num": 18,
            "day_name": "Fri",
            "date": "2026-09-18",
            "status_label": "Present",
            "status_code": "P",
            "details": "Punch: 11:35:11 - 11:38:19",
            "is_today": False,
        })
        self.assertIn("background-color: #F0FDF4", present_card.styleSheet())
        self.assertIn("border: 1px solid #86EFAC", present_card.styleSheet())

        # 2. Absent Card -> Full Light Red background (#FEF2F2)
        absent_card = CalendarDayCard(day_data={
            "day_num": 1,
            "day_name": "Tue",
            "date": "2026-09-01",
            "status_label": "Absent",
            "status_code": "A",
            "details": None,
            "is_today": False,
        })
        self.assertIn("background-color: #FEF2F2", absent_card.styleSheet())
        self.assertIn("border: 1px solid #FECACA", absent_card.styleSheet())

        # 3. Week Off Card -> Full Light Blue background (#EFF6FF)
        weekoff_card = CalendarDayCard(day_data={
            "day_num": 6,
            "day_name": "Sun",
            "date": "2026-09-06",
            "status_label": "Week Off",
            "status_code": "Week Off",
            "details": None,
            "is_today": False,
        })
        self.assertIn("background-color: #EFF6FF", weekoff_card.styleSheet())
        self.assertIn("border: 1px solid #BFDBFE", weekoff_card.styleSheet())

        # 4. Today + Present -> Green Card with Today 2px border and Today badge
        today_present_card = CalendarDayCard(day_data={
            "day_num": 19,
            "day_name": "Sat",
            "date": "2026-09-19",
            "status_label": "Present",
            "status_code": "P",
            "details": "Punch: 09:30:00 - 18:00:00",
            "is_today": True,
        })
        self.assertIn("background-color: #F0FDF4", today_present_card.styleSheet())
        self.assertIn("border: 2px solid #16A34A", today_present_card.styleSheet())

        # 5. Today + Absent -> Red Card with Today 2px border and Today badge
        today_absent_card = CalendarDayCard(day_data={
            "day_num": 19,
            "day_name": "Sat",
            "date": "2026-09-19",
            "status_label": "Absent",
            "status_code": "A",
            "details": None,
            "is_today": True,
        })
        self.assertIn("background-color: #FEF2F2", today_absent_card.styleSheet())
        self.assertIn("border: 2px solid #DC2626", today_absent_card.styleSheet())

        # 6. Unrecorded Day -> Neutral white card with empty status badge hidden
        unrecorded_card = CalendarDayCard(day_data={
            "day_num": 7,
            "day_name": "Wed",
            "date": "2026-10-07",
            "status_label": "",
            "status_code": "",
            "details": None,
            "is_today": False,
        })
        self.assertIn("background-color: #FFFFFF", unrecorded_card.styleSheet())
        self.assertIn("border: 1px solid #E2E8F0", unrecorded_card.styleSheet())
        self.assertFalse(unrecorded_card.status_badge.isVisible())

    def test_16_august_15_days_records_mapping(self):
        """Verify August with 15 non-contiguous attendance days and diverse date formats maps each day accurately."""
        # 15 days in August: 1, 2, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 18, 19
        mock_response_data = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {"date": "2025-08-01", "punch_in": "09:00:00", "punch_out": "18:00:00"},
                    {"lastUpdate": "02-08-2025", "punchTime": "09:05:00,18:05:00"},
                    {"date": "2025-08-04", "punch_in": "09:10:00", "punch_out": "18:10:00"},
                    {"attendance_date": "2025-08-05", "punch_in": "09:15:00"},
                    {"date": "2025-08-06", "punch_in": "09:20:00", "punch_out": "18:20:00"},
                    {"punch_date": "07-08-2025", "punch_in": "09:25:00"},
                    {"date": "2025-08-08", "punch_in": "09:30:00", "punch_out": "18:30:00"},
                    {"date": "2025-08-09", "punch_in": "09:35:00"},
                    {"date": "2025-08-11", "punch_in": "09:40:00", "punch_out": "18:40:00"},
                    {"date": "2025-08-12", "punch_in": "09:45:00"},
                    {"date": "2025-08-13", "punch_in": "09:50:00", "punch_out": "18:50:00"},
                    {"date": "2025-08-14", "punch_in": "09:55:00"},
                    {"date": "15-Aug-2025", "status": "Holiday", "name": "Independence Day"},
                    {"date": "2025-08-18", "punch_in": "10:00:00", "punch_out": "19:00:00"},
                    {"date": "2025-08-19", "punch_in": "10:05:00"},
                ],
                "holiday_days": [
                    {"name": "Independence Day", "date": "2025-08-15"}
                ],
                "weekoff": [
                    {"date": "2025-08-03"},
                    {"date": "2025-08-10"},
                    {"date": "2025-08-17"},
                    {"date": "2025-08-24"},
                    {"date": "2025-08-31"},
                ]
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

            self.assertEqual(len(res["days"]), 31)
            # Day 1: Aug 1 (both punches) -> Present
            self.assertEqual(res["days"][0]["date"], "2025-08-01")
            self.assertEqual(res["days"][0]["status_label"], "Present")
            self.assertEqual(res["days"][0]["details"], "Punch: 09:00:00 - 18:00:00")

            # Day 3: Aug 3 (Sunday - Week Off)
            self.assertEqual(res["days"][2]["date"], "2025-08-03")
            self.assertEqual(res["days"][2]["status_label"], "Week Off")

            # Day 4: Aug 4 (both punches) -> Present
            self.assertEqual(res["days"][3]["date"], "2025-08-04")
            self.assertEqual(res["days"][3]["status_label"], "Present")

            # Day 5: Aug 5 (single punch) -> Missed Punch
            self.assertEqual(res["days"][4]["date"], "2025-08-05")
            self.assertEqual(res["days"][4]["status_label"], "Missed Punch")

            # Day 15: Aug 15 (Holiday)
            self.assertEqual(res["days"][14]["date"], "2025-08-15")
            self.assertIn("Independence Day", res["days"][14]["status_label"])

            # Day 19: Aug 19 (single punch) -> Missed Punch
            self.assertEqual(res["days"][18]["date"], "2025-08-19")
            self.assertEqual(res["days"][18]["status_label"], "Missed Punch")

            # UI Population verification
            page = AttendancePage(service=self.service)
            page._apply_attendance_data(res)
            self.assertEqual(len(page._day_cards), 31)

    def test_17_multi_year_same_month_isolation(self):
        """Verify August 2025 and August 2026 data are completely isolated and not mixed."""
        mock_aug_2025 = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [{"date": "2025-08-01", "punch_in": "09:00:00", "punch_out": "18:00:00"}]
            }
        }
        mock_aug_2026 = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [{"date": "2026-08-01", "punch_in": "10:30:00", "punch_out": "19:30:00"}]
            }
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.side_effect = [mock_aug_2025, mock_aug_2026]
            mock_post.return_value = mock_resp

            res_2025 = self.service.get_monthly_attendance_record(month="August", year=2025, force=True)
            res_2026 = self.service.get_monthly_attendance_record(month="August", year=2026, force=True)

            self.assertEqual(res_2025["year"], 2025)
            self.assertEqual(res_2026["year"], 2026)
            self.assertIn("09:00:00 - 18:00:00", res_2025["days"][0]["details"])
            self.assertIn("10:30:00 - 19:30:00", res_2026["days"][0]["details"])

    def test_18_flexible_month_inputs(self):
        """Verify resolution of abbreviations, string numbers, and 0-indexed month inputs."""
        mock_response = {"response": 200, "status": 1, "result": {"present_days": []}}
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = mock_response
            mock_post.return_value = mock_resp

            # Abbreviation "Aug"
            res = self.service.get_monthly_attendance_record(month="Aug", year=2025, force=True)
            self.assertEqual(res["month"], "August")

            # Numeric "08"
            res = self.service.get_monthly_attendance_record(month="08", year=2025, force=True)
            self.assertEqual(res["month"], "August")

            # JS 0-indexed 0 -> January
            res = self.service.get_monthly_attendance_record(month=0, year=2025, force=True)
            self.assertEqual(res["month"], "January")

    def test_19_dict_response_structures(self):
        """Verify API response with dictionary collections for present_days and holidays."""
        mock_dict_response = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": {
                    "2025-08-01": {"punch_in": "09:00:00", "punch_out": "18:00:00"},
                    "2025-08-02": {"punch_in": "09:30:00"}
                },
                "holiday_days": {
                    "2025-08-15": {"name": "Independence Day"}
                }
            }
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = mock_dict_response
            mock_post.return_value = mock_resp

            res = self.service.get_monthly_attendance_record(month="August", year=2025, force=True)
            self.assertEqual(res["days"][0]["status_label"], "Present")
            self.assertEqual(res["days"][1]["status_label"], "Missed Punch")
            self.assertIn("Independence Day", res["days"][14]["status_label"])

    def test_20_may_2026_screenshot_reference_comparison(self):
        """Verify May 2026 reference scenario matches reference counts and day classifications."""
        mock_may_response = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {"date": "2026-05-04", "punchTime": "12:19:25,12:19:25"},
                    {"date": "2026-05-05", "punchTime": "10:41:33,10:41:33"},
                    {"date": "2026-05-06", "punchTime": "11:08:24 - 11:25:00"},
                    {"date": "2026-05-14", "punchTime": "11:45:46,11:45:46"},
                    {"date": "2026-05-25", "punchTime": "10:00:00,10:00:00"},
                    {"date": "2026-05-27", "punchTime": "10:15:00,10:15:00"},
                    {"date": "2026-05-28", "punchTime": "10:20:00,10:20:00"},
                ],
                "mispunch_days": [
                    "2026-05-04", "2026-05-05", "2026-05-14",
                    "2026-05-25", "2026-05-27", "2026-05-28"
                ],
                "leave_days": [
                    {"date": "2026-05-21", "leave_type": "Casual Leave"}
                ],
                "weekoff": [
                    {"date": "2026-05-02"}, {"date": "2026-05-03"},
                    {"date": "2026-05-09"}, {"date": "2026-05-10"},
                    {"date": "2026-05-16"}, {"date": "2026-05-17"},
                    {"date": "2026-05-23"}, {"date": "2026-05-24"},
                    {"date": "2026-05-30"}, {"date": "2026-05-31"}
                ]
            },
            "freezed": "0"
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = mock_may_response
            mock_post.return_value = mock_resp

            res = self.service.get_monthly_attendance_record(
                month="May",
                year=2026,
                indo_code="EC-098",
                key="testapikey111",
                force=True,
            )

            self.assertEqual(len(res["days"]), 31)

            # Check specific days:
            # May 2 (Sat): Week Off
            self.assertEqual(res["days"][1]["date"], "2026-05-02")
            self.assertEqual(res["days"][1]["status_label"], "Week Off")

            # May 3 (Sun): Week Off
            self.assertEqual(res["days"][2]["date"], "2026-05-03")
            self.assertEqual(res["days"][2]["status_label"], "Week Off")

            # May 4 (Mon): Missed Punch
            self.assertEqual(res["days"][3]["date"], "2026-05-04")
            self.assertEqual(res["days"][3]["status_label"], "Missed Punch")
            self.assertIn("Punch In: 12:19:25", res["days"][3]["details"])
            self.assertIn("Punch Out: Not Available", res["days"][3]["details"])

            # May 6 (Wed): Present (both punches exist)
            self.assertEqual(res["days"][5]["date"], "2026-05-06")
            self.assertEqual(res["days"][5]["status_label"], "Present")
            self.assertEqual(res["days"][5]["details"], "Punch: 11:08:24 - 11:25:00")

            # May 16 (Sat): Week Off
            self.assertEqual(res["days"][15]["date"], "2026-05-16")
            self.assertEqual(res["days"][15]["status_label"], "Week Off")

            # May 21 (Thu): Leave
            self.assertEqual(res["days"][20]["date"], "2026-05-21")
            self.assertIn("Leave", res["days"][20]["status_label"])

            # Summary counts check
            summary = res["summary"]
            self.assertEqual(summary["total_days"], 31)
            self.assertEqual(summary["week_off"], 10)
            self.assertEqual(summary["leave"], 1)
            self.assertEqual(summary["missed_punch"], 6)
            self.assertEqual(summary["present"], 1)

            # UI rendering check
            page = AttendancePage(service=self.service)
            page._apply_attendance_data(res)
            self.assertEqual(page.weekoff_val_label.text(), "10 Days")
            self.assertEqual(page.leave_val_label.text(), "1 Days")
            self.assertEqual(page.missed_punch_val_label.text(), "6 Days")
            self.assertEqual(page.present_val_label.text(), "1 Days")

    def test_21_august_september_october_2026_required_logic(self):
        """Verify dynamic loading and exact required status logic across August, September, and October 2026."""
        # 1. October 2026: Present with both punches, Missed Punch with only in, Missed Punch with only out, Holiday Gandhi Jayanti & Dussehra
        oct_response = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {"date": "2026-10-01", "punch_in": "09:45:55", "punch_out": "18:31:16"},
                    {"date": "2026-10-03", "punch_in": "09:45:55"},
                    {"date": "2026-10-05", "punch_out": "18:31:16"},
                    {"date": "2026-10-06", "status": "Absent"},
                ],
                "holiday_days": [
                    {"name": "Gandhi Jayanti", "date": "2026-10-02"},
                    {"name": "Dussehra", "date": "2026-10-20"},
                ],
                "leave_days": [
                    {"date": "2026-10-07", "leave_type": "CL"},
                    {"date": "2026-10-08", "leave_type": "EL"},
                ],
                "weekoff": [
                    {"date": "2026-10-04"},
                    {"date": "2026-10-11"},
                ]
            }
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = oct_response
            mock_post.return_value = mock_resp

            res_oct = self.service.get_monthly_attendance_record(
                month="October",
                year=2026,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            # Oct 1: Present (Punch: 09:45:55 - 18:31:16)
            day_1 = res_oct["days"][0]
            self.assertEqual(day_1["status_label"], "Present")
            self.assertEqual(day_1["details"], "Punch: 09:45:55 - 18:31:16")

            # Oct 2: Holiday: Gandhi Jayanti
            day_2 = res_oct["days"][1]
            self.assertEqual(day_2["status_label"], "Holiday: Gandhi Jayanti")

            # Oct 3: Missed Punch (Punch In: 09:45:55, Punch Out: Not Available)
            day_3 = res_oct["days"][2]
            self.assertEqual(day_3["status_label"], "Missed Punch")
            self.assertIn("Punch In: 09:45:55", day_3["details"])
            self.assertIn("Punch Out: Not Available", day_3["details"])

            # Oct 4: Week Off
            day_4 = res_oct["days"][3]
            self.assertEqual(day_4["status_label"], "Week Off")

            # Oct 5: Missed Punch (Punch In: Not Available, Punch Out: 18:31:16)
            day_5 = res_oct["days"][4]
            self.assertEqual(day_5["status_label"], "Missed Punch")
            self.assertIn("Punch In: Not Available", day_5["details"])
            self.assertIn("Punch Out: 18:31:16", day_5["details"])

            # Oct 6: Absent (explicitly marked by API)
            day_6 = res_oct["days"][5]
            self.assertEqual(day_6["status_label"], "Absent")

            # Oct 7: Leave (CL)
            day_7 = res_oct["days"][6]
            self.assertEqual(day_7["status_label"], "Leave (CL)")

            # Oct 8: Leave (EL)
            day_8 = res_oct["days"][7]
            self.assertEqual(day_8["status_label"], "Leave (EL)")

            # Oct 20: Holiday: Dussehra
            day_20 = res_oct["days"][19]
            self.assertEqual(day_20["status_label"], "Holiday: Dussehra")

            # Oct 9: No API Record -> Empty status (not Absent)
            day_9 = res_oct["days"][8]
            self.assertEqual(day_9["status_label"], "")
            self.assertEqual(day_9["status_code"], "")

    def test_22_session_switch_cache_invalidation(self):
        """Verify user logout flushes attendance cache completely so new user loads fresh data."""
        mock_user1_res = {
            "response": 200, "status": 1,
            "result": {"present_days": [{"date": "2026-10-01", "punch_in": "09:00:00", "punch_out": "18:00:00"}]}
        }
        mock_user2_res = {
            "response": 200, "status": 1,
            "result": {"present_days": [{"date": "2026-10-01", "punch_in": "10:15:00", "punch_out": "19:15:00"}]}
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.side_effect = [mock_user1_res, mock_user2_res]
            mock_post.return_value = mock_resp

            # User 1 fetches October 2026
            u1_data = self.service.get_monthly_attendance_record(month="October", year=2026, indo_code="EC-001", force=True)
            self.assertIn("09:00:00 - 18:00:00", u1_data["days"][0]["details"])

            # Logout clears cache
            SessionService().logout()

            # User 2 fetches October 2026
            u2_data = self.service.get_monthly_attendance_record(month="October", year=2026, indo_code="EC-002", force=True)
            self.assertIn("10:15:00 - 19:15:00", u2_data["days"][0]["details"])

    def test_23_october_2026_working_days_no_punch_shows_absent_never_dash(self):
        """Verify October 2026 working days with no punches display Absent and never '—'."""
        oct_payload = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    # Day 1: Working day + Punch In + Punch Out -> Present
                    {"date": "2026-10-01", "punch_in": "09:30:00", "punch_out": "18:30:00"},
                    # Day 5: Working day + Punch In only -> Missed Punch
                    {"date": "2026-10-05", "punch_in": "09:40:00"},
                    # Day 6: Working day + Punch Out only -> Missed Punch
                    {"date": "2026-10-06", "punch_out": "18:45:00"},
                    # Days 07, 08, 09, 12, 13, 14 etc. have NO punches and NO special record
                ],
                "holiday_days": [
                    {"name": "Gandhi Jayanti", "date": "2026-10-02"},
                ],
                "leave_days": [
                    {"date": "2026-10-15", "leave_type": "CL"},
                ],
                "weekoff": [
                    {"date": "2026-10-04"},
                    {"date": "2026-10-10"},
                    {"date": "2026-10-11"},
                    {"date": "2026-10-18"},
                    {"date": "2026-10-24"},
                    {"date": "2026-10-25"},
                ]
            }
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = oct_payload
            mock_post.return_value = mock_resp

            res = self.service.get_monthly_attendance_record(
                month="October",
                year=2026,
                indo_code="EC-100",
                key="testapikey111",
                force=True,
            )

            # 1. Oct 1 (Thu) - Working day + Punch In + Punch Out -> Present
            day_1 = res["days"][0]
            self.assertEqual(day_1["date"], "2026-10-01")
            self.assertEqual(day_1["status_label"], "Present")
            self.assertEqual(day_1["details"], "Punch: 09:30:00 - 18:30:00")

            # 2. Oct 2 (Fri) - Holiday -> Gandhi Jayanti
            day_2 = res["days"][1]
            self.assertEqual(day_2["date"], "2026-10-02")
            self.assertEqual(day_2["status_label"], "Holiday: Gandhi Jayanti")

            # 3. Oct 4 (Sun) - Week Off -> Week Off
            day_4 = res["days"][3]
            self.assertEqual(day_4["date"], "2026-10-04")
            self.assertEqual(day_4["status_label"], "Week Off")

            # 4. Oct 5 (Mon) - Working day + Punch In only -> Missed Punch
            day_5 = res["days"][4]
            self.assertEqual(day_5["date"], "2026-10-05")
            self.assertEqual(day_5["status_label"], "Missed Punch")
            self.assertIn("Punch In: 09:40:00", day_5["details"])
            self.assertIn("Punch Out: Not Available", day_5["details"])

            # 5. Oct 6 (Tue) - Working day + Punch Out only -> Missed Punch
            day_6 = res["days"][5]
            self.assertEqual(day_6["date"], "2026-10-06")
            self.assertEqual(day_6["status_label"], "Missed Punch")
            self.assertIn("Punch In: Not Available", day_6["details"])
            self.assertIn("Punch Out: 18:45:00", day_6["details"])

            # 6. Oct 7 (Wed) - No API record -> Empty status (not Absent)
            day_7 = res["days"][6]
            self.assertEqual(day_7["date"], "2026-10-07")
            self.assertEqual(day_7["status_label"], "")
            self.assertEqual(day_7["status_code"], "")

            # 7. Oct 8 (Thu) - No API record -> Empty status (not Absent)
            day_8 = res["days"][7]
            self.assertEqual(day_8["date"], "2026-10-08")
            self.assertEqual(day_8["status_label"], "")
            self.assertEqual(day_8["status_code"], "")

            # 8. Oct 9 (Fri) - No API record -> Empty status (not Absent)
            day_9 = res["days"][8]
            self.assertEqual(day_9["date"], "2026-10-09")
            self.assertEqual(day_9["status_label"], "")
            self.assertEqual(day_9["status_code"], "")

            # 9. Oct 15 (Thu) - Leave -> Leave (CL)
            day_15 = res["days"][14]
            self.assertEqual(day_15["date"], "2026-10-15")
            self.assertEqual(day_15["status_label"], "Leave (CL)")

            # 10. UI Calendar Rendering verification:
            page = AttendancePage(service=self.service)
            page._apply_attendance_data(res)
            # Ensure unrecorded future day cards have hidden status badge and empty content
            day_7_card = page._day_cards[6]
            self.assertFalse(day_7_card.status_badge.isVisible())

            day_8_card = page._day_cards[7]
            self.assertFalse(day_8_card.status_badge.isVisible())

    def test_24_july_2026_working_days_no_punch_shows_absent(self):
        """Verify July 2026 actual API structure: 1 Present day, 8 Week Offs, 1 Leave, 22 Absent working days."""
        july_payload = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    {
                        "punchTime": "12:45:57,13:05:07",
                        "lastUpdate": "30-07-2026"
                    }
                ],
                "leave_days": [
                    {
                        "from_date": "2026-07-19 16:00:00",
                        "to_date": "2026-07-19 16:00:00",
                        "leave_type": "Leave"
                    }
                ],
                "weekoff": [
                    {"date": "2026-07-04"},
                    {"date": "2026-07-05"},
                    {"date": "2026-07-11"},
                    {"date": "2026-07-12"},
                    {"date": "2026-07-18"},
                    {"date": "2026-07-19"},
                    {"date": "2026-07-25"},
                    {"date": "2026-07-26"},
                ]
            },
            "freezed": "0"
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = july_payload
            mock_post.return_value = mock_resp

            res = self.service.get_monthly_attendance_record(
                month="July",
                year=2026,
                indo_code="EC-098",
                key="testapikey111",
                force=True,
            )

            self.assertEqual(len(res["days"]), 31)

            # July 30: Present + Punch times
            day_30 = res["days"][29]
            self.assertEqual(day_30["date"], "2026-07-30")
            self.assertEqual(day_30["status_label"], "Present")
            self.assertEqual(day_30["details"], "Punch: 12:45:57 - 13:05:07")

            # July 4: Week Off
            day_4 = res["days"][3]
            self.assertEqual(day_4["date"], "2026-07-04")
            self.assertEqual(day_4["status_label"], "Week Off")

            # July 19: Leave or Week Off
            day_19 = res["days"][18]
            self.assertEqual(day_19["date"], "2026-07-19")
            self.assertIn(day_19["status_label"], ("Week Off", "Leave"))

            # July 1: Working day with NO punch -> MUST show "Absent"
            day_1 = res["days"][0]
            self.assertEqual(day_1["date"], "2026-07-01")
            self.assertEqual(day_1["status_label"], "Absent")
            self.assertEqual(day_1["status_code"], "A")
            self.assertEqual(day_1["status_badge"], "A")
            self.assertEqual(day_1["color"], "#dc2626")

            # Summary verification
            summary = res["summary"]
            self.assertEqual(summary["total_days"], 31)
            self.assertEqual(summary["present"], 1)
            self.assertEqual(summary["absent"], 22)


if __name__ == "__main__":
    unittest.main()

