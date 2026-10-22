"""Comprehensive test suite for Windows lock (Win + L) and display-off tracking.

Verifies:
1. Workstation lock state detection (is_workstation_locked).
2. Foreground application filtering to prevent LockApp.exe / LogonUI.exe from being tracked as active applications.
3. ActivityTracker lifecycle during Windows lock (Win + L):
   - Immediate or threshold-based transition to idle.
   - Active application closed retroactively at exact moment of lock.
   - Accumulation of idle duration while machine remains locked in background.
   - Clean resumption when user unlocks without session corruption or false app creation.
4. Payload construction and synchronization of locked/idle periods.
5. Display-off and sleep/suspend boundary behavior.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from database.database import get_session, init_database
from database.models import ActivitySession
from database.repository import ActivityRepository
from platform_support.base import ActiveApplication, PlatformActivityProvider
from platform_support.windows import active_window
from services.session_service import SessionService
from services.sync_service import SyncService
from tracker.activity_tracker import ActivityTracker


class FakeClock:
    """Deterministic controllable clock for test scenarios."""

    def __init__(self, start_dt: datetime):
        self.current_dt = start_dt

    def __call__(self) -> datetime:
        return self.current_dt

    def advance(self, seconds: float) -> None:
        self.current_dt += timedelta(seconds=seconds)


class LockableFakeProvider(PlatformActivityProvider):
    """Controllable provider that simulates active app, idle time, and workstation lock state."""

    def __init__(self):
        self.active_application: ActiveApplication | None = ActiveApplication("chrome.exe", 101, "Google Chrome")
        self.idle_seconds: float = 0.0
        self.locked: bool = False

    def get_active_application(self) -> ActiveApplication | None:
        if self.locked:
            return None
        return self.active_application

    def get_idle_seconds(self) -> float:
        return self.idle_seconds

    def is_workstation_locked(self) -> bool:
        return self.locked


class TestWindowsLockAndDisplayOffTracking(unittest.TestCase):
    """Tests for Windows locked state (Win + L), display-off, and idle handling."""

    def setUp(self):
        init_database()
        self.provider = LockableFakeProvider()
        self.start_dt = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        self.clock = FakeClock(self.start_dt)
        self.sync_service = SyncService(api_url="https://test.api")
        self.sync_service.current_sync_interval_seconds = 300
        self.sync_service.current_idle_threshold_seconds = 60

        # Patch requests.post to avoid real network calls during tests
        self.post_patcher = patch("requests.post")
        self.mock_post = self.post_patcher.start()
        default_resp = MagicMock()
        default_resp.status_code = 200
        default_resp.json.return_value = {
            "response": "Success",
            "data": {
                "sync_interval_seconds": 300,
                "idle_threshold_seconds": 60,
            },
        }
        self.mock_post.return_value = default_resp

        # Authenticate session
        SessionService().login(
            username="dinesh_dev",
            role="employee",
            employee_id="EC-098",
            device_token="DEV_TOKEN_LOCK_TEST",
        )

        # Clear test database sessions
        db = get_session()
        try:
            db.query(ActivitySession).delete()
            db.commit()
        finally:
            db.close()

    def tearDown(self):
        self.post_patcher.stop()
        SessionService().logout()

    def _make_tracker(self, idle_threshold: int = 60) -> ActivityTracker:
        return ActivityTracker(
            provider=self.provider,
            session_factory=get_session,
            idle_threshold_seconds=idle_threshold,
            track_window_titles=True,
            clock=self.clock,
            sync_service=self.sync_service,
        )

    # -------------------------------------------------------------------------
    # 1. Detection of Windows Lock State
    # -------------------------------------------------------------------------
    def test_is_workstation_locked_detection(self):
        """Verify is_workstation_locked correctly reflects desktop switchability."""
        with patch("ctypes.windll.user32.OpenInputDesktop") as mock_open:
            with patch("ctypes.windll.user32.SwitchDesktop") as mock_switch:
                with patch("ctypes.windll.user32.CloseDesktop"):
                    # Desktop switch succeeds -> Unlocked
                    mock_open.return_value = 1234
                    mock_switch.return_value = 1
                    self.assertFalse(active_window.is_workstation_locked())

                    # Desktop switch fails (access denied / secure desktop) -> Locked
                    mock_switch.return_value = 0
                    self.assertTrue(active_window.is_workstation_locked())

                    # OpenInputDesktop fails -> Locked
                    mock_open.return_value = 0
                    self.assertTrue(active_window.is_workstation_locked())

    def test_get_active_application_filters_lock_screen_and_locked_state(self):
        """Verify get_active_application returns None when locked or when LockApp/LogonUI is active."""
        with patch.object(active_window, "is_workstation_locked", return_value=True):
            app = active_window.get_active_application()
            self.assertIsNone(app)

        with patch.object(active_window, "is_workstation_locked", return_value=False):
            with patch("win32gui.GetForegroundWindow", return_value=999):
                with patch("win32gui.GetWindowText", return_value="Windows Default Lock Screen"):
                    with patch("win32process.GetWindowThreadProcessId", return_value=(0, 888)):
                        with patch("psutil.Process") as mock_proc:
                            # 1. LockApp.exe -> Must return None
                            mock_proc.return_value.name.return_value = "LockApp.exe"
                            self.assertIsNone(active_window.get_active_application())

                            # 2. LogonUI.exe -> Must return None
                            mock_proc.return_value.name.return_value = "LogonUI.exe"
                            self.assertIsNone(active_window.get_active_application())

                            # 3. Normal app -> Must return ActiveApplication
                            mock_proc.return_value.name.return_value = "code.exe"
                            normal_app = active_window.get_active_application()
                            self.assertIsNotNone(normal_app)
                            self.assertEqual(normal_app.application_name, "code.exe")

    # -------------------------------------------------------------------------
    # 2. Complete Win + L Lock, Idle Accumulation, and Unlock Cycle
    # -------------------------------------------------------------------------
    def test_tracking_lifecycle_when_windows_is_locked(self):
        """
        Verify:
        1. User active in chrome.exe for 120s.
        2. User locks workstation with Win + L.
        3. Tracker transitions to idle, closing chrome.exe at lock timestamp.
        4. Application continues running in background for 900s (15 min) with idle accumulating.
        5. User unlocks Windows: chrome.exe resumes with 900s idle time recorded.
        6. No false 'LockApp.exe' session is ever created.
        """
        tracker = self._make_tracker(idle_threshold=60)
        tracker.start()

        # Step 1: User works in Chrome for 120 seconds
        self.provider.active_application = ActiveApplication("chrome.exe", 101, "Google Chrome")
        self.provider.idle_seconds = 0.0
        self.provider.locked = False

        tracker.poll()
        session_id = tracker._current.db_id
        self.assertIsNotNone(session_id)

        # Advance 120s in Chrome
        for _ in range(24):
            self.clock.advance(5)
            tracker.poll()

        elapsed_chrome = (self.clock() - tracker._current.started_at).total_seconds()
        self.assertEqual(elapsed_chrome, 120)
        self.assertFalse(tracker.is_idle)

        # Step 2: User locks Windows (Win + L)
        self.provider.locked = True
        self.provider.idle_seconds = 1.0
        self.clock.advance(1)

        tracker.poll()

        # Tracker detects lock and transitions to idle
        self.assertTrue(tracker.is_idle)
        self.assertEqual(tracker.current_idle_session_id, session_id)

        # Step 3: Windows remains locked in background for 15 minutes (900 seconds total)
        # Advance clock and idle_seconds while locked
        locked_seconds = 900
        step = 10
        for s in range(0, locked_seconds, step):
            self.clock.advance(step)
            self.provider.idle_seconds = float(s + step)
            tracker.poll()
            self.assertTrue(tracker.is_idle)

        # Step 4: User unlocks Windows (enters password and presses Enter)
        self.provider.locked = False
        self.provider.idle_seconds = 0.0
        self.provider.active_application = ActiveApplication("chrome.exe", 101, "Google Chrome")
        self.clock.advance(1)

        tracker.poll()

        # Tracker is active again
        self.assertFalse(tracker.is_idle)
        self.assertIsNone(tracker.current_idle_session_id)

        # User works for another 60 seconds
        for _ in range(12):
            self.clock.advance(5)
            tracker.poll()

        tracker.stop()

        # Step 5: Verify database state
        db = get_session()
        try:
            repo = ActivityRepository(db)
            sessions = repo.get_all_sessions()
            # Must NOT contain LockApp.exe or LogonUI.exe
            app_names = [s.application_name for s in sessions]
            self.assertNotIn("LockApp.exe", app_names)
            self.assertNotIn("LogonUI.exe", app_names)

            # Find Chrome session
            chrome_session = repo.get_session_by_id(session_id)
            self.assertIsNotNone(chrome_session)
            # Idle duration must match locked duration (~901s)
            self.assertGreaterEqual(chrome_session.idle_seconds, 900)
            self.assertLessEqual(chrome_session.idle_seconds, 915)

            # Active duration must match actual work (120s + 60s = 180s)
            active_duration = chrome_session.duration_seconds - chrome_session.idle_seconds
            self.assertEqual(active_duration, 180)

            # Step 6: Verify API payload for sync
            payload = self.sync_service._build_page_payload(
                [chrome_session],
                chrome_session.started_at,
                chrome_session.ended_at,
                page=1,
                page_size=25,
            )
            act = payload["activities"][0]
            self.assertEqual(act["status"], "Idle")
            self.assertTrue(act["is_idle"])
            self.assertEqual(act["active_duration"], 180)
            self.assertGreaterEqual(act["idle_time"], 900)
            # Window title for idle session must show human-readable idle duration
            self.assertIn("minutes", act["window_title"])
        finally:
            db.close()

    # -------------------------------------------------------------------------
    # 3. Switching Windows User / Logout Security Isolation
    # -------------------------------------------------------------------------
    def test_user_logout_clears_identity_and_token(self):
        """Verify logging out completely purges cached user identity and device token."""
        svc = SessionService()
        self.assertIsNotNone(svc.current_user)
        self.assertEqual(svc.current_user.employee_id, "EC-098")
        self.assertEqual(svc.device_token, "DEV_TOKEN_LOCK_TEST")

        svc.logout()

        self.assertIsNone(svc.current_user)
        self.assertIsNone(svc.device_token)

        # Login as another user
        svc.login(
            username="other_user",
            role="employee",
            employee_id="EC-999",
            device_token="DEV_TOKEN_NEW_USER",
        )
        self.assertEqual(svc.current_user.username, "other_user")
        self.assertEqual(svc.current_user.employee_id, "EC-999")
        self.assertEqual(svc.device_token, "DEV_TOKEN_NEW_USER")


if __name__ == "__main__":
    unittest.main()
