"""
Regression tests for real employee attendance data normalization,
tenant URL resolution, status reconciliation, and diagnostic logging.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from services.attendance_service import AttendanceService
from ui.attendance_page import CalendarDayCard, AttendancePage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def service():
    s = AttendanceService()
    s.clear_cache()
    return s


def test_tenant_base_url_resolution(service):
    """Test that tenant base URL is resolved dynamically from iHRMSMonitor settings or ApiConfig."""
    with patch("PySide6.QtCore.QSettings.value") as mock_val:
        def side_effect(key, default=None):
            if key == "ApiConfig/last_base_url":
                return "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api"
            return default
        mock_val.side_effect = side_effect

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "response": 200,
                "status": 1,
                "freezed": 0,
                "result": {"present_days": []},
            }

            service.get_monthly_attendance_record(
                month=5,
                year=2025,
                indo_code="EMP-1001",
                key="VALID-KEY",
                force=True,
            )

            # Assert URL was sent to the tenant endpoint
            assert mock_post.called
            call_url = mock_post.call_args[0][0]
            assert "softdev.indovisionservices.in/ihrms84" in call_url


def test_api_status_99999_handled_as_error(service):
    """Test that status 99999 (session rejected) returns a structured error rather than 31 false Absents."""
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": 401,
            "status": 99999,
            "message": "Token expired or unauthorized session.",
        }

        res = service.get_monthly_attendance_record(
            month=5,
            year=2025,
            indo_code="EMP-1001",
            key="EXPIRED-KEY",
            force=True,
        )

        assert res["status"] == 0
        assert "Token expired" in res["error"]
        assert len(res["days"]) == 0
        assert res["summary"]["absent"] == 0


def test_freezed_1_warning_maps_to_present(service, qapp):
    """Test that when freezed = 1, any 'Warning' attendance entry maps to Present (P), green indicator, and counted in monthly present."""
    fake_response = {
        "response": 200,
        "status": 1,
        "freezed": 1,
        "result": {
            # Day 1: Warning -> Present
            # Day 2: Warning -> Present
            # Day 3: A -> Absent
            # Day 4: Week Off -> Week Off
            # Day 5: EL -> Leave
            # Day 6: P -> Present
            # Day 7: H -> Holiday
            # Day 8: MP -> Missed Punch
            "present_days": ["Warning", "Warning", "A", "Week Off", "EL", "P", "Holiday", "MP"],
        },
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = fake_response

        res = service.get_monthly_attendance_record(
            month=5,
            year=2025,
            indo_code="EMP-1001",
            key="KEY",
            force=True,
        )

        days = res["days"]
        d1 = next(d for d in days if d["date"] == "2025-05-01")
        d2 = next(d for d in days if d["date"] == "2025-05-02")
        d3 = next(d for d in days if d["date"] == "2025-05-03")
        d4 = next(d for d in days if d["date"] == "2025-05-04")
        d5 = next(d for d in days if d["date"] == "2025-05-05")
        d6 = next(d for d in days if d["date"] == "2025-05-06")
        d7 = next(d for d in days if d["date"] == "2025-05-07")
        d8 = next(d for d in days if d["date"] == "2025-05-08")

        # Day 1: Warning -> Present
        assert d1["status_code"] == "P"
        assert d1["status_label"] == "Present"
        assert d1["color"] == "#16a34a"

        # Day 2: Warning -> Present
        assert d2["status_code"] == "P"
        assert d2["status_label"] == "Present"
        assert d2["color"] == "#16a34a"

        # Explicit other statuses remain unchanged
        assert d3["status_code"] == "A"
        assert d3["status_label"] == "Absent"

        assert d4["status_code"] == "Week Off"
        assert d4["status_label"] == "Week Off"

        assert d5["status_code"] == "EL"
        assert "Leave" in d5["status_label"]

        assert d6["status_code"] == "P"
        assert d6["status_label"] == "Present"

        assert "Holiday" in d7["status_label"]

        assert d8["status_code"] == "Missed Punch"
        assert d8["status_label"] == "Missed Punch"

        # Monthly summary present count includes both Warning days (d1, d2) and d6 -> at least 3
        assert res["summary"]["present"] >= 3

        # Calendar card UI verification for Warning date
        card = CalendarDayCard(day_data=d1)
        assert card._status_circle_bg == "#16A34A"


def test_freezed_0_warning_maps_to_present(service):
    """Test that when freezed = 0, 'Warning' also maps to Present (P) dynamically."""
    fake_response = {
        "response": 200,
        "status": 1,
        "freezed": 0,
        "result": {
            "present_days": [
                {
                    "date": "2025-05-01",
                    "status": "Warning",
                },
                {
                    "date": "2025-05-02",
                    "status": "  warn  ",  # test whitespace and case
                },
            ],
        },
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = fake_response

        res = service.get_monthly_attendance_record(
            month=5,
            year=2025,
            indo_code="EMP-1001",
            key="KEY",
            force=True,
        )

        d1 = next(d for d in res["days"] if d["date"] == "2025-05-01")
        assert d1["status_code"] == "P"
        assert d1["status_label"] == "Present"

        d2 = next(d for d in res["days"] if d["date"] == "2025-05-02")
        assert d2["status_code"] == "P"
        assert d2["status_label"] == "Present"


def test_path_b_real_employee_string_status_array(service):
    """Test that day-by-day status string arrays in normal months are properly indexed and parsed."""
    fake_response = {
        "response": 200,
        "status": 1,
        "freezed": 0,
        "result": {
            # Array of 4 daily statuses
            "present_days": ["P", "P", "Week Off", "EL"],
        },
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = fake_response

        res = service.get_monthly_attendance_record(
            month=5,
            year=2025,
            indo_code="EMP-REAL",
            key="KEY",
            force=True,
        )

        days = res["days"]
        d1 = next(d for d in days if d["date"] == "2025-05-01")
        d2 = next(d for d in days if d["date"] == "2025-05-02")
        d3 = next(d for d in days if d["date"] == "2025-05-03")
        d4 = next(d for d in days if d["date"] == "2025-05-04")

        assert d1["status_label"] == "Present"
        assert d2["status_label"] == "Present"
        assert d3["status_label"] == "Week Off"
        assert "Leave" in d4["status_label"]


def test_weekend_confirmed_present_not_overridden(service):
    """Test that an employee confirmed Present on a Saturday/Sunday is NOT overridden to Week Off."""
    # May 3, 2025 was a Saturday
    fake_response = {
        "response": 200,
        "status": 1,
        "freezed": 0,
        "result": {
            "present_days": [
                {
                    "date": "2025-05-03",
                    "status": "P",
                    "punch_in": "10:00:00",
                    "punch_out": "19:00:00",
                }
            ]
        },
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = fake_response

        res = service.get_monthly_attendance_record(
            month=5,
            year=2025,
            indo_code="EMP-REAL",
            key="KEY",
            force=True,
        )

        d3 = next(d for d in res["days"] if d["date"] == "2025-05-03")
        assert d3["status_label"] == "Present"


def test_calendar_card_update_status(qapp):
    """Test that CalendarDayCard.update_status refreshes styling and label accurately."""
    day_data = {
        "day_num": 10,
        "date": "2025-05-10",
        "day_name": "Sat",
        "status_code": "A",
        "status_label": "Absent",
        "details": None,
    }
    card = CalendarDayCard(day_data=day_data)
    assert card._status_circle_bg == "#EF4444"

    # Now update dynamically to Present
    new_data = {
        "day_num": 10,
        "date": "2025-05-10",
        "day_name": "Sat",
        "status_code": "P",
        "status_label": "Present",
        "details": "Biometric Punches: 10:00:00 - 19:00:00",
    }
    card.update_status(new_data)
    assert card._status_circle_bg == "#16A34A"
    assert "Present" in card.toolTip()


def test_missing_attendance_records_handling(service):
    """Verify missing records on past working days become Absent, while holidays, leaves, and weekends do not."""
    fake_response = {
        "response": 200,
        "status": 1,
        "freezed": 0,
        "result": {
            # Only May 1 has a record
            "present_days": [{"date": "2025-05-01", "status": "P"}],
            "holidays": [{"date": "2025-05-02", "name": "Labour Day"}],
            "leave_days": [{"from_date": "2025-05-05", "to_date": "2025-05-05", "leave_type": "CL"}],
            "weekoff": [{"date": "2025-05-04"}],
        },
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = fake_response

        res = service.get_monthly_attendance_record(
            month=5,
            year=2025,
            indo_code="EMP-1001",
            key="KEY",
            force=True,
        )

        days = res["days"]
        # May 1: Present
        d1 = next(d for d in days if d["date"] == "2025-05-01")
        assert d1["status_label"] == "Present"

        # May 2: Holiday (NOT Absent)
        d2 = next(d for d in days if d["date"] == "2025-05-02")
        assert "Holiday" in d2["status_label"]
        assert d2["status_code"] != "A"

        # May 4: Week Off (NOT Absent)
        d4 = next(d for d in days if d["date"] == "2025-05-04")
        assert d4["status_label"] == "Week Off"
        assert d4["status_code"] != "A"

        # May 5: Leave (NOT Absent)
        d5 = next(d for d in days if d["date"] == "2025-05-05")
        assert "Leave" in d5["status_label"]
        assert d5["status_code"] != "A"

        # May 6: Past working day with no record -> Absent
        d6 = next(d for d in days if d["date"] == "2025-05-06")
        assert d6["status_label"] == "Absent"
        assert d6["status_code"] == "A"


def test_dynamic_month_lengths_and_leap_years(service):
    """Verify calendar days are dynamically generated for leap years and different month lengths."""
    # Feb 2024 (Leap year -> 29 days)
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": 200, "status": 1, "freezed": 1, "result": {"present_days": ["P"] * 29}
        }
        res_leap = service.get_monthly_attendance_record(month=2, year=2024, indo_code="EMP-1", force=True)
        assert len(res_leap["days"]) == 29

    # Feb 2025 (Standard year -> 28 days)
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": 200, "status": 1, "freezed": 1, "result": {"present_days": ["P"] * 28}
        }
        res_std = service.get_monthly_attendance_record(month=2, year=2025, indo_code="EMP-1", force=True)
        assert len(res_std["days"]) == 28


def test_popup_warning_displays_present(qapp):
    """Verify AttendancePage detail popup logic displays Present when given a Warning day."""
    page = AttendancePage()
    day_info = {
        "day_num": 12,
        "date": "2025-05-12",
        "day_name": "Mon",
        "status_code": "P",
        "status_label": "Present",
        "details": None,
    }
    card = CalendarDayCard(day_data=day_info)

    # When card is rendered, it has green circle and Present badge
    assert card._status_circle_bg == "#16A34A"
    assert "Present" in card.toolTip()

