"""Unit tests for Idle Window Title formatting and display in iHRMS Monitor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from database.database import get_session, init_database
from database.models import ActivitySession
from platform_support.base import ActiveApplication, PlatformActivityProvider
from services.activity_service import ActivityService
from services.session_service import SessionService
from tracker.activity_tracker import ActivityTracker, TrackerState
from ui.dashboard import DashboardPage


class FakeClock:
    """Deterministic clock for testing."""

    def __init__(self, start_dt: datetime):
        self.current_dt = start_dt

    def __call__(self) -> datetime:
        return self.current_dt

    def advance(self, seconds: float) -> None:
        self.current_dt += timedelta(seconds=seconds)


class FakeProvider(PlatformActivityProvider):
    """Fake platform provider simulating application and idle time."""

    def __init__(self):
        self.active_application: ActiveApplication | None = ActiveApplication(
            "Code.exe",
            1234,
            "main.py - Visual Studio Code",
        )
        self.idle_seconds: float = 0.0

    def get_active_application(self) -> ActiveApplication | None:
        return self.active_application

    def get_idle_seconds(self) -> float:
        return self.idle_seconds


class TestIdleWindowTitle(unittest.TestCase):
    """Test suite verifying Window Title displays 'Idle - HH:MM:SS' during idle and resumes when active."""

    def setUp(self):
        init_database()
        self.provider = FakeProvider()
        self.start_dt = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        self.clock = FakeClock(self.start_dt)

        SessionService().login(
            username="test_employee",
            role="employee",
            employee_id="EMP_001",
            device_token="DEVICE_001",
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

    def test_01_active_state_shows_actual_window_title(self):
        """When active, TrackerState shows the actual foreground application and window title."""
        self.tracker.start()
        self.provider.idle_seconds = 0.0
        state = self.tracker.poll()

        self.assertFalse(state.is_idle)
        self.assertEqual(state.current_application, "Code.exe")
        self.assertEqual(state.current_window_title, "main.py - Visual Studio Code")

    def test_02_idle_detected_shows_idle_duration_in_window_title(self):
        """When idle is detected (>= threshold), window title shows 'Idle - HH:MM:SS'."""
        self.tracker.start()
        self.provider.idle_seconds = 0.0
        self.tracker.poll()

        # Simulate 85 seconds of idle (1m 25s -> threshold is 60s)
        self.clock.advance(85)
        self.provider.idle_seconds = 85.0
        state = self.tracker.poll()

        self.assertTrue(state.is_idle)
        self.assertEqual(state.current_window_title, "Idle - 00:01:25")

    def test_03_idle_duration_updates_as_idle_continues(self):
        """As idle continues, window title updates with the latest idle duration."""
        self.tracker.start()
        self.provider.idle_seconds = 0.0
        self.tracker.poll()

        # 342 seconds idle (5m 42s -> 00:05:42)
        self.clock.advance(342)
        self.provider.idle_seconds = 342.0
        state1 = self.tracker.poll()
        self.assertTrue(state1.is_idle)
        self.assertEqual(state1.current_window_title, "Idle - 00:05:42")

        # Advance to 908 seconds idle (15m 08s -> 00:15:08)
        self.clock.advance(908 - 342)
        self.provider.idle_seconds = 908.0
        state2 = self.tracker.poll()
        self.assertTrue(state2.is_idle)
        self.assertEqual(state2.current_window_title, "Idle - 00:15:08")

    def test_04_active_again_resumes_actual_window_title(self):
        """When user becomes active again, actual application and window title resume."""
        self.tracker.start()
        self.provider.idle_seconds = 0.0
        self.tracker.poll()

        # Become idle
        self.clock.advance(100)
        self.provider.idle_seconds = 100.0
        idle_state = self.tracker.poll()
        self.assertTrue(idle_state.is_idle)
        self.assertEqual(idle_state.current_window_title, "Idle - 00:01:40")

        # User becomes active in Chrome
        self.clock.advance(1)
        self.provider.idle_seconds = 0.0
        self.provider.active_application = ActiveApplication(
            "chrome.exe",
            5678,
            "Google - Google Chrome",
        )
        active_state = self.tracker.poll()

        self.assertFalse(active_state.is_idle)
        self.assertEqual(active_state.current_application, "chrome.exe")
        self.assertEqual(active_state.current_window_title, "Google - Google Chrome")

    def test_05_dashboard_labels_reflect_idle_window_title(self):
        """DashboardPage labels update with Idle window title and application info."""
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication([])

        service = ActivityService(get_session)
        page = DashboardPage(activity_service=service)

        # Active state
        page.update_tracker_state(TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Slack.exe",
            current_window_title="General - Slack",
            idle_seconds=0.0,
        ))
        self.assertEqual(page.current_app_label.text(), "Slack.exe")
        self.assertEqual(page.current_window_label.text(), "General - Slack")

        # Idle state
        page.update_tracker_state(TrackerState(
            is_tracking=True,
            is_idle=True,
            current_application="Idle",
            current_window_title="Idle - 00:05:42",
            idle_seconds=342.0,
        ))
        self.assertEqual(page.current_app_label.text(), "Idle")
        self.assertEqual(page.current_window_label.text(), "Idle - 00:05:42")

        # Resumed state
        page.update_tracker_state(TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="Slack.exe",
            current_window_title="General - Slack",
            idle_seconds=342.0,
        ))
        self.assertEqual(page.current_app_label.text(), "Slack.exe")
        self.assertEqual(page.current_window_label.text(), "General - Slack")


if __name__ == "__main__":
    unittest.main()
