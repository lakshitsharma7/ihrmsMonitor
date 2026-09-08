"""Unit tests for the Dashboard Real-time Idle Time counter and preservation logic."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from database.database import get_session, init_database
from database.models import ActivitySession
from platform_support.base import ActiveApplication, PlatformActivityProvider
from services.activity_service import ActivityService
from services.session_service import SessionService
from tracker.activity_tracker import ActivityTracker, TrackerState
from ui.dashboard import DashboardPage


class FakeClock:
    """Deterministic clock for simulating time progression."""

    def __init__(self, start_dt: datetime):
        self.current_dt = start_dt

    def __call__(self) -> datetime:
        return self.current_dt

    def advance(self, seconds: float) -> None:
        self.current_dt += timedelta(seconds=seconds)


class FakeProvider(PlatformActivityProvider):
    """Fake platform provider simulating active application and idle seconds."""

    def __init__(self):
        self.active_application: ActiveApplication | None = ActiveApplication("TestApp.exe", 1234, "Test Window")
        self.idle_seconds: float = 0.0

    def get_active_application(self) -> ActiveApplication | None:
        return self.active_application

    def get_idle_seconds(self) -> float:
        return self.idle_seconds


class TestDashboardIdleCounter(unittest.TestCase):
    """Test suite verifying Dashboard Idle Time counter real-time update and preservation."""

    def setUp(self):
        init_database()
        self.provider = FakeProvider()
        self.start_dt = datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc)
        self.clock = FakeClock(self.start_dt)

        SessionService().login(
            username="idle_test_user",
            role="employee",
            employee_id="EMP_IDLE_1",
            device_token="DEVICE_IDLE_1",
        )

        db = get_session()
        try:
            db.query(ActivitySession).delete()
            db.commit()
        finally:
            db.close()

        self.tracker = ActivityTracker(
            provider=self.provider,
            session_factory=get_session,
            idle_threshold_seconds=60,
            track_window_titles=True,
            clock=self.clock,
        )

    def test_01_idle_counts_in_real_time_second_by_second(self):
        """When user becomes idle, Idle Time must count in real time (1s, 2s, 3s...) immediately."""
        self.tracker.start()

        # Step 1: Active
        self.provider.idle_seconds = 0.0
        state = self.tracker.poll()
        self.assertEqual(state.idle_seconds, 0.0)

        # Step 2: User stops interacting - becomes idle second by second
        self.provider.idle_seconds = 1.0
        self.clock.advance(1)
        state1 = self.tracker.poll()
        self.assertEqual(state1.idle_seconds, 1.0)

        self.provider.idle_seconds = 2.0
        self.clock.advance(1)
        state2 = self.tracker.poll()
        self.assertEqual(state2.idle_seconds, 2.0)

        self.provider.idle_seconds = 3.0
        self.clock.advance(1)
        state3 = self.tracker.poll()
        self.assertEqual(state3.idle_seconds, 3.0)

        self.provider.idle_seconds = 4.0
        self.clock.advance(1)
        state4 = self.tracker.poll()
        self.assertEqual(state4.idle_seconds, 4.0)

    def test_02_stops_counter_and_preserves_duration_when_active_again(self):
        """When user becomes active again, stop the idle counter and preserve the calculated idle duration."""
        self.tracker.start()

        # Idle for 15 seconds
        for s in range(1, 16):
            self.provider.idle_seconds = float(s)
            self.clock.advance(1)
            state = self.tracker.poll()
            self.assertEqual(state.idle_seconds, float(s))

        # User becomes active again at second 16
        self.provider.idle_seconds = 0.0
        self.clock.advance(1)
        resumed_state = self.tracker.poll()

        # Idle counter should stop and preserve 15 seconds
        self.assertEqual(resumed_state.idle_seconds, 15.0)
        self.assertFalse(resumed_state.is_idle)

        # Continues active work for 5 more seconds - preserved idle duration remains 15.0s
        for _ in range(5):
            self.clock.advance(1)
            active_state = self.tracker.poll()
            self.assertEqual(active_state.idle_seconds, 15.0)

    def test_03_dashboard_page_updates_idle_time_label_in_real_time(self):
        """DashboardPage idle_time_label reflects real-time idle duration and preserves it."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        service = ActivityService(get_session)
        page = DashboardPage(activity_service=service)

        # Active state
        page.update_tracker_state(TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="TestApp.exe",
            current_window_title="Test Window",
            idle_seconds=0.0,
        ))
        self.assertEqual(page.idle_time_label.text(), "Idle Time: 0 seconds")

        # Second by second idle updates
        for s in (1, 2, 3, 4, 5):
            page.update_tracker_state(TrackerState(
                is_tracking=True,
                is_idle=False,
                current_application="TestApp.exe",
                current_window_title="Test Window",
                idle_seconds=float(s),
            ))
            self.assertEqual(page.idle_time_label.text(), f"Idle Time: {s} seconds")

        # 65 seconds idle (1m 5s)
        page.update_tracker_state(TrackerState(
            is_tracking=True,
            is_idle=True,
            current_application="TestApp.exe",
            current_window_title="Test Window",
            idle_seconds=65.0,
        ))
        self.assertEqual(page.idle_time_label.text(), "Idle Time: 1 minutes 5 seconds")

        # Returned to active - preserves 65s on label
        page.update_tracker_state(TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="TestApp.exe",
            current_window_title="Test Window",
            idle_seconds=65.0,
        ))
        self.assertEqual(page.idle_time_label.text(), "Idle Time: 1 minutes 5 seconds")


if __name__ == "__main__":
    unittest.main()
