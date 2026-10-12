"""Test attendance calendar stability and anti-blinking fixes."""

import sys
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
from ui.attendance_page import AttendancePage
from ui.main_window import MainWindow
from ui.weekly_timeline import WeeklyTimelinePage
from tracker.activity_tracker import TrackerState


class TestAttendanceCalendarBlinkingFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_01_main_window_tracker_tick_does_not_refresh_attendance_page(self):
        """Ensure tracker worker ticks (every ~1s / app switches) never call refresh() on AttendancePage."""
        window = MainWindow()
        try:
            # In our app, weekly_page is aliased to attendance_page
            self.assertIs(window.weekly_page, window.attendance_page)
            self.assertIsInstance(window.attendance_page, AttendancePage)

            with patch.object(window.attendance_page, "refresh") as mock_refresh:
                # Simulate tracker state change with app switch
                state = TrackerState(
                    is_workpulse=True,
                    is_idle=False,
                    current_application="VSCode",
                    current_window_title="test.py",
                    idle_seconds=0.0,
                )
                window._on_tracker_state_changed(state)
                # attendance_page.refresh should NOT be called
                mock_refresh.assert_not_called()
        finally:
            window.deleteLater()

    def test_02_main_window_tracker_tick_calls_refresh_only_for_real_weekly_timeline_page(self):
        """Ensure if weekly_page is an actual WeeklyTimelinePage, it can still refresh."""
        window = MainWindow()
        try:
            dummy_weekly = WeeklyTimelinePage(activity_service=MagicMock(), parent=window)
            window.weekly_page = dummy_weekly
            with patch.object(dummy_weekly, "isVisible", return_value=True), patch.object(
                dummy_weekly, "refresh"
            ) as mock_refresh:
                state = TrackerState(
                    is_workpulse=True,
                    is_idle=False,
                    current_application="VSCode",
                    current_window_title="test.py",
                    idle_seconds=0.0,
                )
                window._on_tracker_state_changed(state)
                mock_refresh.assert_called_once_with(async_mode=True)
        finally:
            window.deleteLater()

    def test_03_attendance_page_anti_blinking_caching(self):
        """Ensure AttendancePage does not rebuild calendar cards on repeated identical data payloads."""
        page = AttendancePage()
        try:
            mock_days = [
                {"day_num": 1, "status_code": "P", "status_label": "Present", "is_today": False},
                {"day_num": 2, "status_code": "P", "status_label": "Present", "is_today": False},
                {"day_num": 3, "status_code": "WO", "status_label": "Week Off", "is_today": False},
            ]
            payload = {
                "year": 2026,
                "month": "September",
                "days": mock_days,
                "working_days": 2,
                "present_count": 2,
            }

            # First load
            page._apply_attendance_data(payload)
            cards_first = list(page._day_cards)
            self.assertGreater(len(cards_first), 0)

            # User clicks day 2
            day_2_card = next(c for c in cards_first if c._day_data.get("day_num") == 2)
            day_2_card.set_selected(True)
            self.assertTrue(day_2_card._is_selected)

            # Re-apply identical data (as would happen on background sync or interval)
            with patch.object(page, "_populate_calendar") as mock_populate:
                page._apply_attendance_data(payload)
                # Should NOT recreate widgets or re-populate calendar
                mock_populate.assert_not_called()

            # Cards must remain identical instances
            self.assertEqual(page._day_cards, cards_first)
            self.assertTrue(day_2_card._is_selected)
        finally:
            page.deleteLater()

    def test_04_attendance_page_updates_when_month_changes_and_preserves_selection(self):
        """Ensure changing month updates calendar and preserves selected day if present."""
        page = AttendancePage()
        try:
            payload_sep = {
                "year": 2026,
                "month": "September",
                "days": [
                    {"day_num": 1, "status_code": "P", "status_label": "Present", "is_today": False},
                    {"day_num": 2, "status_code": "P", "status_label": "Present", "is_today": False},
                ],
                "working_days": 2,
                "present_count": 2,
            }
            page._apply_attendance_data(payload_sep)
            day_1_card = next(c for c in page._day_cards if c._day_data.get("day_num") == 1)
            day_1_card.set_selected(True)
            self.assertTrue(day_1_card._is_selected)

            payload_oct = {
                "year": 2026,
                "month": "October",
                "days": [
                    {"day_num": 1, "status_code": "A", "status_label": "Absent", "is_today": False},
                    {"day_num": 2, "status_code": "A", "status_label": "Absent", "is_today": False},
                ],
                "working_days": 2,
                "present_count": 0,
            }
            page._apply_attendance_data(payload_oct)

            # After month change, day 1 should still be selected in the new month
            selected_cards = [c for c in page._day_cards if getattr(c, "_is_selected", False)]
            self.assertEqual(len(selected_cards), 1)
            self.assertEqual(selected_cards[0]._day_data.get("day_num"), 1)
        finally:
            page.deleteLater()
