"""Comprehensive tests for Attendance Calendar UI:
1. Distinct color tokens for Week Off (#2563EB), Leave (#9333EA), Holiday (#0EA5E9), etc.
2. Alignment of weekday headings (SUN .. SAT) directly above all 7 date columns across
   months starting on various weekdays and with 28, 29, 30, and 31 days.
3. Legend matching date indicator colors.
4. Selection outline visibility without replacing the status color.
"""

import sys
import unittest
import calendar
from datetime import date
from PySide6.QtWidgets import QApplication, QLabel
from ui.attendance_page import AttendancePage, CalendarDayCard, WEEKDAY_NAMES


class TestCalendarUIAlignmentAndColors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.page = AttendancePage()

    def tearDown(self):
        self.page.deleteLater()

    def test_01_status_circle_colors(self):
        """Verify date circles, badges, and hovers use exact required colors."""
        test_cases = [
            ("Week Off", "WO", "#2563EB", "Week Off must be Blue #2563EB"),
            ("Leave", "CL", "#9333EA", "Leave must be Purple #9333EA"),
            ("Present", "P", "#16A34A", "Present must be Green #16A34A"),
            ("Absent", "A", "#EF4444", "Absent must be Red #EF4444"),
            ("Missed Punch", "MP", "#F59E0B", "Missed Punch must be Amber #F59E0B"),
            ("Holiday", "H", "#0EA5E9", "Holiday must be Cyan #0EA5E9"),
        ]

        for label, code, expected_color, err_msg in test_cases:
            card = CalendarDayCard(day_data={"day_num": 1, "status_label": label, "status_code": code})
            self.assertEqual(card._status_circle_bg, expected_color, err_msg)
            self.assertEqual(card._card_hover, expected_color, f"Card hover should match {expected_color}")

    def test_02_selection_outline_preserves_status_color(self):
        """Verify selected-day outline remains visible without replacing the status color."""
        # Week Off card selected
        wo_card = CalendarDayCard(day_data={"day_num": 4, "status_label": "Week Off", "status_code": "WO"})
        self.assertEqual(wo_card._status_circle_bg, "#2563EB")
        wo_card.set_selected(True)
        # Background is still #2563EB, and border is visible
        wo_style = wo_card.num_label.styleSheet()
        self.assertIn("background: #2563EB", wo_style)
        self.assertIn("border: 2.5px solid", wo_style)

        # Leave card selected
        leave_card = CalendarDayCard(day_data={"day_num": 5, "status_label": "Leave", "status_code": "CL"})
        self.assertEqual(leave_card._status_circle_bg, "#9333EA")
        leave_card.set_selected(True)
        leave_style = leave_card.num_label.styleSheet()
        self.assertIn("background: #9333EA", leave_style)
        self.assertIn("border: 2.5px solid", leave_style)

    def test_03_legend_colors_match_indicators(self):
        """Verify the calendar legend displays the exact status colors."""
        expected_legend = {
            "Present": "#16A34A",
            "Absent": "#EF4444",
            "Missed punch": "#F59E0B",
            "Week off": "#2563EB",
            "Leave": "#9333EA",
            "Holiday": "#0EA5E9",
        }
        # Find all legend labels in the calendar panel
        found_legend = {}
        for child in self.page.cal_right_panel.findChildren(QLabel):
            text = child.text()
            for name in expected_legend:
                if f">{name}</span>" in text:
                    for color in expected_legend.values():
                        if f"color:{color};" in text:
                            found_legend[name] = color

        self.assertEqual(len(found_legend), len(expected_legend))
        for name, color in expected_legend.items():
            self.assertEqual(found_legend.get(name), color, f"Legend color mismatch for {name}")

    def test_04_calendar_grid_seven_equal_columns_and_header_alignment(self):
        """Test calendar layouts for months with 28, 29, 30, and 31 days starting on various weekdays."""
        test_months = [
            (2026, 2, "February 2026: 28 days, starts on Sunday"),
            (2020, 2, "February 2020: 29 days, starts on Saturday (Leap Year)"),
            (2026, 6, "June 2026: 30 days, starts on Monday"),
            (2026, 9, "September 2026: 30 days, starts on Tuesday"),
            (2026, 7, "July 2026: 31 days, starts on Wednesday"),
            (2026, 1, "January 2026: 31 days, starts on Thursday"),
            (2026, 5, "May 2026: 31 days, starts on Friday"),
            (2026, 8, "August 2026: 31 days, starts on Saturday"),
            (2026, 3, "March 2026: 31 days, starts on Sunday"),
        ]

        for year, month, description in test_months:
            with self.subTest(msg=description):
                self.page._populate_calendar([], month, year)

                grid = self.page.calendar_grid

                # Exactly 7 columns with equal stretch factor = 1
                for c in range(7):
                    self.assertEqual(grid.columnStretch(c), 1, f"Column {c} stretch should be 1")

                # Row 0 must contain the 7 weekday headings SUN ... SAT
                for c in range(7):
                    item = grid.itemAtPosition(0, c)
                    self.assertIsNotNone(item, f"Header at row 0, col {c} missing in {description}")
                    widget = item.widget()
                    self.assertIsInstance(widget, QLabel)
                    self.assertEqual(
                        widget.text(),
                        WEEKDAY_NAMES[c].upper(),
                        f"Header at col {c} should be {WEEKDAY_NAMES[c].upper()}",
                    )

                # Verify every date appears under the correct weekday column (Sunday = col 0 ... Saturday = col 6)
                first_weekday, num_days = calendar.monthrange(year, month)
                for day_num in range(1, num_days + 1):
                    dt = date(year, month, day_num)
                    # Python weekday: Mon=0, Tue=1, ..., Sat=5, Sun=6
                    # Sunday-first col: Sun=0, Mon=1, ..., Sat=6
                    expected_col = (dt.weekday() + 1) % 7
                    card = self.page._day_cards[day_num - 1]
                    self.assertEqual(int(card.num_label.text()), day_num)

                    # Find position in grid
                    pos = None
                    for r in range(1, grid.rowCount()):
                        cell_item = grid.itemAtPosition(r, expected_col)
                        if cell_item and cell_item.widget() == card:
                            pos = (r, expected_col)
                            break
                    self.assertIsNotNone(
                        pos,
                        f"Day {day_num} of {year}-{month} not found under column {expected_col} ({WEEKDAY_NAMES[expected_col]})",
                    )


if __name__ == "__main__":
    unittest.main()
