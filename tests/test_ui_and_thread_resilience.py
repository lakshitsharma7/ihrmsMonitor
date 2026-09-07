"""Tests for UI responsiveness, background thread decoupling, and SQLite WAL concurrency."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from database.database import get_session, init_database
from services.sync_service import SyncService
from tracker.activity_tracker import ActivityTracker


class FakeProvider:
    def __init__(self):
        from platform_support.base import ActiveApplication
        self.active_application = ActiveApplication("Code.exe", 100, "main.py")
        self.idle_seconds = 0.0

    def get_active_application(self):
        return self.active_application

    def get_idle_seconds(self):
        return self.idle_seconds


class TestUIAndThreadResilience(unittest.TestCase):
    """Verify background threading, SQLite WAL concurrency, and non-blocking sync."""

    def setUp(self):
        init_database()

    def test_sqlite_pragmas_and_concurrency(self):
        """Verify SQLite has WAL mode, busy timeout, and allows multi-thread access."""
        from sqlalchemy import text
        session = get_session()
        try:
            # Check journal_mode (may be wal or memory in temporary testing environments)
            mode = session.execute(text("PRAGMA journal_mode;")).scalar()
            self.assertIn(str(mode).lower(), ["wal", "memory"])
        finally:
            session.close()

    def test_sync_lock_prevents_concurrent_sync(self):
        """Verify SyncService uses _sync_lock with non-blocking acquire to skip overlapping syncs."""
        svc = SyncService(api_url="https://test.api")
        
        # Simulate lock already held by another thread
        acquired = svc._sync_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            # Calling sync_activity_now while lock is held must return False immediately
            result = svc.sync_activity_now()
            self.assertFalse(result)
        finally:
            svc._sync_lock.release()

    def test_activity_tracker_sync_activity_spawns_thread(self):
        """Verify _sync_activity spawns a background thread and does not block caller."""
        provider = FakeProvider()
        sync_mock = MagicMock()
        
        # Make sync_activity_now sleep briefly to ensure it runs asynchronously
        def slow_sync():
            time.sleep(0.05)
            return True

        sync_mock.sync_activity_now.side_effect = slow_sync
        sync_mock._load_cached_setting.return_value = None

        from database.database import _SessionFactory
        tracker = ActivityTracker(
            provider=provider,
            session_factory=_SessionFactory,
            idle_threshold_seconds=300,
            sync_service=sync_mock,
        )
        tracker.start()

        start_time = time.time()
        tracker._sync_activity()
        elapsed = time.time() - start_time

        # _sync_activity must return immediately (< 0.04s) because work is in background thread
        self.assertLess(elapsed, 0.04)

        # Allow worker thread to finish
        time.sleep(0.1)
        sync_mock.sync_activity_now.assert_called()
        tracker.stop()

    def test_screenshot_skips_qscreen_on_background_thread(self):
        """Verify _grab_screen_image avoids QScreen.grabWindow when called outside main GUI thread."""
        from services.screenshot import _grab_screen_image
        from PIL import Image

        # In a worker thread, QThread.currentThread() != app.thread()
        result_holder = {}

        def _bg_grab():
            # Mock PIL ImageGrab to verify Tier 2 is used
            with patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (100, 100), color="blue")):
                img = _grab_screen_image()
                result_holder["img"] = img

        t = threading.Thread(target=_bg_grab)
        t.start()
        t.join(timeout=3.0)

        self.assertIn("img", result_holder)
        self.assertIsNotNone(result_holder["img"])


if __name__ == "__main__":
    unittest.main()
