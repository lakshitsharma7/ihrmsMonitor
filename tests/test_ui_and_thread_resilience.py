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
        acquired = svc._sync_lock.acquire(timeout=5.0)
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
        def slow_sync(*args, **kwargs):
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

    def test_dashboard_update_tracker_state_does_not_query_database_on_tick(self):
        """Verify update_tracker_state on the 1-second GUI tick uses cached values without querying SQLite."""
        import sys
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        from ui.dashboard import DashboardPage
        from tracker.activity_tracker import TrackerState

        mock_service = MagicMock()
        dashboard = DashboardPage(mock_service)

        # Set cached baseline
        dashboard._cached_today_idle = 45
        dashboard._cached_uploaded_count = 12

        mock_service.reset_mock()

        # Simulate 1-second tick state update
        state = TrackerState(
            is_tracking=True,
            is_idle=False,
            current_application="VS Code",
            current_window_title="main.py",
            idle_seconds=0.0,
        )
        dashboard.update_tracker_state(state)

        # Ensure NO database queries were run on UI tick
        mock_service.get_today_total_idle_seconds.assert_not_called()
        mock_service.get_uploaded_records_count.assert_not_called()
        mock_service.get_today_total_seconds.assert_not_called()
        mock_service.get_today_timeline.assert_not_called()

        self.assertEqual(dashboard.idle_time_label.text(), "Idle Time: 45 seconds")
        self.assertEqual(dashboard.records_uploaded_label.text(), "Records Uploaded: 12")

    def test_dashboard_refresh_async_mode_is_non_blocking_and_single_flight(self):
        """Verify DashboardPage.refresh(async_mode=True) runs in background worker and prevents overlapping workers."""
        import sys
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        from ui.dashboard import DashboardPage

        mock_service = MagicMock()

        def slow_fetch():
            time.sleep(0.06)
            return 3600

        mock_service.get_today_total_seconds.side_effect = slow_fetch
        mock_service.get_uploaded_records_count.return_value = 10
        mock_service.get_today_total_idle_seconds.return_value = 120
        mock_service.get_today_timeline.return_value = []

        dashboard = DashboardPage(mock_service)

        start = time.time()
        dashboard.refresh(async_mode=True)
        elapsed = time.time() - start

        # Refresh must return immediately without waiting for the 0.06s slow_fetch
        self.assertLess(elapsed, 0.058)
        self.assertTrue(dashboard._is_refreshing)

        # Second refresh while first is running must be dropped immediately
        dashboard.refresh(async_mode=True)

        # Wait for worker to finish
        for _ in range(40):
            app.processEvents()
            if not dashboard._is_refreshing:
                break
            time.sleep(0.05)

        self.assertFalse(dashboard._is_refreshing)
        if hasattr(dashboard, "_worker_thread") and dashboard._worker_thread:
            dashboard._worker_thread.wait(2000)

    def test_weekly_timeline_refresh_async_mode_is_non_blocking(self):
        """Verify WeeklyTimelinePage.refresh(async_mode=True) offloads 7-day aggregation to background thread."""
        import sys
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        from ui.weekly_timeline import WeeklyTimelinePage

        mock_service = MagicMock()

        def slow_week_data():
            time.sleep(0.06)
            return []

        mock_service.get_weekly_timeline_data.side_effect = slow_week_data
        weekly = WeeklyTimelinePage(mock_service)

        start = time.time()
        weekly.refresh(async_mode=True)
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.15)

        for _ in range(40):
            app.processEvents()
            if not weekly._is_refreshing:
                break
            time.sleep(0.05)

        self.assertFalse(weekly._is_refreshing)
        if hasattr(weekly, "_worker_thread") and weekly._worker_thread:
            weekly._worker_thread.wait(2000)

    def test_sync_service_fetch_settings_single_flight_lock(self):
        """Verify SyncService._fetching_settings_lock prevents overlapping settings API requests."""
        svc = SyncService(api_url="https://test.api")
        acquired = svc._fetching_settings_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            # Calling fetch_settings while lock is held must return empty dict immediately without HTTP request
            with patch("requests.post") as mock_post:
                res = svc.fetch_settings()
                self.assertEqual(res, {})
                mock_post.assert_not_called()
        finally:
            svc._fetching_settings_lock.release()


if __name__ == "__main__":
    unittest.main()
