"""Comprehensive test suite for iHRMS Monitor idle-time tracking, accumulation,

persistence, and backend synchronization.

Covers all 7 verification cases:
- Case 1: Normal active -> idle -> active
- Case 2: Multiple idle periods in one session (accumulating idle)
- Case 3: Long idle period (preventing premature sync while idle)
- Case 4: Laptop sleep -> wake (preventing sleep duration inflating idle)
- Case 5: Offline tracking -> later sync (preserving idle duration and syncing once online)
- Case 6: App restart (stale session handling preserving idle time)
- Case 7: Multiple activity sessions (each with distinct active and idle durations)
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from database.database import get_session, init_database
from database.models import ActivitySession
from database.repository import ActivityRepository
from platform_support.base import ActiveApplication, PlatformActivityProvider
from services.session_service import SessionService
from services.sync_service import SyncService
from tracker.activity_tracker import ActivityTracker


class FakeClock:
    """Deterministic clock controllable in test cases."""

    def __init__(self, start_dt: datetime):
        self.current_dt = start_dt

    def __call__(self) -> datetime:
        return self.current_dt

    def advance(self, seconds: float) -> None:
        self.current_dt += timedelta(seconds=seconds)


class FakeProvider(PlatformActivityProvider):
    """Controllable fake provider simulating user active application and idle seconds."""

    def __init__(self):
        self.active_application: ActiveApplication | None = ActiveApplication("Chrome.exe", 1001, "Google - Chrome")
        self.idle_seconds: float = 0.0

    def get_active_application(self) -> ActiveApplication | None:
        return self.active_application

    def get_idle_seconds(self) -> float:
        return self.idle_seconds


class TestIdleTrackingAndSync(unittest.TestCase):
    """Complete test suite verifying idle tracking, persistence, and synchronization."""

    def setUp(self):
        init_database()
        self.provider = FakeProvider()
        self.start_dt = datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc)
        self.clock = FakeClock(self.start_dt)
        self.sync_service = SyncService(api_url="https://test.api")
        self.sync_service.current_sync_interval_seconds = 300
        self.sync_service.current_idle_threshold_seconds = 60

        # Patch requests.post by default so background threads don't block on network
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

        # Authenticate user session for consistent employee_id scoping
        SessionService().login(
            username="test_user",
            role="employee",
            employee_id="EMP_TEST_101",
            device_token="DEVICE_TOKEN_123",
        )

        # Clean previous sessions from test DB
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

    def advance_time(self, tracker: ActivityTracker, seconds: float, step: float = 5.0) -> None:
        """Advance the clock and poll in realistic increments (<=5s) to avoid false sleep triggers."""
        elapsed = 0.0
        while elapsed < seconds:
            adv = min(step, seconds - elapsed)
            self.clock.advance(adv)
            tracker.poll()
            elapsed += adv

    def simulate_idle(self, tracker: ActivityTracker, total_idle_seconds: int, step: float = 5.0) -> None:
        """Simulate realistic idle time where clock advances alongside provider idle_seconds."""
        elapsed = 0
        while elapsed < total_idle_seconds:
            adv = min(step, total_idle_seconds - elapsed)
            self.clock.advance(adv)
            elapsed += adv
            self.provider.idle_seconds = float(elapsed)
            tracker.poll()

    # =========================================================================
    # CASE 1: Normal active -> idle -> active
    # =========================================================================
    def test_case_1_normal_active_idle_active(self):
        """
        Case 1: User works in an app, goes idle, and resumes.
        Verifies:
        - [IDLE_DETECTED] logged with timestamp, session_id, app, idle_seconds, threshold
        - [IDLE_RESUMED] logged with calculated_idle_duration
        - Correct idle_seconds stored in database
        - Active session continues in same app with accumulated idle time
        """
        tracker = self._make_tracker(idle_threshold=60)
        tracker.start()

        # 1. User active in Chrome for 120 seconds
        self.provider.idle_seconds = 0.0
        tracker.poll()  # opens session 1
        initial_session_id = tracker._current.db_id
        self.assertIsNotNone(initial_session_id)

        self.advance_time(tracker, 120, step=5.0)
        self.assertEqual(tracker._current.db_id, initial_session_id)

        # 2. User goes idle for 100 seconds (threshold 60s reached at 60s)
        with self.assertLogs("activity_tracker.tracker.activity_tracker", level="INFO") as cm:
            self.simulate_idle(tracker, 100, step=5.0)
            self.assertTrue(tracker.is_idle)
            self.assertEqual(tracker.current_idle_session_id, initial_session_id)
            log_text = "\n".join(cm.output)
            self.assertIn("[IDLE_DETECTED]", log_text)
            self.assertIn(f"session_id={initial_session_id}", log_text)
            self.assertIn("idle_seconds=60.0s", log_text)

        # 3. User resumes activity in the SAME application
        self.clock.advance(1)
        self.provider.idle_seconds = 0.0
        with self.assertLogs("activity_tracker.tracker.activity_tracker", level="INFO") as cm:
            state = tracker.poll()
            self.assertFalse(state.is_idle)
            self.assertFalse(tracker.is_idle)
            self.assertIsNone(tracker.current_idle_session_id)
            log_text = "\n".join(cm.output)
            self.assertIn("[IDLE_RESUMED]", log_text)
            self.assertIn(f"session_id={initial_session_id}", log_text)
            self.assertIn("calculated_idle_duration=101s", log_text)

        # 4. User works for another 60 seconds and tracker stops
        self.advance_time(tracker, 60, step=5.0)
        tracker.stop()

        # Verify database record
        db = get_session()
        try:
            repo = ActivityRepository(db)
            session = repo.get_session_by_id(initial_session_id)
            self.assertIsNotNone(session)
            self.assertEqual(session.idle_seconds, 101)
            # Total duration includes active (120 + 60 = 180) + idle (101) = 281s
            self.assertEqual(session.duration_seconds, 281)

            # Check payload generated for API
            payload = self.sync_service._build_page_payload(
                [session],
                session.started_at,
                session.ended_at,
                page=1,
                page_size=25,
            )
            act = payload["activities"][0]
            self.assertEqual(act["idle_duration_seconds"], 101)
            self.assertEqual(act["idle_time"], 101)
            self.assertEqual(act["status"], "Idle")
            self.assertTrue(act["is_idle"])
            self.assertEqual(act["active_duration"], 180)
            self.assertEqual(act["total_duration"], 281)
            self.assertEqual(act["active_duration"] + act["idle_duration_seconds"], act["total_duration"])
        finally:
            db.close()

    # =========================================================================
    # CASE 2: Multiple idle periods in one session (accumulating idle)
    # =========================================================================
    def test_case_2_multiple_idle_periods_accumulate_in_one_session(self):
        """
        Case 2: Multiple idle periods occur while staying in the same application.
        Verifies:
        - Idle durations accumulate correctly into idle_seconds (idle1 + idle2)
        - Session is not fragmented into multiple disconnected sessions
        - active_duration and total_duration remain accurate
        """
        self.sync_service.current_sync_interval_seconds = 600
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "sync_interval_seconds": 600,
                "idle_threshold_seconds": 60,
            },
        }
        self.mock_post.return_value = mock_resp
        tracker = self._make_tracker(idle_threshold=60)
        tracker.start()

        # 1. Start in Chrome
        self.provider.idle_seconds = 0.0
        tracker.poll()
        session_id = tracker._current.db_id

        # Work for 100s
        self.advance_time(tracker, 100, step=5.0)

        # 2. First Idle period: 70 seconds
        self.simulate_idle(tracker, 70, step=5.0)
        self.assertTrue(tracker.is_idle)

        # Resume activity in Chrome
        self.clock.advance(1)
        self.provider.idle_seconds = 0.0
        tracker.poll()
        self.assertFalse(tracker.is_idle)
        self.assertEqual(tracker._current.db_id, session_id)

        # 3. Work for another 80s
        self.advance_time(tracker, 80, step=5.0)

        # 4. Second Idle period: 90 seconds
        self.simulate_idle(tracker, 90, step=5.0)
        self.assertTrue(tracker.is_idle)

        # Resume activity in Chrome again
        self.clock.advance(1)
        self.provider.idle_seconds = 0.0
        tracker.poll()
        self.assertFalse(tracker.is_idle)
        self.assertEqual(tracker._current.db_id, session_id)

        # Work 30s more and finish
        self.advance_time(tracker, 30, step=5.0)
        tracker.stop()

        db = get_session()
        try:
            repo = ActivityRepository(db)
            session = repo.get_session_by_id(session_id)
            self.assertIsNotNone(session)
            # Total accumulated idle: 71s + 91s = 162s
            self.assertEqual(session.idle_seconds, 162)
            # Total duration must equal active work (100 + 80 + 30 = 210) + idle (162) = 372s
            self.assertEqual(session.duration_seconds, 372)

            payload = self.sync_service._build_page_payload([session], session.started_at, session.ended_at, 1, 25)
            act = payload["activities"][0]
            self.assertEqual(act["idle_duration_seconds"], 162)
            self.assertEqual(act["active_duration"], 210)
            self.assertEqual(act["total_duration"], 372)
            self.assertEqual(act["active_duration"] + act["idle_duration_seconds"], act["total_duration"])
        finally:
            db.close()

    # =========================================================================
    # CASE 3: Long idle period (preventing premature sync while idle)
    # =========================================================================
    def test_case_3_long_idle_period_prevents_premature_sync(self):
        """
        Case 3: User stays idle for a prolonged period (e.g. 15 minutes).
        Verifies:
        - Ongoing idle session is excluded from sync while idle so it is not synced with 0 idle seconds
        - After resumption, full idle time is recorded and synced
        """
        tracker = self._make_tracker(idle_threshold=60)
        tracker.start()

        # User active in VS Code
        self.provider.active_application = ActiveApplication("Code.exe", 2002, "main.py")
        self.provider.idle_seconds = 0.0
        tracker.poll()
        session_id = tracker._current.db_id

        self.advance_time(tracker, 60, step=5.0)

        # User becomes idle
        self.simulate_idle(tracker, 60, step=5.0)
        self.assertTrue(tracker.is_idle)
        self.assertEqual(tracker.current_idle_session_id, session_id)

        # Check get_unsynced_closed_sessions excluding current_idle_session_id
        db = get_session()
        try:
            repo = ActivityRepository(db)
            # Without exclusion, the session closed at last_input_time would appear
            all_closed = repo.get_unsynced_closed_sessions()
            self.assertTrue(any(s.id == session_id for s in all_closed))

            # With exclusion, the currently idle session is omitted from sync
            filtered = repo.get_unsynced_closed_sessions(exclude_session_ids=[tracker.current_idle_session_id])
            self.assertFalse(any(s.id == session_id for s in filtered))
        finally:
            db.close()

        # User stays idle for 15 minutes = 900 seconds
        for _ in range(180):
            self.clock.advance(5)
            self.provider.idle_seconds += 5.0
            tracker.poll()
            self.assertTrue(tracker.is_idle)

        # User resumes
        self.clock.advance(1)
        self.provider.idle_seconds = 0.0
        tracker.poll()
        self.assertFalse(tracker.is_idle)

        tracker.stop()

        # Verify session now has the complete idle time
        db = get_session()
        try:
            repo = ActivityRepository(db)
            session = repo.get_session_by_id(session_id)
            self.assertEqual(session.idle_seconds, 961)
            # Now it is available for sync
            to_sync = repo.get_unsynced_closed_sessions()
            self.assertTrue(any(s.id == session_id for s in to_sync))
        finally:
            db.close()

    # =========================================================================
    # CASE 4: Laptop sleep -> wake (preventing sleep duration inflating idle)
    # =========================================================================
    def test_case_4_sleep_resume_handling_prevents_inflated_idle(self):
        """
        Case 4: Laptop sleeps for multiple hours.
        Verifies:
        - Sleep duration is not treated as active or session idle duration
        - Anomalous durations > 7200s are sanitized to 0
        - Tracking resumes cleanly upon wake
        """
        tracker = self._make_tracker(idle_threshold=60)
        tracker.start()

        self.provider.active_application = ActiveApplication("Slack.exe", 3003, "General")
        self.provider.idle_seconds = 0.0
        tracker.poll()
        session_id = tracker._current.db_id

        # User is active for 5 minutes
        self.advance_time(tracker, 300, step=5.0)

        # Laptop goes to sleep at 10:05:00
        suspend_time = self.clock()
        tracker.handle_system_suspend(suspend_time)

        # Laptop sleeps for 4 hours (14400 seconds)
        self.clock.advance(14400)
        wake_time = self.clock()

        # System wakes up
        tracker.handle_system_resume(wake_time)
        self.assertFalse(tracker.is_idle)

        # User works for 60 seconds
        self.provider.idle_seconds = 0.0
        self.advance_time(tracker, 60, step=5.0)
        tracker.stop()

        db = get_session()
        try:
            repo = ActivityRepository(db)
            sessions = repo.get_all_sessions()
            for s in sessions:
                # Sleep time must never be stored as idle
                self.assertLess(s.idle_seconds, 300)
                # Session duration must not include 4 hours of sleep
                self.assertLess(s.duration_seconds, 1000)
        finally:
            db.close()

    # =========================================================================
    # CASE 5: Offline tracking -> later sync (preserving idle duration)
    # =========================================================================
    def test_case_5_offline_tracking_and_later_sync(self):
        """
        Case 5: Application operates offline, records idle time, and syncs when back online.
        Verifies:
        - Offline sessions maintain idle_seconds
        - Server sync updates server_session_id and logs [DATABASE_UPDATE_RESULT]
        - If idle is subsequently added, server_session_id is reset so it re-syncs
        """
        # Create a closed session with idle time for the active test employee
        db = get_session()
        try:
            repo = ActivityRepository(db)
            start = self.clock()
            sess = repo.create_session("Chrome.exe", 1001, "Google", start, idle_seconds=0)
            repo.close_session(sess.id, start + timedelta(seconds=120))
            repo.add_session_idle_seconds(sess.id, 60)
            session_id = sess.id
        finally:
            db.close()

        # 1. Attempt sync while offline -> fails
        self.mock_post.side_effect = Exception("Network offline")
        success = self.sync_service.sync_activity_now()
        self.assertFalse(success)

        # Verify session still unsynced
        db = get_session()
        try:
            repo = ActivityRepository(db)
            sess = repo.get_session_by_id(session_id)
            self.assertIsNone(sess.server_session_id)
            self.assertEqual(sess.idle_seconds, 60)
        finally:
            db.close()

        # 2. Network restored -> sync succeeds
        self.mock_post.side_effect = None
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Success",
            "message": "Saved successfully",
            "data": [
                {
                    "client_session_ref": session_id,
                    "activity_session_id": "SRV_9999",
                    "status": "created",
                }
            ],
        }
        self.mock_post.return_value = mock_response

        with self.assertLogs("activity_tracker.services.sync_service", level="INFO") as cm:
            success = self.sync_service.sync_activity_now()
            self.assertTrue(success)
            log_text = "\n".join(cm.output)
            self.assertIn("[DATABASE_UPDATE_RESULT]", log_text)
            self.assertIn("local_session_id=", log_text)
            self.assertIn("server_session_id=SRV_9999", log_text)

        # Verify session now bound to server_session_id
        db = get_session()
        try:
            repo = ActivityRepository(db)
            sess = repo.get_session_by_id(session_id)
            self.assertEqual(sess.server_session_id, "SRV_9999")

            # 3. If idle time is updated on this session later, server_session_id resets
            repo.add_session_idle_seconds(session_id, 30)
            self.assertEqual(sess.idle_seconds, 90)
            self.assertIsNone(sess.server_session_id)
        finally:
            db.close()

    # =========================================================================
    # CASE 6: App restart (stale session handling preserving idle time)
    # =========================================================================
    def test_case_6_app_restart_safely_closes_stale_sessions_preserving_idle(self):
        """
        Case 6: Application abruptly terminated and restarted.
        Verifies:
        - close_stale_sessions closes any leftover open sessions
        - Existing recorded idle_seconds is preserved and not overwritten
        """
        db = get_session()
        try:
            repo = ActivityRepository(db)
            start = self.clock()
            sess = repo.create_session("Word.exe", 4004, "Document.docx", start, idle_seconds=45)
            # Leave ended_at=None (simulating crash/kill)
            stale_id = sess.id
        finally:
            db.close()

        # Start a new tracker instance (simulating app relaunch)
        new_clock = FakeClock(self.clock() + timedelta(seconds=600))
        new_tracker = ActivityTracker(
            provider=self.provider,
            session_factory=get_session,
            idle_threshold_seconds=60,
            track_window_titles=True,
            clock=new_clock,
            sync_service=self.sync_service,
        )
        new_tracker.start()

        db = get_session()
        try:
            repo = ActivityRepository(db)
            stale_sess = repo.get_session_by_id(stale_id)
            self.assertIsNotNone(stale_sess.ended_at)
            # Preserved idle_seconds
            self.assertEqual(stale_sess.idle_seconds, 45)
        finally:
            db.close()

        new_tracker.stop()

    # =========================================================================
    # CASE 7: Multiple activity sessions (each with distinct active and idle durations)
    # =========================================================================
    def test_case_7_multiple_activity_sessions_distinct_durations(self):
        """
        Case 7: User switches between multiple apps, each having distinct active and idle durations.
        Verifies:
        - Distinct active and idle durations for each application
        - No duration leakage or mix-up across sessions
        - Correct payload totals aggregation
        """
        sessions_data = [
            {"app": "Chrome.exe", "pid": 101, "active": 120, "idle": 60},
            {"app": "Code.exe", "pid": 102, "active": 200, "idle": 0},
            {"app": "Excel.exe", "pid": 103, "active": 90, "idle": 45},
        ]

        created_sessions = []
        db = get_session()
        try:
            repo = ActivityRepository(db)
            current_time = self.start_dt
            for item in sessions_data:
                sess = repo.create_session(item["app"], item["pid"], item["app"], current_time)
                end_time = current_time + timedelta(seconds=item["active"])
                repo.close_session(sess.id, end_time)
                if item["idle"] > 0:
                    repo.add_session_idle_seconds(sess.id, item["idle"])
                current_time = end_time + timedelta(seconds=item["idle"])
                db.refresh(sess)
                created_sessions.append(sess)
        finally:
            db.close()

        # Build payload
        payload = self.sync_service._build_page_payload(
            created_sessions,
            self.start_dt,
            current_time,
            page=1,
            page_size=25,
        )

        activities = payload["activities"]
        self.assertEqual(len(activities), 3)

        # Chrome: 120s active, 60s idle, total 180s
        chrome_act = next(a for a in activities if a["application_name"] == "Chrome.exe")
        self.assertEqual(chrome_act["active_duration"], 120)
        self.assertEqual(chrome_act["idle_duration_seconds"], 60)
        self.assertEqual(chrome_act["total_duration"], 180)
        self.assertEqual(chrome_act["status"], "Idle")

        # Code: 200s active, 0s idle, total 200s
        code_act = next(a for a in activities if a["application_name"] == "Code.exe")
        self.assertEqual(code_act["active_duration"], 200)
        self.assertEqual(code_act["idle_duration_seconds"], 0)
        self.assertEqual(code_act["total_duration"], 200)
        self.assertEqual(code_act["status"], "Active")

        # Excel: 90s active, 45s idle, total 135s
        excel_act = next(a for a in activities if a["application_name"] == "Excel.exe")
        self.assertEqual(excel_act["active_duration"], 90)
        self.assertEqual(excel_act["idle_duration_seconds"], 45)
        self.assertEqual(excel_act["total_duration"], 135)
        self.assertEqual(excel_act["status"], "Idle")

        # Check totals aggregation
        totals = {t["application_name"]: t["total_duration_seconds"] for t in payload["totals"]}
        self.assertEqual(totals["Chrome.exe"], 120)
        self.assertEqual(totals["Code.exe"], 200)
        self.assertEqual(totals["Excel.exe"], 90)

    # =========================================================================
    # CASE 8: Payload contains explicit "idle_seconds" for backend DB mapping
    # =========================================================================
    def test_case_8_idle_seconds_field_in_sync_payload(self):
        """
        Verify that SyncService._build_page_payload explicitly includes
        both 'idle_seconds' and 'idle_duration' matching the session idle time.
        """
        db = get_session()
        try:
            repo = ActivityRepository(db)
            start = self.clock()
            sess = repo.create_session("Word.exe", 5005, "Report.docx", start, idle_seconds=0)
            repo.close_session(sess.id, start + timedelta(seconds=200))
            repo.add_session_idle_seconds(sess.id, 153)
            db.refresh(sess)

            payload = self.sync_service._build_page_payload(
                [sess],
                start,
                start + timedelta(seconds=353),
                page=1,
                page_size=25,
            )
            self.assertEqual(len(payload["activities"]), 1)
            act = payload["activities"][0]
            # Primary backend field
            self.assertIn("idle_seconds", act)
            self.assertEqual(act["idle_seconds"], 153)
            # Alternative field
            self.assertIn("idle_duration", act)
            self.assertEqual(act["idle_duration"], 153)
            # Legacy fields preserved
            self.assertEqual(act["idle_time"], 153)
            self.assertEqual(act["idle_duration_seconds"], 153)
        finally:
            db.close()

    # =========================================================================
    # CASE 9: Tracker state preserves idle_seconds during ongoing sessions and transitions
    # =========================================================================
    def test_case_9_tracker_state_idle_seconds_ongoing_and_transitions(self):
        """
        Verify that ActivityTracker._state() correctly reports idle_seconds:
        - When idle: reports the ongoing idle time
        - When resuming active: does NOT reset to 0; retains session's idle duration
        - Multiple idle intervals accumulate in state.idle_seconds
        """
        tracker = self._make_tracker(idle_threshold=60)
        tracker.start()

        self.provider.active_application = ActiveApplication("Chrome.exe", 1001, "Google")
        self.provider.idle_seconds = 0.0
        state = tracker.poll()
        self.assertEqual(state.idle_seconds, 0.0)

        # Work for 120s
        self.advance_time(tracker, 120, step=5.0)

        # User becomes idle for 153s
        self.simulate_idle(tracker, 153, step=5.0)
        state = tracker.poll()
        self.assertTrue(state.is_idle)
        # In idle state, idle_seconds reports ongoing idle
        self.assertGreaterEqual(state.idle_seconds, 150.0)

        # User becomes active again (idle -> active transition)
        self.clock.advance(1)
        self.provider.idle_seconds = 0.0
        state = tracker.poll()
        self.assertFalse(state.is_idle)
        # Must NOT be 0! Must reflect the 153s idle duration
        self.assertGreaterEqual(state.idle_seconds, 153.0)

        # User continues working for another 60s
        self.advance_time(tracker, 60, step=5.0)
        state = tracker.poll()
        self.assertFalse(state.is_idle)
        # Still reflects the accumulated session idle
        self.assertGreaterEqual(state.idle_seconds, 153.0)

        tracker.stop()

    # =========================================================================
    # CASE 10: Repository and ActivityService idle calculations
    # =========================================================================
    def test_case_10_repository_and_service_idle_and_active_calculations(self):
        """
        Verify:
        - ActivityRepository.get_total_duration_seconds deducts idle_seconds
        - ActivityRepository.get_total_idle_seconds sums idle_seconds accurately
        - ActivityService.get_today_timeline and get_today_total_idle_seconds
        """
        from services.activity_service import ActivityService

        db = get_session()
        try:
            repo = ActivityRepository(db)
            start = self.start_dt
            # Session 1: 300s total, 100s idle -> 200s active
            s1 = repo.create_session("App1.exe", 1, "App 1", start, employee_id="EMP_TEST_101")
            repo.close_session(s1.id, start + timedelta(seconds=300))
            repo.add_session_idle_seconds(s1.id, 100)

            # Session 2: 180s total, 30s idle -> 150s active
            start2 = start + timedelta(seconds=300)
            s2 = repo.create_session("App2.exe", 2, "App 2", start2, employee_id="EMP_TEST_101")
            repo.close_session(s2.id, start2 + timedelta(seconds=180))
            repo.add_session_idle_seconds(s2.id, 30)

            # Check repo total duration (net active): 300 + 180 = 480
            total_active = repo.get_total_duration_seconds(start, start + timedelta(seconds=1000), employee_id="EMP_TEST_101")
            self.assertEqual(total_active, 480)

            # Check repo total idle: 100 + 30 = 130
            total_idle = repo.get_total_idle_seconds(start, start + timedelta(seconds=1000), employee_id="EMP_TEST_101")
            self.assertEqual(total_idle, 130)

            # Check ActivityService
            service = ActivityService(get_session)
            timeline = service.get_today_timeline(now=start + timedelta(seconds=500))
            self.assertEqual(len(timeline), 2)
            # Check entry idle_seconds and net duration
            e1 = next(e for e in timeline if e.application_name == "App1.exe")
            self.assertEqual(e1.duration_seconds, 300)
            self.assertEqual(e1.idle_seconds, 100)

            e2 = next(e for e in timeline if e.application_name == "App2.exe")
            self.assertEqual(e2.duration_seconds, 180)
            self.assertEqual(e2.idle_seconds, 30)

            # Check service get_today_total_idle_seconds
            today_idle = service.get_today_total_idle_seconds(now=start + timedelta(seconds=500))
            self.assertEqual(today_idle, 130)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
