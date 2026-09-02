"""Tests for multi-user session isolation and tracking data separation."""

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, ActivitySession
from database.repository import ActivityRepository
from services.session_service import SessionService
from services.sync_service import SyncService
from services.activity_service import ActivityService


class TestMultiUserTrackingFlow(unittest.TestCase):
    """Test suite ensuring strict multi-user separation in iHRMS Monitor."""

    def setUp(self):
        # Create an in-memory SQLite database for testing
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionFactory = sessionmaker(bind=self.engine)
        self.db = self.SessionFactory()

        # Ensure clean session service
        SessionService().clear()
        SyncService.reset_sync_state()

    def tearDown(self):
        self.db.close()
        SessionService().clear()
        SyncService.reset_sync_state()

    def test_session_service_does_not_inherit_previous_user_token(self):
        """Verify that User B never inherits User A's device token or employee ID."""
        session_svc = SessionService()

        # User A logs in
        session_svc.login(
            username="user_a",
            role="User",
            full_name="User Alpha",
            employee_id="EMP_001",
            company_code="CMP_IND",
            device_token="TOKEN_ALPHA_123",
        )
        self.assertEqual(session_svc.device_token, "TOKEN_ALPHA_123")
        self.assertEqual(session_svc.current_user.employee_id, "EMP_001")

        # User A logs out
        session_svc.logout()
        self.assertIsNone(session_svc.current_user)
        self.assertIsNone(session_svc.device_token)

        # User B logs in with their own token
        session_svc.login(
            username="user_b",
            role="User",
            full_name="User Beta",
            employee_id="EMP_002",
            company_code="CMP_IND",
            device_token="TOKEN_BETA_456",
        )
        self.assertEqual(session_svc.device_token, "TOKEN_BETA_456")
        self.assertEqual(session_svc.current_user.employee_id, "EMP_002")
        self.assertNotEqual(session_svc.device_token, "TOKEN_ALPHA_123")

    def test_activity_sessions_strictly_scoped_by_employee_id(self):
        """Verify that sessions created under User A and User B have separate employee_ids and sync queries."""
        session_svc = SessionService()
        repo = ActivityRepository(self.db)
        now = datetime.now(timezone.utc)

        # 1. User A is active
        session_svc.login(
            username="user_a",
            role="User",
            employee_id="EMP_001",
            device_token="TOKEN_A",
        )

        sess_a1 = repo.create_session(
            application_name="Code.exe",
            process_id=1001,
            window_title="Project A",
            started_at=now - timedelta(minutes=30),
        )
        # Close session A1
        repo.close_session(sess_a1.id, ended_at=now - timedelta(minutes=15))

        # Verify sess_a1 has EMP_001
        self.assertEqual(sess_a1.employee_id, "EMP_001")

        # Query unsynced sessions for User A
        unsynced_a = repo.get_unsynced_closed_sessions(employee_id="EMP_001")
        self.assertEqual(len(unsynced_a), 1)
        self.assertEqual(unsynced_a[0].id, sess_a1.id)

        # 2. User A logs out
        session_svc.logout()

        # When no user is active and employee_id is not passed, query returns empty list
        unsynced_none = repo.get_unsynced_closed_sessions()
        self.assertEqual(len(unsynced_none), 0)

        # 3. User B logs in
        session_svc.login(
            username="user_b",
            role="User",
            employee_id="EMP_002",
            device_token="TOKEN_B",
        )

        # Before User B does any work, User B's unsynced list is empty
        unsynced_b = repo.get_unsynced_closed_sessions(employee_id="EMP_002")
        self.assertEqual(len(unsynced_b), 0)

        # Automatic employee_id resolution from current_user also returns empty for User B
        unsynced_b_auto = repo.get_unsynced_closed_sessions()
        self.assertEqual(len(unsynced_b_auto), 0)

        # User B tracks an activity
        sess_b1 = repo.create_session(
            application_name="Chrome.exe",
            process_id=2002,
            window_title="Documentation",
            started_at=now - timedelta(minutes=10),
        )
        repo.close_session(sess_b1.id, ended_at=now)

        # Verify sess_b1 has EMP_002
        self.assertEqual(sess_b1.employee_id, "EMP_002")

        # User B now has 1 unsynced session; User A's session is NOT included
        unsynced_b_after = repo.get_unsynced_closed_sessions(employee_id="EMP_002")
        self.assertEqual(len(unsynced_b_after), 1)
        self.assertEqual(unsynced_b_after[0].id, sess_b1.id)
        self.assertEqual(unsynced_b_after[0].employee_id, "EMP_002")

        # User A's unsynced session remains untouched and separate
        unsynced_a_check = repo.get_unsynced_closed_sessions(employee_id="EMP_001")
        self.assertEqual(len(unsynced_a_check), 1)
        self.assertEqual(unsynced_a_check[0].id, sess_a1.id)

    def test_dashboard_views_isolate_user_activities(self):
        """Verify that ActivityService timeline and duration only display the logged-in user's data."""
        session_svc = SessionService()
        repo = ActivityRepository(self.db)
        now = datetime.now(timezone.utc)

        # Setup User A with 1 session of 1200 seconds
        session_svc.login(username="user_a", role="User", employee_id="EMP_001", device_token="TOKEN_A")
        s_a = repo.create_session(
            application_name="AppAlpha.exe",
            process_id=111,
            window_title="Alpha Window",
            started_at=now - timedelta(minutes=40),
        )
        repo.close_session(s_a.id, ended_at=now - timedelta(minutes=20))

        activity_svc = ActivityService(lambda: self.SessionFactory())

        # While User A is logged in, timeline shows 1 entry
        timeline_a = activity_svc.get_today_timeline(now)
        self.assertEqual(len(timeline_a), 1)
        self.assertEqual(timeline_a[0].application_name, "AppAlpha.exe")

        # User A logs out, User B logs in
        session_svc.logout()
        session_svc.login(username="user_b", role="User", employee_id="EMP_002", device_token="TOKEN_B")

        # User B has no recorded activities yet
        timeline_b = activity_svc.get_today_timeline(now)
        self.assertEqual(len(timeline_b), 0)

        # User B tracks an activity
        s_b = repo.create_session(
            application_name="AppBeta.exe",
            process_id=222,
            window_title="Beta Window",
            started_at=now - timedelta(minutes=15),
        )
        repo.close_session(s_b.id, ended_at=now - timedelta(minutes=5))

        # User B's timeline now shows AppBeta.exe only
        timeline_b_after = activity_svc.get_today_timeline(now)
        self.assertEqual(len(timeline_b_after), 1)
        self.assertEqual(timeline_b_after[0].application_name, "AppBeta.exe")

        # Usage summary for User B contains only AppBeta
        usage_b = activity_svc.get_today_application_usage(now)
        self.assertEqual(len(usage_b), 1)
        self.assertEqual(usage_b[0].application_name, "AppBeta.exe")
        self.assertEqual(usage_b[0].total_seconds, 600)

    def test_sync_service_require_device_token_multi_user(self):
        """Verify _require_device_token returns the active user's token and ignores previous session data."""
        session_svc = SessionService()

        # When no user is active, return None
        token = SyncService._require_device_token()
        self.assertIsNone(token)

        # Set User A
        session_svc.login(
            username="user_a",
            role="User",
            employee_id="EMP_001",
            device_token="TOKEN_A",
        )
        self.assertEqual(SyncService._require_device_token(), "TOKEN_A")

        # Switch to User B
        session_svc.logout()
        session_svc.login(
            username="user_b",
            role="User",
            employee_id="EMP_002",
            device_token="TOKEN_B",
        )
        self.assertEqual(SyncService._require_device_token(), "TOKEN_B")

    def test_screenshot_upload_query_scoped_by_employee(self):
        """Verify unuploaded screenshots query only returns screenshots belonging to the specified employee."""
        session_svc = SessionService()
        repo = ActivityRepository(self.db)
        now = datetime.now(timezone.utc)

        # Session for User A with screenshot
        session_svc.login(username="user_a", role="User", employee_id="EMP_001", device_token="TOKEN_A")
        sess_a = repo.create_session(
            application_name="AppA.exe",
            process_id=10,
            window_title="WinA",
            started_at=now - timedelta(minutes=30),
        )
        repo.close_session(sess_a.id, ended_at=now - timedelta(minutes=20))
        repo.update_session_server_id(sess_a.id, "SERVER_SESS_A")
        repo.update_session_screenshot_path(sess_a.id, "C:/screenshots/session_a.png")

        # Session for User B with screenshot
        session_svc.logout()
        session_svc.login(username="user_b", role="User", employee_id="EMP_002", device_token="TOKEN_B")
        sess_b = repo.create_session(
            application_name="AppB.exe",
            process_id=20,
            window_title="WinB",
            started_at=now - timedelta(minutes=10),
        )
        repo.close_session(sess_b.id, ended_at=now)
        repo.update_session_server_id(sess_b.id, "SERVER_SESS_B")
        repo.update_session_screenshot_path(sess_b.id, "C:/screenshots/session_b.png")

        # Query User B unuploaded screenshots
        unuploaded_b = repo.get_sessions_with_unuploaded_screenshots(employee_id="EMP_002")
        self.assertEqual(len(unuploaded_b), 1)
        self.assertEqual(unuploaded_b[0].id, sess_b.id)
        self.assertEqual(unuploaded_b[0].employee_id, "EMP_002")

        # Query User A unuploaded screenshots
        unuploaded_a = repo.get_sessions_with_unuploaded_screenshots(employee_id="EMP_001")
        self.assertEqual(len(unuploaded_a), 1)
        self.assertEqual(unuploaded_a[0].id, sess_a.id)
        self.assertEqual(unuploaded_a[0].employee_id, "EMP_001")


if __name__ == "__main__":
    unittest.main()
