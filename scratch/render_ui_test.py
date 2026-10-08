import os
import sys
from datetime import datetime
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# Ensure root directory in pythonpath
sys.path.insert(0, os.path.abspath("."))

from ui.attendance_page import AttendancePage

app = QApplication.instance() or QApplication(sys.argv)

page = AttendancePage()
page.resize(1180, 820)
page.show()

# Sample data
sample_data = {
    "status": 1,
    "month": "October",
    "year": 2026,
    "days": [
        {"day_num": 1, "date": "2026-10-01", "day_name": "Thu", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 2, "date": "2026-10-02", "day_name": "Fri", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 3, "date": "2026-10-03", "day_name": "Sat", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 4, "date": "2026-10-04", "day_name": "Sun", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 5, "date": "2026-10-05", "day_name": "Mon", "status_code": "A", "status_label": "Absent", "color": "#dc2626", "bg_color": "#fee2e2", "is_today": False, "details": None},
        {"day_num": 6, "date": "2026-10-06", "day_name": "Tue", "status_code": "WO", "status_label": "Week Off", "color": "#7c3aed", "bg_color": "#ede9fe", "is_today": False, "details": None},
        {"day_num": 7, "date": "2026-10-07", "day_name": "Wed", "status_code": "WO", "status_label": "Week Off", "color": "#7c3aed", "bg_color": "#ede9fe", "is_today": False, "details": None},
        {"day_num": 8, "date": "2026-10-08", "day_name": "Thu", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": True, "details": "Punch: 09:15 - 18:00"},
        {"day_num": 9, "date": "2026-10-09", "day_name": "Fri", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 10, "date": "2026-10-10", "day_name": "Sat", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 11, "date": "2026-10-11", "day_name": "Sun", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 12, "date": "2026-10-12", "day_name": "Mon", "status_code": "A", "status_label": "Absent", "color": "#dc2626", "bg_color": "#fee2e2", "is_today": False, "details": None},
        {"day_num": 13, "date": "2026-10-13", "day_name": "Tue", "status_code": "WO", "status_label": "Week Off", "color": "#7c3aed", "bg_color": "#ede9fe", "is_today": False, "details": None},
        {"day_num": 14, "date": "2026-10-14", "day_name": "Wed", "status_code": "WO", "status_label": "Week Off", "color": "#7c3aed", "bg_color": "#ede9fe", "is_today": False, "details": None},
        {"day_num": 15, "date": "2026-10-15", "day_name": "Thu", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 16, "date": "2026-10-16", "day_name": "Fri", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 17, "date": "2026-10-17", "day_name": "Sat", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 18, "date": "2026-10-18", "day_name": "Sun", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 19, "date": "2026-10-19", "day_name": "Mon", "status_code": "A", "status_label": "Absent", "color": "#dc2626", "bg_color": "#fee2e2", "is_today": False, "details": None},
        {"day_num": 20, "date": "2026-10-20", "day_name": "Tue", "status_code": "WO", "status_label": "Week Off", "color": "#7c3aed", "bg_color": "#ede9fe", "is_today": False, "details": None},
        {"day_num": 21, "date": "2026-10-21", "day_name": "Wed", "status_code": "WO", "status_label": "Week Off", "color": "#7c3aed", "bg_color": "#ede9fe", "is_today": False, "details": None},
        {"day_num": 22, "date": "2026-10-22", "day_name": "Thu", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 23, "date": "2026-10-23", "day_name": "Fri", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 24, "date": "2026-10-24", "day_name": "Sat", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 25, "date": "2026-10-25", "day_name": "Sun", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 26, "date": "2026-10-26", "day_name": "Mon", "status_code": "A", "status_label": "Absent", "color": "#dc2626", "bg_color": "#fee2e2", "is_today": False, "details": None},
        {"day_num": 27, "date": "2026-10-27", "day_name": "Tue", "status_code": "WO", "status_label": "Week Off", "color": "#7c3aed", "bg_color": "#ede9fe", "is_today": False, "details": None},
        {"day_num": 28, "date": "2026-10-28", "day_name": "Wed", "status_code": "WO", "status_label": "Week Off", "color": "#7c3aed", "bg_color": "#ede9fe", "is_today": False, "details": None},
        {"day_num": 29, "date": "2026-10-29", "day_name": "Thu", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 30, "date": "2026-10-30", "day_name": "Fri", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
        {"day_num": 31, "date": "2026-10-31", "day_name": "Sat", "status_code": "P", "status_label": "Present", "color": "#16a34a", "bg_color": "#dcfce7", "is_today": False, "details": "Punch: 09:30 - 18:30"},
    ],
    "summary": {
        "working_days": 23,
        "present": 18,
        "absent": 3,
        "missed_punch": 1,
        "half_day": 0,
        "leave": 2,
        "week_off": 8,
        "total_days": 31,
    },
    "freezed": False,
    "error": None,
}

page._apply_attendance_data(sample_data)
# Select date 25 to show selection highlight
if len(page._day_cards) >= 25:
    card_25 = page._day_cards[24]
    card_25.set_selected(True)
    if hasattr(page, "cal_header_date_label"):
        page.cal_header_date_label.setText("Oct 25, Sun")

app.processEvents()

out_path = r"C:\Users\Dell\.gemini\antigravity-ide\brain\bebd6e1c-f684-4fd4-8acc-1c68cd8d7722\scratch\current_ui_check.png"
pix = page.grab()
pix.save(out_path)
print("Saved to", out_path)
