"""Unit tests verifying idle/tracking state handling across Windows Sleep/Resume."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from database.database import _SessionFactory, get_session, init_database
from database.repository import ActivityRepository
from platform_support.base import ActiveApplication, PlatformActivityProvider
from tracker.activity_tracker import ActivityTracker


class FakeClock:
    def __init__(self, start: datetime):
        self._now = start

    def advance(self, seconds: float):
        self._now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self._now


class FakeProvider(PlatformActivityProvider):
    def __init__(self):
        self.active_application: ActiveApplication | None = ActiveApplication("chrome.exe", 101, "Google")
        self.idle_seconds: float = 0.0
        self.reset_called = False

    def get_active_application(self) -> ActiveApplication | None:
        return self.active_application

    def get_idle_seconds(self) -> float:
        return self.idle_seconds

    def reset_after_resume(self) -> None:
        self.reset_called = True
        self.idle_seconds = 0.0


class TestSleepResumeHandling(unittest.TestCase):
    """Verify tracker and idle detector correctly handle sleep and resume."""

    def setUp(self):
        init_database()
        self.session_factory = get_session
        from database.models import ActivitySession
        db = get_session()
        try:
            db.query(ActivitySession).delete()
            db.commit()
        finally:
            db.close()

    def test_sleep_gap_in_poll_triggers_resume_and_closes_session_at_sleep_time(self):
        """Verify that a time gap (>5s) between polls closes the pre-sleep session at sleep time."""
        clock = FakeClock(datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc))
        provider = FakeProvider()
        tracker = ActivityTracker(
            provider=provider,
            session_factory=self.session_factory,
            idle_threshold_seconds=300,
            clock=clock,
        )
        tracker.start()

        # Poll 1 at 10:00:00: opens Chrome session
        state1 = tracker.poll()
        self.assertEqual(state1.current_application, "chrome.exe")
        self.assertFalse(state1.is_idle)

        # 30 seconds of work
        clock.advance(30)
        state2 = tracker.poll()
        self.assertEqual(state2.current_application, "chrome.exe")

        # Laptop goes to sleep for 8 hours (28,800 seconds)
        clock.advance(28800)

        # Poll right after wake
        state_after_wake = tracker.poll()

        # 1. State must NOT be trapped in Idle
        self.assertFalse(state_after_wake.is_idle)
        self.assertEqual(state_after_wake.current_application, "chrome.exe")
        self.assertTrue(provider.reset_called)

        # 2. Check the pre-sleep session in database: duration must be ~30s, NOT 8 hours!
        db = self.session_factory()
        try:
            repo = ActivityRepository(db)
            sessions = repo.get_sessions_between(
                datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 8, 0, 0, 0, tzinfo=timezone.utc),
            )
            # Find the closed pre-sleep session
            pre_sleep = [s for s in sessions if s.ended_at is not None]
            self.assertTrue(len(pre_sleep) >= 1)
            # Duration should be <= 35 seconds, NOT 28,800 seconds
            self.assertLessEqual(pre_sleep[0].duration_seconds, 35)
        finally:
            db.close()

        tracker.stop()

    def test_handle_system_suspend_and_resume_explicit(self):
        """Verify explicit handle_system_suspend and handle_system_resume lifecycle."""
        clock = FakeClock(datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc))
        provider = FakeProvider()
        tracker = ActivityTracker(
            provider=provider,
            session_factory=self.session_factory,
            idle_threshold_seconds=300,
            clock=clock,
        )
        tracker.start()
        tracker.poll()

        # Working for 60 seconds
        clock.advance(60)
        tracker.poll()

        # Native suspend signal received
        suspend_time = clock()
        tracker.handle_system_suspend(now=suspend_time)

        # Asleep for 5 hours
        clock.advance(5 * 3600)

        # Native resume signal received
        resume_time = clock()
        tracker.handle_system_resume(now=resume_time)

        # State must immediately be tracking and active
        self.assertFalse(tracker._is_idle)
        self.assertIsNone(tracker._idle_start_time)
        self.assertEqual(tracker._last_idle_seconds, 0.0)

        # User types / clicks
        state = tracker.poll()
        self.assertFalse(state.is_idle)
        self.assertEqual(state.current_application, "chrome.exe")

        tracker.stop()

    def test_idle_spanning_sleep_does_not_record_sleep_hours_as_idle_duration(self):
        """Verify that if a user went idle before sleep, 14 hours of sleep is not saved as idle time."""
        clock = FakeClock(datetime(2026, 9, 7, 18, 0, 0, tzinfo=timezone.utc))
        provider = FakeProvider()
        tracker = ActivityTracker(
            provider=provider,
            session_factory=self.session_factory,
            idle_threshold_seconds=300,
            clock=clock,
        )
        tracker.start()
        tracker.poll()

        # User went idle before sleep
        provider.idle_seconds = 301
        clock.advance(1)
        tracker.poll()
        self.assertTrue(tracker._is_idle)

        # Laptop went to sleep for 12 hours
        clock.advance(12 * 3600)
        tracker.handle_system_resume(now=clock())

        # Resume user activity
        provider.idle_seconds = 0.0
        provider.active_application = ActiveApplication("code.exe", 200, "main.py")
        state = tracker.poll()

        # Must be active now
        self.assertFalse(state.is_idle)
        self.assertEqual(state.current_application, "code.exe")

        # Check database: idle seconds must NOT be 12 hours (43,200s)
        db = self.session_factory()
        try:
            repo = ActivityRepository(db)
            sessions = repo.get_sessions_between(
                datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 8, 0, 0, 0, tzinfo=timezone.utc),
            )
            for s in sessions:
                self.assertLess(getattr(s, "idle_seconds", 0), 3600)
        finally:
            db.close()

        tracker.stop()

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows-specific idle detector test")
    def test_windows_idle_detector_resume_capping(self):
        """Verify platform_support.windows.idle_detector caps pre-sleep tick counts after resume."""
        from platform_support.windows import idle_detector

        # Reset baseline after resume
        idle_detector.reset_after_resume()

        # Even if GetLastInputInfo returned an old tick count from 5 hours ago,
        # get_idle_seconds must cap it to the elapsed time since resume (<= 2 seconds)
        mock_last_input = idle_detector._LASTINPUTINFO()
        mock_last_input.dwTime = 1000  # Stale tick from hours ago

        with patch("ctypes.windll.user32.GetLastInputInfo", return_value=1), \
             patch("ctypes.windll.kernel32.GetTickCount", return_value=50000000), \
             patch("ctypes.windll.user32.GetCursorPos", return_value=1), \
             patch("ctypes.windll.user32.GetAsyncKeyState", return_value=0):
            idle = idle_detector.get_idle_seconds()
            # Idle time must NOT be 50,000 seconds! It should be capped near 0.0s!
            self.assertLess(idle, 5.0)

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows-specific idle detector test")
    def test_windows_idle_detector_detects_mouse_move_and_clicks(self):
        """Verify platform_support.windows.idle_detector returns 0.0 on cursor movement or button press."""
        from platform_support.windows import idle_detector

        # 1. Simulate mouse cursor movement
        idle_detector._last_cursor_pos = (100, 100)
        with patch("ctypes.windll.user32.GetCursorPos") as mock_cursor:
            def _move_cursor(byref_pt):
                pt = byref_pt._obj
                pt.x = 200
                pt.y = 250
                return 1
            mock_cursor.side_effect = _move_cursor
            idle = idle_detector.get_idle_seconds()
            self.assertEqual(idle, 0.0)

        # 2. Simulate mouse button press (VK_LBUTTON=0x01)
        with patch("ctypes.windll.user32.GetCursorPos", return_value=0), \
             patch("ctypes.windll.user32.GetAsyncKeyState", return_value=0x8000):
            idle = idle_detector.get_idle_seconds()
            self.assertEqual(idle, 0.0)


if __name__ == "__main__":
    unittest.main()
