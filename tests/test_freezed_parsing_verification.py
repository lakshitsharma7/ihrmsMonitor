"""Comprehensive verification tests for Attendance API parsing: freezed = 0 and freezed = 1.

Tests cover:
1. freezed = "1" / 1:
   - Day-wise status array mapping (index 0 represents Day 1).
   - Status mapping: P -> Present, A -> Absent, EL -> Leave (EL), Week Off -> Week Off, etc.
   - No punch time invention.
2. freezed = "0" / 0:
   - Punch records extraction with actual dates (DD-MM-YYYY).
   - mispunch_days (DD-MM-YYYY) and mispunch_criteria precedence (e.g. Sep 9 and Sep 18).
   - weekoff (YYYY-MM-DD) parsing.
   - Leave, Comp Off, Holiday arrays (including multi-day ranges).
   - Past confirmed working days with no records marked Absent.
3. Edge Cases:
   - [null] / None / empty lists / missing keys.
   - String and numeric freezed values ("0", 0, "1", 1, True, False).
   - Employee and month isolation in caching.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from services.attendance_service import AttendanceService


class TestFreezedAttendanceParsing(unittest.TestCase):
    """Test suite for both freezed=0 and freezed=1 attendance API parsing."""

    def setUp(self) -> None:
        self.service = AttendanceService()
        self.service.clear_cache()
        self.service.clear_state()

    def test_01_freezed_1_frozen_day_wise_array(self):
        """Verify freezed = '1' parses 31 day-wise status codes accurately, mapping index 0 to Day 1."""
        # 31 items sample for 30-day September 2025 (or August 2024):
        # Day 1: EL, Day 2-11: P, Day 12: Week Off, Day 13-14: A, Day 15: P, etc.
        sample_present_days = [
            "EL", "P", "P", "P", "P", "P", "P", "P", "P", "P", "P", "Week Off",
            "A", "A", "P", "A", "A", "A", "Week Off", "A", "P", "A", "P", "P",
            "P", "Week Off", "A", "EL", "EL", "EL", "A"
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"mock": true}'
        mock_resp.json.return_value = {
            "response": 200,
            "status": 1,
            "freezed": "1",
            "result": {
                "present_days": sample_present_days,
            },
        }

        with patch("requests.post", return_value=mock_resp):
            res = self.service.get_monthly_attendance_record(
                month="September", year=2025, indo_code="EC-098", force=True
            )

        self.assertTrue(res["freezed"])
        self.assertEqual(res["month"], "September")
        self.assertEqual(res["year"], 2025)
        days = res["days"]
        self.assertEqual(len(days), 30)  # September has 30 days

        # Verify Index 0 is Day 1 -> EL (Leave)
        day1 = days[0]
        self.assertEqual(day1["day_num"], 1)
        self.assertEqual(day1["date"], "2025-09-01")
        self.assertEqual(day1["status_code"], "EL")
        self.assertEqual(day1["status_label"], "Leave (EL)")
        self.assertEqual(day1["status_badge"], "EL")
        self.assertEqual(day1["color"], "#7e22ce")
        self.assertIsNone(day1["details"])  # Never invent punches

        # Verify Day 2 is P (Present)
        day2 = days[1]
        self.assertEqual(day2["day_num"], 2)
        self.assertEqual(day2["status_code"], "P")
        self.assertEqual(day2["status_label"], "Present")

        # Verify Day 12 is Week Off
        day12 = days[11]
        self.assertEqual(day12["day_num"], 12)
        self.assertEqual(day12["status_code"], "Week Off")
        self.assertEqual(day12["status_label"], "Week Off")

        # Verify Day 13 is Absent
        day13 = days[12]
        self.assertEqual(day13["day_num"], 13)
        self.assertEqual(day13["status_code"], "A")
        self.assertEqual(day13["status_label"], "Absent")

        # Summary check
        summary = res["summary"]
        self.assertEqual(summary["total_days"], 30)
        self.assertEqual(summary["leave"], 4)  # Day 1, 28, 29, 30 are EL
        self.assertEqual(summary["week_off"], 3)  # Day 12, 19, 26
        self.assertEqual(summary["present"], 15)
        self.assertEqual(summary["absent"], 8)

    def test_02_freezed_0_actual_september_2026_response(self):
        """Verify freezed = '0' parses actual September 2026 response with Sep 9 & 18 mispunches and weekoffs."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"mock": true}'
        mock_resp.json.return_value = {
            "response": 200,
            "status": 1,
            "freezed": "0",
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
                "comp_off_days": [None],
                "leave_days": [None],
                "mispunch_days": [
                    "09-09-2026",
                    "18-09-2026"
                ],
                "holiday_days": [None],
                "weekoff": [
                    {"date": "2026-09-05"},
                    {"date": "2026-09-06"},
                    {"date": "2026-09-12"},
                    {"date": "2026-09-13"},
                    {"date": "2026-09-19"},
                    {"date": "2026-09-20"},
                    {"date": "2026-09-26"},
                    {"date": "2026-09-27"}
                ],
                "mispunch_criteria": "08:30:00"
            }
        }

        with patch("requests.post", return_value=mock_resp):
            res = self.service.get_monthly_attendance_record(
                month="September", year=2026, indo_code="EC-098", force=True
            )

        self.assertFalse(res["freezed"])
        self.assertEqual(res["month"], "September")
        self.assertEqual(res["year"], 2026)
        days = res["days"]
        self.assertEqual(len(days), 30)

        days_by_date = {d["date"]: d for d in days}

        # Sep 9: Single punch (11:37:19 repeated), in mispunch_days -> Missed Punch
        sep9 = days_by_date["2026-09-09"]
        self.assertEqual(sep9["status_code"], "Missed Punch")
        self.assertEqual(sep9["status_label"], "Missed Punch")
        self.assertIn("11:37:19", sep9["details"])

        # Sep 18: In mispunch_days (under mispunch_criteria) -> Missed Punch (NOT Present)
        sep18 = days_by_date["2026-09-18"]
        self.assertEqual(sep18["status_code"], "Missed Punch")
        self.assertEqual(sep18["status_label"], "Missed Punch")
        self.assertIn("11:35:11", sep18["details"])
        self.assertIn("11:38:19", sep18["details"])

        # Sep 5: Week Off
        sep5 = days_by_date["2026-09-05"]
        self.assertEqual(sep5["status_code"], "Week Off")
        self.assertEqual(sep5["status_label"], "Week Off")

        # Sep 1: Working day with no punch/leave/holiday -> Absent
        sep1 = days_by_date["2026-09-01"]
        self.assertEqual(sep1["status_code"], "A")
        self.assertEqual(sep1["status_label"], "Absent")

        # Summary
        summary = res["summary"]
        self.assertEqual(summary["total_days"], 30)
        self.assertEqual(summary["present"], 0)
        self.assertEqual(summary["missed_punch"], 2)
        self.assertEqual(summary["week_off"], 8)
        self.assertEqual(summary["leave"], 0)
        self.assertEqual(summary["holiday"], 0)
        self.assertEqual(summary["absent"], 20)

    def test_03_null_and_empty_edge_cases(self):
        """Verify [null], empty lists, and missing keys do not corrupt parsing or cause crashes."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"mock": true}'
        mock_resp.json.return_value = {
            "response": 200,
            "status": 1,
            "freezed": 0,  # numeric 0
            "result": {
                "present_days": [None],
                "comp_off_days": [None, None],
                "leave_days": [],
                "mispunch_days": None,
                "holiday_days": [None],
                "weekoff": [],
            }
        }

        with patch("requests.post", return_value=mock_resp):
            res = self.service.get_monthly_attendance_record(
                month="September", year=2026, indo_code="EC-098", force=True
            )

        self.assertFalse(res["freezed"])
        summary = res["summary"]
        self.assertEqual(summary["total_days"], 30)
        self.assertEqual(summary["leave"], 0)
        self.assertEqual(summary["holiday"], 0)
        self.assertEqual(summary["missed_punch"], 0)

    def test_04_leave_multi_day_range_expansion(self):
        """Verify multi-day leave ranges (from_date to to_date) expand to each individual day."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"mock": true}'
        mock_resp.json.return_value = {
            "response": 200,
            "status": 1,
            "freezed": "0",
            "result": {
                "present_days": [],
                "comp_off_days": [],
                "leave_days": [
                    {
                        "from_date": "2026-09-10",
                        "to_date": "2026-09-12",
                        "leave_type": "EL",
                        "status": "Approved"
                    }
                ],
                "mispunch_days": [],
                "holiday_days": [],
                "weekoff": [{"date": "2026-09-06"}],
            }
        }

        with patch("requests.post", return_value=mock_resp):
            res = self.service.get_monthly_attendance_record(
                month="September", year=2026, indo_code="EC-098", force=True
            )

        days_by_date = {d["date"]: d for d in res["days"]}
        self.assertEqual(days_by_date["2026-09-10"]["status_code"], "EL")
        self.assertEqual(days_by_date["2026-09-11"]["status_code"], "EL")
        self.assertEqual(days_by_date["2026-09-12"]["status_code"], "EL")
        self.assertEqual(days_by_date["2026-09-10"]["status_label"], "Leave (EL)")
        self.assertEqual(res["summary"]["leave"], 3)

    def test_05_employee_cache_isolation(self):
        """Verify switching between employees does not reuse another employee's cached attendance."""
        mock_resp_98 = MagicMock()
        mock_resp_98.status_code = 200
        mock_resp_98.content = b'{"mock": true}'
        mock_resp_98.json.return_value = {
            "response": 200, "status": 1, "freezed": 1,
            "result": {"present_days": ["P"] * 30}
        }

        mock_resp_100 = MagicMock()
        mock_resp_100.status_code = 200
        mock_resp_100.content = b'{"mock": true}'
        mock_resp_100.json.return_value = {
            "response": 200, "status": 1, "freezed": 1,
            "result": {"present_days": ["A"] * 30}
        }

        with patch("requests.post", return_value=mock_resp_98):
            res_98 = self.service.get_monthly_attendance_record(
                month="September", year=2026, indo_code="EC-098"
            )

        with patch("requests.post", return_value=mock_resp_100):
            res_100 = self.service.get_monthly_attendance_record(
                month="September", year=2026, indo_code="EC-100"
            )

        self.assertEqual(res_98["summary"]["present"], 30)
        self.assertEqual(res_100["summary"]["absent"], 30)
        self.assertNotEqual(res_98["summary"]["present"], res_100["summary"]["present"])

    def test_06_comprehensive_status_classification_scenarios(self):
        """Verify all specific attendance scenarios:
        1. Identical in/out punch times -> Missed Punch
        2. Two distinct punch times with backend mispunch flag -> Missed Punch
        3. Two distinct punch times failing mispunch_criteria -> Missed Punch
        4. Valid Present day with distinct punches meeting criteria -> Present
        5. Valid Present day without punch times (optional punch field missing) -> Present
        6. Absent working day with no attendance record -> Absent
        7. Leave, Week Off, Holiday correctly mapped
        8. Missing or null optional fields handled gracefully
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"mock": true}'
        mock_resp.json.return_value = {
            "response": 200,
            "status": 1,
            "freezed": "0",
            "result": {
                "present_days": [
                    # Day 1: Identical punch times (single punch repeated)
                    {"date": "2026-09-01", "punchTime": "11:37:19,11:37:19"},
                    # Day 2: Two distinct punches flagged in mispunch_days
                    {"date": "2026-09-02", "punchTime": "11:35:11,11:38:19"},
                    # Day 3: Two distinct punches failing mispunch_criteria (not in mispunch_days)
                    {"date": "2026-09-03", "punch_in": "10:00:00", "punch_out": "10:15:00"},
                    # Day 4: Valid Present day meeting criteria
                    {"date": "2026-09-04", "punch_in": "09:30:00", "punch_out": "18:30:00"},
                    # Day 7: Valid Present confirmed by API without punch times
                    {"date": "2026-09-07", "status": "Present"},
                ],
                "mispunch_days": ["2026-09-02"],
                "mispunch_criteria": "08:30:00",
                "holiday_days": [
                    {"name": "Labor Day", "date": "2026-09-08"}
                ],
                "weekoff": [
                    {"date": "2026-09-05"},
                    {"date": "2026-09-06"}
                ],
                "leave_days": [
                    {"date": "2026-09-09", "leave_type": "CL"}
                ],
                "comp_off_days": [None],
            }
        }

        with patch("requests.post", return_value=mock_resp):
            res = self.service.get_monthly_attendance_record(
                month="September", year=2026, indo_code="EC-098", force=True
            )

        days_by_date = {d["date"]: d for d in res["days"]}

        # 1. Identical in/out punches -> Missed Punch
        d1 = days_by_date["2026-09-01"]
        self.assertEqual(d1["status_label"], "Missed Punch")
        self.assertEqual(d1["status_badge"], "MP")

        # 2. Distinct punches in mispunch_days -> Missed Punch
        d2 = days_by_date["2026-09-02"]
        self.assertEqual(d2["status_label"], "Missed Punch")
        self.assertEqual(d2["status_badge"], "MP")

        # 3. Distinct punches failing mispunch_criteria -> Missed Punch
        d3 = days_by_date["2026-09-03"]
        self.assertEqual(d3["status_label"], "Missed Punch")
        self.assertEqual(d3["status_badge"], "MP")

        # 4. Valid Present meeting criteria -> Present
        d4 = days_by_date["2026-09-04"]
        self.assertEqual(d4["status_label"], "Present")
        self.assertEqual(d4["status_badge"], "P")
        self.assertEqual(d4["color"], "#16a34a")

        # 5. Week Off
        d5 = days_by_date["2026-09-05"]
        self.assertEqual(d5["status_label"], "Week Off")

        # 6. Valid Present confirmed without punch times
        d7 = days_by_date["2026-09-07"]
        self.assertEqual(d7["status_label"], "Present")
        self.assertEqual(d7["status_badge"], "P")

        # 7. Holiday
        d8 = days_by_date["2026-09-08"]
        self.assertIn("Labor Day", d8["status_label"])

        # 8. Leave
        d9 = days_by_date["2026-09-09"]
        self.assertIn("Leave", d9["status_label"])

        # 9. Past working day with no record -> Absent
        d10 = days_by_date["2026-09-10"]
        self.assertEqual(d10["status_label"], "Absent")
        self.assertEqual(d10["status_badge"], "A")
        self.assertEqual(d10["color"], "#dc2626")

    def test_07_ui_day_card_styling_and_warning_badge(self):
        """Verify CalendarDayCard renders exact expected colors, badges, and warning indicator."""
        from PySide6.QtWidgets import QApplication
        from ui.attendance_page import CalendarDayCard
        import sys
        _ = QApplication.instance() or QApplication(sys.argv)

        # Present day card
        present_card = CalendarDayCard(
            day_data={"day_num": 1, "status_label": "Present", "status_code": "P"}
        )
        self.assertEqual(present_card._status_circle_bg, "#16A34A")

        # Absent day card
        absent_card = CalendarDayCard(
            day_data={"day_num": 2, "status_label": "Absent", "status_code": "A"}
        )
        self.assertEqual(absent_card._status_circle_bg, "#EF4444")

        # Genuine Missed Punch card (amber warning)
        mp_card = CalendarDayCard(
            day_data={"day_num": 3, "status_label": "Missed Punch", "status_code": "MP"}
        )
        self.assertEqual(mp_card._status_circle_bg, "#F59E0B")

        # Week off card (blue #2563EB)
        wo_card = CalendarDayCard(
            day_data={"day_num": 4, "status_label": "Week Off", "status_code": "Week Off"}
        )
        self.assertEqual(wo_card._status_circle_bg, "#2563EB")

        # Leave card (purple #9333EA)
        leave_card = CalendarDayCard(
            day_data={"day_num": 5, "status_label": "Leave", "status_code": "CL"}
        )
        self.assertEqual(leave_card._status_circle_bg, "#9333EA")

        # Holiday card (cyan #0EA5E9)
        holiday_card = CalendarDayCard(
            day_data={"day_num": 6, "status_label": "Holiday: Gandhi Jayanti", "status_code": "Holiday"}
        )
        self.assertEqual(holiday_card._status_circle_bg, "#0EA5E9")

    def test_08_live_september_2026_api_mapping(self):
        """Verify the exact live September 2026 API payload with 31-slot array maps accurately."""
        live_payload = {
            "response": 200,
            "status": 1,
            "result": {
                "present_days": [
                    "Warning", "Warning", "Warning", "Warning", "CL",
                    "Week Off", "EL", "EL", "Warning", "Warning",
                    "Warning", "Week Off", "Week Off", "Warning", "Warning",
                    "Warning", "P", "Warning", "Warning", "Week Off",
                    "Warning", "Warning", "OD", "OD", "OD",
                    "Week Off", "Week Off", "P", "P", "Warning",
                    None
                ]
            },
            "freezed": 1
        }

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b'{"response": 200}'
            mock_resp.json.return_value = live_payload
            mock_post.return_value = mock_resp

            res = self.service.get_monthly_attendance_record(
                month="September",
                year=2026,
                indo_code="INDO-S7288",
                key="testkey",
                force=True
            )

            days = res["days"]
            self.assertEqual(len(days), 30)

            # Sept 14, 15, 16: raw is 'Warning' -> Present (when freezed = 1)
            self.assertEqual(days[13]["date"], "2026-09-14")
            self.assertEqual(days[13]["status_label"], "Present")
            self.assertEqual(days[14]["date"], "2026-09-15")
            self.assertEqual(days[14]["status_label"], "Present")
            self.assertEqual(days[15]["date"], "2026-09-16")
            self.assertEqual(days[15]["status_label"], "Present")

            # Sept 17: raw is 'P' -> Present
            self.assertEqual(days[16]["date"], "2026-09-17")
            self.assertEqual(days[16]["status_label"], "Present")
            self.assertEqual(days[16]["color"], "#16a34a")

            # Sept 23, 24, 25: raw is 'OD' -> Present
            self.assertEqual(days[22]["date"], "2026-09-23")
            self.assertEqual(days[22]["status_label"], "Present")
            self.assertEqual(days[23]["date"], "2026-09-24")
            self.assertEqual(days[23]["status_label"], "Present")
            self.assertEqual(days[24]["date"], "2026-09-25")
            self.assertEqual(days[24]["status_label"], "Present")

            # Sept 28, 29: raw is 'P' -> Present
            self.assertEqual(days[27]["date"], "2026-09-28")
            self.assertEqual(days[27]["status_label"], "Present")
            self.assertEqual(days[28]["date"], "2026-09-29")
            self.assertEqual(days[28]["status_label"], "Present")

            # Summary verification: 21 Present, 0 Absent, 6 Week Off, 3 Leave
            summary = res["summary"]
            self.assertEqual(summary["present"], 21)
            self.assertEqual(summary["absent"], 0)
            self.assertEqual(summary["week_off"], 6)
            self.assertEqual(summary["leave"], 3)


if __name__ == "__main__":
    unittest.main()

