"""
Unit tests for DD-MM-YYYY date format standardization and iHRMS branding replacement.
"""

from datetime import date, datetime
import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QLabel, QDialog

from utils.date_utils import format_date_display, parse_date_safe, DISPLAY_DATE_FORMAT
from ui.attendance_page import AttendancePage, CalendarDayCard
from ui.main_window import MainWindow
from services.hrms_portal_service import HrmsPortalService
from services.activity_service import ActivityService
from database.database import get_session


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_format_date_display_standard_rules():
    """Verify format_date_display strictly formats to DD-MM-YYYY across types."""
    assert format_date_display("2026-09-09") == "09-09-2026"
    assert format_date_display("2026-10-13") == "13-10-2026"
    assert format_date_display("2026-09-09 (Wed)") == "09-09-2026 (Wed)"
    assert format_date_display("2026-10-13, Tue") == "13-10-2026, Tue"
    assert format_date_display(date(2026, 10, 13)) == "13-10-2026"
    assert format_date_display(datetime(2026, 9, 9, 14, 15, 30)) == "09-09-2026"
    assert format_date_display("09-09-2026") == "09-09-2026"
    assert format_date_display(None) == ""
    assert format_date_display("") == ""
    assert format_date_display("-", default="-") == "-"


def test_calendar_day_card_tooltip_date_format(qapp):
    """CalendarDayCard tooltip must format date as DD-MM-YYYY (e.g. 13-10-2026)."""
    card = CalendarDayCard(
        day_data={
            "day_num": 13,
            "date": "2026-10-13",
            "day_name": "Tue",
            "status_code": "P",
            "status_label": "Present",
        }
    )
    tooltip = card.toolTip()
    assert "Date: 13-10-2026 (Tue)" in tooltip
    assert "2026-10-13" not in tooltip


def test_attendance_detail_dialog_date_and_branding(qapp, monkeypatch):
    """Attendance detail dialog must display DD-MM-YYYY date and iHRMS Portal branding."""
    page = AttendancePage()
    day_info = {
        "day_num": 13,
        "date": "2026-10-13",
        "day_name": "Tue",
        "status_code": "A",
        "status_label": "Absent",
        "details": "Biometric Punches: 09:30 - 09:30",
    }

    captured_dialog = None

    def mock_exec(self):
        nonlocal captured_dialog
        captured_dialog = self
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", mock_exec)
    page._show_day_detail(day_info)

    assert captured_dialog is not None
    assert captured_dialog.windowTitle() == "Attendance — 13-10-2026"

    labels = captured_dialog.findChildren(QLabel)
    title_label = next((l for l in labels if "Attendance: 13-10-2026 (Tue)" in l.text()), None)
    assert title_label is not None, "Title label should display date in DD-MM-YYYY format"

    # Check regularization note branding
    note_label = next((l for l in labels if "regularization request" in l.text()), None)
    assert note_label is not None
    assert "iHRMS Portal" in note_label.text()
    assert not re_has_unprefixed_hrms(note_label.text())

    # Check portal button branding
    buttons = captured_dialog.findChildren(QPushButton)
    portal_btn = next((b for b in buttons if "Portal" in b.text()), None)
    assert portal_btn is not None
    assert "iHRMS Portal" in portal_btn.text()


def test_main_window_ihrms_portal_button(qapp, monkeypatch):
    """Main window header portal button must display ' iHRMS' and 'Open iHRMS Web Portal'."""
    # Prevent background timer and thread triggers during test
    monkeypatch.setattr(MainWindow, "_check_for_updates", lambda self, manual=False: None)
    win = MainWindow()
    assert win.hrms_button.text().strip() == "iHRMS"
    assert "iHRMS Web Portal" in win.hrms_button.toolTip()


def test_hrms_portal_service_html_branding():
    """HTML redirect page in HrmsPortalService must display iHRMS branding."""
    svc = HrmsPortalService()
    html = svc.generate_autologin_html(
        portal_url="https://ihrms.indovisionservices.in",
        username="EC-098",
    )
    assert "<title>iHRMS Portal - Connecting...</title>" in html
    assert "<h2>Connecting to iHRMS Portal</h2>" in html


def test_activity_service_weekly_timeline_date_format():
    """Weekly timeline breakdown rows must use DD-MM-YYYY date format."""
    svc = ActivityService(get_session)
    week_data = svc.get_weekly_timeline_data()
    assert len(week_data) == 7
    for day in week_data:
        date_str = day["date_str"]
        # Format should be DD-MM-YYYY
        parts = date_str.split("-")
        assert len(parts) == 3, f"Expected DD-MM-YYYY, got {date_str}"
        assert len(parts[0]) == 2 and len(parts[1]) == 2 and len(parts[2]) == 4
        assert date_str in day["display_line"]


def re_has_unprefixed_hrms(text: str) -> bool:
    import re
    return bool(re.search(r"(?<![iI])\bHRMS\b", text))
