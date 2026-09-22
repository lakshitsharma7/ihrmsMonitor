"""Tests verifying the Today's Time dashboard counter.

Requirements:
- Continuously accumulate during active tracking.
- Represent complete total tracked time for the current calendar day.
- Do NOT reset on dashboard refresh.
- Do NOT reset on API sync.
- Do NOT reset on tracking stop/start.
- Do NOT reset on app restart.
- Do NOT reset on idle -> active transition.
- Do NOT reset on session changes (application switch).
- Reset ONLY when a new calendar day begins.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import sys
import unittest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from services.activity_service import ActivityService
from tracker.activity_tracker import TrackerState
from ui.dashboard import DashboardPage


class TestTodayTimeCounter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.mock_service = MagicMock(spec=ActivityService)
        self.mock_service.get_today_total_seconds.return_value = 100
        self.mock_service.get_persisted_daily_active_seconds.return_value = 100
        self.mock_service.get_uploaded_records_count.return_value = 5
        self.mock_service.get_today_total_idle_seconds.return_value = 20
        self.mock_service.get_today_timeline.return_value = []

    def test_01_initialization_with_persisted_or_db_seconds(self):
        """DashboardPage initializes with cumulative today seconds and formats label immediately."""
        dashboard = DashboardPage(self.mock_service)
        self.assertGreaterEqual(dashboard._cached_today_total_seconds, 100)
        self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(dashboard._cached_today_total_seconds))

    def test_02_continuous_live_accumulation_during_active_tracking(self):
        """Counter continuously increments by 1s on each active non-idle tick."""
        dashboard = DashboardPage(self.mock_service)
        initial_seconds = dashboard._cached_today_total_seconds

        state = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Chrome.exe",
            current_window_title="Tab",
            idle_seconds=0.0,
        )

        for i in range(1, 6):
            dashboard.update_tracker_state(state)
            self.assertEqual(dashboard._cached_today_total_seconds, initial_seconds + i)
            self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(initial_seconds + i))

    def test_03_no_accumulation_during_idle_and_resumes_without_reset(self):
        """Counter pauses during idle and resumes continuous accumulation on active resumption without resetting."""
        dashboard = DashboardPage(self.mock_service)
        initial_seconds = dashboard._cached_today_total_seconds

        # Active for 3 seconds
        active_state = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Chrome.exe",
            current_window_title="Tab",
            idle_seconds=0.0,
        )
        for _ in range(3):
            dashboard.update_tracker_state(active_state)
        self.assertEqual(dashboard._cached_today_total_seconds, initial_seconds + 3)

        # User goes idle for 4 ticks
        idle_state = TrackerState(
            is_tracking=True,
            is_idle=True,
            current_application=None,
            current_window_title=None,
            idle_seconds=65.0,
        )
        for _ in range(4):
            dashboard.update_tracker_state(idle_state)
        # Active time must remain unchanged during idle
        self.assertEqual(dashboard._cached_today_total_seconds, initial_seconds + 3)

        # User returns from idle (idle -> active transition)
        dashboard.update_tracker_state(active_state)
        # Must resume from initial + 4 without resetting
        self.assertEqual(dashboard._cached_today_total_seconds, initial_seconds + 4)
        self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(initial_seconds + 4))

    def test_04_no_reset_on_session_changes_app_switch(self):
        """Switching applications does not reset the counter; it continues continuous accumulation."""
        dashboard = DashboardPage(self.mock_service)
        initial_seconds = dashboard._cached_today_total_seconds

        state_app1 = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="AppOne.exe",
            current_window_title="Window 1",
            idle_seconds=0.0,
        )
        dashboard.update_tracker_state(state_app1)
        self.assertEqual(dashboard._cached_today_total_seconds, initial_seconds + 1)

        # Switch to AppTwo
        state_app2 = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="AppTwo.exe",
            current_window_title="Window 2",
            idle_seconds=0.0,
        )
        dashboard.update_tracker_state(state_app2)
        self.assertEqual(dashboard._cached_today_total_seconds, initial_seconds + 2)
        self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(initial_seconds + 2))

    def test_05_no_reset_on_dashboard_refresh_or_api_sync(self):
        """Refreshing dashboard or applying sync results does not step backwards or reset to 0."""
        dashboard = DashboardPage(self.mock_service)
        dashboard._cached_today_total_seconds = 500
        dashboard.today_total_label.setText(ActivityService.format_duration(500))

        # Synchronous refresh with smaller/stale DB value (e.g. 450) must not pull counter backwards
        self.mock_service.get_today_total_seconds.return_value = 450
        dashboard.refresh(async_mode=False)
        self.assertEqual(dashboard._cached_today_total_seconds, 500)
        self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(500))

        # Asynchronous refresh payload with 480 seconds must not pull counter backwards
        dashboard._apply_dashboard_data({
            "total_seconds": 480,
            "uploaded_count": 5,
            "today_idle": 10,
            "timeline": [],
        })
        self.assertEqual(dashboard._cached_today_total_seconds, 500)

        # Refresh payload with greater DB value (e.g. 520) advances counter smoothly
        dashboard._apply_dashboard_data({
            "total_seconds": 520,
            "uploaded_count": 5,
            "today_idle": 10,
            "timeline": [],
        })
        self.assertEqual(dashboard._cached_today_total_seconds, 520)
        self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(520))

    def test_06_no_reset_on_tracking_stop_and_start(self):
        """Stopping tracking preserves the displayed counter; restarting continues accumulation."""
        dashboard = DashboardPage(self.mock_service)
        dashboard._cached_today_total_seconds = 300
        dashboard.today_total_label.setText(ActivityService.format_duration(300))

        # User stops tracking
        dashboard.set_tracking_active(False)
        self.assertEqual(dashboard._cached_today_total_seconds, 300)
        self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(300))

        # Inactive state ticks do not increment
        inactive_state = TrackerState(
            is_tracking=False,
            is_idle=False,
            current_application=None,
            current_window_title=None,
            idle_seconds=0.0,
        )
        dashboard.update_tracker_state(inactive_state)
        self.assertEqual(dashboard._cached_today_total_seconds, 300)

        # User starts tracking again
        dashboard.set_tracking_active(True)
        active_state = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Notepad.exe",
            current_window_title="Notes",
            idle_seconds=0.0,
        )
        dashboard.update_tracker_state(active_state)
        self.assertEqual(dashboard._cached_today_total_seconds, 301)
        self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(301))

    def test_07_persistence_across_app_restart(self):
        """Simulating app restart on the same calendar day preserves accumulated time."""
        dashboard1 = DashboardPage(self.mock_service)
        dashboard1._cached_today_total_seconds = 750
        today_date = dashboard1._cached_calendar_date
        dashboard1._save_persisted_today_seconds(750, today_date)
        self.mock_service.save_daily_active_seconds.assert_called_with(today_date, 750)

        # Create fresh DashboardPage instance as would occur on app restart
        self.mock_service.get_today_total_seconds.return_value = 750
        self.mock_service.get_persisted_daily_active_seconds.return_value = 750
        dashboard2 = DashboardPage(self.mock_service)
        self.assertEqual(dashboard2._cached_today_total_seconds, 750)
        self.assertEqual(dashboard2.today_total_label.text(), ActivityService.format_duration(750))

    def test_08_resets_only_when_new_calendar_day_begins(self):
        """Counter resets to 0 ONLY when the local calendar date rolls over to a new day."""
        self.mock_service.get_persisted_daily_active_seconds.side_effect = lambda d: 600 if d == date(2026, 9, 8) else 0
        self.mock_service.get_day_total_seconds.side_effect = lambda d: 600 if d == date(2026, 9, 8) else 0

        dashboard = DashboardPage(self.mock_service)
        dashboard._cached_today_total_seconds = 600
        dashboard._cached_calendar_date = date(2026, 9, 8)

        # While date remains 2026-09-08, tracking continues
        state = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Work.exe",
            current_window_title="Doc",
            idle_seconds=0.0,
        )

        # Simulate date rollover to next day (2026-09-09)
        from unittest.mock import patch
        with patch("ui.dashboard.datetime") as mock_dt:
            # Return new calendar date 2026-09-09 on astimezone().date()
            mock_local = MagicMock()
            mock_local.date.return_value = date(2026, 9, 9)
            mock_dt.now.return_value.astimezone.return_value = mock_local

            dashboard.update_tracker_state(state)

            # Counter must have reset to 0 for the new calendar day, plus the 1s from the current tick
            self.assertEqual(dashboard._cached_calendar_date, date(2026, 9, 9))
            self.assertEqual(dashboard._cached_today_total_seconds, 1)
            self.assertEqual(dashboard.today_total_label.text(), ActivityService.format_duration(1))

    def test_09_every_active_tick_persists_accumulated_seconds(self):
        """Active non-idle ticks persist accumulated seconds on every interval."""
        dashboard = DashboardPage(self.mock_service)
        start_sec = dashboard._cached_today_total_seconds
        today_date = dashboard._cached_calendar_date

        state = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Editor.exe",
            current_window_title="Code",
            idle_seconds=0.0,
        )

        self.mock_service.save_daily_active_seconds.reset_mock()
        dashboard.update_tracker_state(state)
        self.mock_service.save_daily_active_seconds.assert_called_with(today_date, start_sec + 1)

    def test_10_online_status_and_toggle_tracking_button(self):
        """Online status reflects tracking active state and toggle button triggers correct signals."""
        dashboard = DashboardPage(self.mock_service)

        # Initial active state
        dashboard.set_tracking_active(True)
        self.assertEqual(dashboard.tracking_status_label.text(), "Online: Active")
        self.assertEqual(dashboard.tracking_toggle_button.text(), "Stop Tracking")

        # Clicking toggle button while active emits tracking_stop_requested
        stop_mock = MagicMock()
        dashboard.tracking_stop_requested.connect(stop_mock)
        dashboard.tracking_toggle_button.click()
        stop_mock.assert_called_once()

        # Update state to inactive
        dashboard.set_tracking_active(False)
        self.assertEqual(dashboard.tracking_status_label.text(), "Online: Inactive")
        self.assertEqual(dashboard.tracking_toggle_button.text(), "Start Tracking")

        # Clicking toggle button while inactive emits tracking_start_requested
        start_mock = MagicMock()
        dashboard.tracking_start_requested.connect(start_mock)
        dashboard.tracking_toggle_button.click()
        start_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
