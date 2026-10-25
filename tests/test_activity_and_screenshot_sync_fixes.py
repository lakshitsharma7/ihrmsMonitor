import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from database.database import get_session
from database.models import ActivitySession
from database.repository import ActivityRepository
from services.sync_service import SyncService, DEFAULT_API_HEADERS


class TestActivityAndScreenshotSyncFixes(unittest.TestCase):
    def setUp(self):
        self.sync_service = SyncService(api_url="https://test.server/ci4/api")

    @patch("requests.post")
    def test_fetch_settings_sends_standard_headers(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Success", "data": {"sync_interval_seconds": 120}}
        mock_post.return_value = mock_resp

        with patch.object(self.sync_service, "_require_device_token", return_value="dummy_token_123"):
            res = self.sync_service.fetch_settings()

        self.assertTrue(mock_post.called)
        _, kwargs = mock_post.call_args
        self.assertIn("headers", kwargs)
        self.assertEqual(kwargs["headers"]["Accept"], DEFAULT_API_HEADERS["Accept"])
        self.assertEqual(kwargs["headers"]["User-Agent"], DEFAULT_API_HEADERS["User-Agent"])

    @patch("requests.post")
    def test_save_activity_batch_sends_standard_headers(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Success", "data": []}
        mock_post.return_value = mock_resp

        payload = {"device_token": "dummy_token_123", "sessions": "[]"}
        res = self.sync_service._send_request_with_retry(payload, page=1, retries=1)

        self.assertTrue(mock_post.called)
        _, kwargs = mock_post.call_args
        self.assertIn("headers", kwargs)
        self.assertEqual(kwargs["headers"]["Accept"], DEFAULT_API_HEADERS["Accept"])
        self.assertEqual(kwargs["headers"]["User-Agent"], DEFAULT_API_HEADERS["User-Agent"])

    @patch("requests.post")
    def test_upload_screenshot_sends_standard_headers_and_accepts_token(self, mock_post, tmp_path_factory=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Success", "data": {"screenshot_id": "999"}}
        mock_post.return_value = mock_resp

        # Create a dummy screenshot file in scratch or temp
        test_file = Path("test_shot_dummy.png")
        test_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")
        try:
            success = self.sync_service.upload_screenshot_now(
                screenshot_path=test_file,
                activity_session_id="7777",
                application_name="test.exe",
                process_id=1234,
                device_token="explicit_device_token_xyz",
            )
            self.assertTrue(success)
            self.assertTrue(mock_post.called)
            _, kwargs = mock_post.call_args
            self.assertIn("headers", kwargs)
            self.assertEqual(kwargs["headers"]["Accept"], DEFAULT_API_HEADERS["Accept"])
            self.assertEqual(kwargs["headers"]["User-Agent"], DEFAULT_API_HEADERS["User-Agent"])
            self.assertEqual(kwargs["data"]["device_token"], "explicit_device_token_xyz")
        finally:
            if test_file.exists():
                test_file.unlink()

    @patch.object(SyncService, "fetch_settings", return_value={})
    @patch.object(SyncService, "_send_request_with_retry")
    def test_sync_activity_now_with_explicit_context(self, mock_send, mock_settings):
        mock_send.return_value = {
            "response": "Success",
            "data": [{"client_session_ref": 99999, "activity_session_id": "8888", "status": "saved"}]
        }

        # Create an unsynced closed session in db for target emp
        db = get_session()
        try:
            repo = ActivityRepository(db)
            sess = repo.create_session(
                application_name="explicit_test.exe",
                process_id=999,
                window_title="Test Explicit",
                started_at=datetime.now(timezone.utc),
                employee_id="EXPLICIT_EMP_01",
            )
            sess_id = sess.id
            repo.close_session(sess_id, datetime.now(timezone.utc), 10)
        finally:
            db.close()

        try:
            success = self.sync_service.sync_activity_now(
                device_token="token_flush_override",
                employee_id="EXPLICIT_EMP_01",
            )
            self.assertTrue(success)
            self.assertTrue(mock_send.called)
            payload_sent = mock_send.call_args[0][0]
            self.assertEqual(payload_sent["device_token"], "token_flush_override")
        finally:
            # Clean up db record
            db = get_session()
            try:
                rec = db.get(ActivitySession, sess_id)
                if rec:
                    db.delete(rec)
                    db.commit()
            finally:
                db.close()

    @patch("tracker.activity_tracker.capture_screenshot")
    def test_screenshot_timer_checkpoints_session_when_screenshot_already_present(self, mock_capture):
        from platform_support.base import ActiveApplication, PlatformActivityProvider
        from tracker.activity_tracker import ActivityTracker
        from datetime import timedelta

        class DummyClock:
            def __init__(self):
                self.now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
            def __call__(self):
                return self.now
            def advance(self, s):
                self.now += timedelta(seconds=s)

        class DummyProvider(PlatformActivityProvider):
            def get_active_application(self):
                return ActiveApplication("Word.exe", 2000, "Document 1 - Word")
            def get_idle_seconds(self):
                return 0.0

        mock_capture.side_effect = lambda activity_session_id=None: f"C:/dummy/session_{activity_session_id}.png"

        clock = DummyClock()
        provider = DummyProvider()
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=300,
            clock=clock,
            screenshot_interval_type="custom",
            screenshot_custom_interval_seconds=60,
            capture_on_switch=True,
        )

        created_sessions = []
        try:
            tracker.start()
            tracker.poll()  # Session 1 created with initial screenshot
            sess1_id = tracker._current.db_id
            created_sessions.append(sess1_id)

            # Verify session 1 has screenshot in db
            db = get_session()
            try:
                rec1 = db.get(ActivitySession, sess1_id)
                self.assertIsNotNone(rec1.screenshot_path)
                self.assertIn(f"session_{sess1_id}", rec1.screenshot_path)
            finally:
                db.close()

            # Advance clock past interval
            clock.advance(65)
            tracker.poll()  # Periodic capture triggered

            sess2_id = tracker._current.db_id
            created_sessions.append(sess2_id)

            # Session 1 must have been closed with its screenshot intact
            # Session 2 must be open with its own screenshot
            self.assertNotEqual(sess1_id, sess2_id)

            db = get_session()
            try:
                rec1_after = db.get(ActivitySession, sess1_id)
                rec2_after = db.get(ActivitySession, sess2_id)
                self.assertIsNotNone(rec1_after.ended_at)
                self.assertIsNotNone(rec1_after.screenshot_path)
                self.assertIsNotNone(rec2_after.screenshot_path)
                self.assertNotEqual(rec1_after.screenshot_path, rec2_after.screenshot_path)
            finally:
                db.close()

        finally:
            tracker.stop()
            db = get_session()
            try:
                for sid in created_sessions:
                    rec = db.get(ActivitySession, sid)
                    if rec:
                        db.delete(rec)
                db.commit()
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()

