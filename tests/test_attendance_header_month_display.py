"""
Test suite for Attendance Calendar Header Month Display.
Verifies that the calendar header displays ONLY the selected month name (e.g. 'October'),
updates dynamically on previous/next/sidebar navigation without full reload,
and never reverts to showing date or weekday when cards are clicked.
"""

import sys
from datetime import datetime
import pytest
from PySide6.QtWidgets import QApplication
from ui.attendance_page import AttendancePage, MONTH_NAMES, CalendarDayCard


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app


def test_calendar_header_initial_display(qapp):
    """Header should initialize displaying only the selected month name (no day number or weekday)."""
    page = AttendancePage()
    cur_month = page.month_combo.currentText()
    header_text = page.cal_header_date_label.text()

    assert header_text == cur_month
    assert header_text in MONTH_NAMES
    assert "," not in header_text
    assert "Mon" not in header_text and "Tue" not in header_text and "Wed" not in header_text
    assert not any(char.isdigit() for char in header_text)


def test_calendar_header_updates_on_prev_and_next_month(qapp):
    """Header should immediately update when navigating previous or next months."""
    page = AttendancePage()
    now = datetime.now()

    # Set to a known month, e.g. October
    page.month_combo.setCurrentText("October")
    assert page.cal_header_date_label.text() == "October"

    # Click previous month
    page._on_prev_month()
    assert page.month_combo.currentText() == "September"
    assert page.cal_header_date_label.text() == "September"
    assert not any(char.isdigit() for char in page.cal_header_date_label.text())

    # Click previous month again
    page._on_prev_month()
    assert page.month_combo.currentText() == "August"
    assert page.cal_header_date_label.text() == "August"

    # Click next month
    page._on_next_month()
    assert page.month_combo.currentText() == "September"
    assert page.cal_header_date_label.text() == "September"

    page._on_next_month()
    assert page.month_combo.currentText() == "October"
    assert page.cal_header_date_label.text() == "October"


def test_calendar_header_updates_on_sidebar_selection(qapp):
    """Header updates when a month is clicked in the left sidebar."""
    page = AttendancePage()
    page._on_sidebar_month_clicked("May")
    assert page.month_combo.currentText() == "May"
    assert page.cal_header_date_label.text() == "May"

    page._on_sidebar_month_clicked("January")
    assert page.month_combo.currentText() == "January"
    assert page.cal_header_date_label.text() == "January"


def test_calendar_header_remains_month_only_on_card_click(qapp):
    """Clicking a day card should NOT overwrite the header with date or weekday."""
    page = AttendancePage()
    page.month_combo.setCurrentText("October")
    assert page.cal_header_date_label.text() == "October"

    # Mock a card click
    card = CalendarDayCard({"day_num": 12, "status_code": "P", "status_label": "Present"})
    day_info = {
        "day_num": 12,
        "date": "2026-10-12",
        "day_name": "Mon",
        "status_code": "P",
        "status_label": "Present",
    }
    
    # Trigger _on_card_clicked
    # We patch _show_day_detail so it doesn't open a blocking QDialog
    page._show_day_detail = lambda day_info, card=None: None
    page._on_card_clicked(day_info, card)

    # Header must still show only "October"
    assert page.cal_header_date_label.text() == "October"
    assert "Oct" not in page.cal_header_date_label.text() or page.cal_header_date_label.text() == "October"
    assert "12" not in page.cal_header_date_label.text()
    assert "Mon" not in page.cal_header_date_label.text()
