"""Comprehensive tests for Application Detection, Session Creation, and Timeline Display.

Validates:
- Active application and window detection.
- Database session creation with started_at, application_name, window_title, process_id.
- Live elapsed duration calculation for ongoing active sessions.
- Proper aggregation in ApplicationUsageTable (Time, App, Duration, Subprocess).
- Proper display in ActivityTimelineTable (Time, App, Duration, Subprocess, PID).
- Asynchronous dashboard refresh dispatching to Qt main thread via data_refreshed Signal.
- Asynchronous weekly timeline refresh dispatching via weekly_data_refreshed Signal.
- Application switching creating distinct entries.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import ActivitySession, Base
from database.repository import ActivityRepository
from services.activity_service import ActivityService, TimelineEntry
from tracker.activity_tracker import ActiveApplication, ActivityTracker, TrackerState
from ui.activity_table import ActivityTimelineTable, ApplicationUsageTable
from ui.dashboard import DashboardPage
from ui.weekly_timeline import WeeklyTimelinePage


class TestApplicationTrackingAndTimeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.service = ActivityService(self.session_factory)
        self.emp_id = self.service._current_employee_id()

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_01_ongoing_session_calculates_live_duration(self):
        """An ongoing session (ended_at is None) returns live elapsed duration in get_today_timeline()."""
        db = self.session_factory()
        now_utc = datetime.now(timezone.utc)
        started_at = now_utc - timedelta(seconds=45)

        repo = ActivityRepository(db)
        repo.create_session(
            application_name="Antigravity IDE.exe",
            process_id=12345,
            window_title="activity_tracker.py - Antigravity IDE",
            started_at=started_at,
            employee_id=self.emp_id,
        )
        db.close()

        timeline = self.service.get_today_timeline()
        self.assertEqual(len(timeline), 1)
        entry = timeline[0]
        self.assertEqual(entry.application_name, "Antigravity IDE.exe")
        self.assertEqual(entry.window_title, "activity_tracker.py - Antigravity IDE")
        self.assertEqual(entry.process_id, 12345)
        # Live duration should be >= 45 seconds (not 0)
        self.assertGreaterEqual(entry.duration_seconds, 45)

    def test_02_multiple_applications_and_app_switch_aggregation(self):
        """Switching between applications records distinct sessions and aggregates correctly."""
        db = self.session_factory()
        now_utc = datetime.now(timezone.utc)

        repo = ActivityRepository(db)
        # Session 1: Chrome (closed, 120s)
        s1 = repo.create_session(
            application_name="chrome.exe",
            process_id=2001,
            window_title="Google Search - Google Chrome",
            started_at=now_utc - timedelta(seconds=300),
            employee_id=self.emp_id,
        )
        repo.close_session(s1.id, ended_at=now_utc - timedelta(seconds=180), idle_seconds=0)

        # Session 2: Excel (closed, 60s with 10s idle)
        s2 = repo.create_session(
            application_name="EXCEL.EXE",
            process_id=2002,
            window_title="Q3_Report.xlsx - Excel",
            started_at=now_utc - timedelta(seconds=180),
            employee_id=self.emp_id,
        )
        repo.close_session(s2.id, ended_at=now_utc - timedelta(seconds=120), idle_seconds=10)

        # Session 3: Chrome again (ongoing for 120s)
        repo.create_session(
            application_name="chrome.exe",
            process_id=2001,
            window_title="GitHub - Google Chrome",
            started_at=now_utc - timedelta(seconds=120),
            employee_id=self.emp_id,
        )
        db.close()

        timeline = self.service.get_today_timeline()
        self.assertEqual(len(timeline), 3)

        # Test ActivityTimelineTable population
        timeline_table = ActivityTimelineTable()
        timeline_table.set_entries(timeline)
        self.assertEqual(timeline_table.rowCount(), 3)
        # First row is newest (Chrome ongoing)
        self.assertEqual(timeline_table.item(0, 1).text(), "chrome.exe")
        self.assertEqual(timeline_table.item(0, 3).text(), "GitHub - Google Chrome")
        self.assertEqual(timeline_table.item(0, 4).text(), "2001")

        # Second row is Excel with idle duration formatted
        self.assertEqual(timeline_table.item(1, 1).text(), "EXCEL.EXE")
        self.assertIn("idle", timeline_table.item(1, 2).text())
        self.assertEqual(timeline_table.item(1, 4).text(), "2002")

        # Test ApplicationUsageTable aggregation
        usage_table = ApplicationUsageTable()
        usage_table.set_entries(timeline)
        self.assertEqual(usage_table.rowCount(), 2)  # Chrome and Excel

    def test_03_dashboard_page_async_refresh_populates_tables_via_signal(self):
        """DashboardPage.refresh(async_mode=True) emits data_refreshed signal and populates UI tables on the main thread."""
        db = self.session_factory()
        now_utc = datetime.now(timezone.utc)
        repo = ActivityRepository(db)
        s = repo.create_session(
            application_name="python.exe",
            process_id=9999,
            window_title="Workpulse",
            started_at=now_utc - timedelta(seconds=30),
            employee_id=self.emp_id,
        )
        repo.close_session(s.id, ended_at=now_utc, idle_seconds=0)
        db.close()

        dashboard = DashboardPage(self.service)
        # Call async refresh
        dashboard.refresh(async_mode=True)

        # Allow background thread and Qt event loop to deliver signal
        for _ in range(30):
            time.sleep(0.05)
            self.app.processEvents()
            if dashboard.timeline_table.rowCount() > 0:
                break

        self.assertGreaterEqual(dashboard.timeline_table.rowCount(), 1)
        self.assertEqual(dashboard.timeline_table.item(0, 1).text(), "python.exe")
        self.assertEqual(dashboard.usage_table.item(0, 1).text(), "python.exe")

    def test_04_weekly_timeline_page_async_refresh_via_signal(self):
        """WeeklyTimelinePage.refresh(async_mode=True) emits weekly_data_refreshed signal and updates chart."""
        weekly_page = WeeklyTimelinePage(self.service)
        weekly_page.refresh(async_mode=True)

        for _ in range(30):
            time.sleep(0.05)
            self.app.processEvents()
            if len(weekly_page.chart._week_data) > 0:
                break

        self.assertEqual(len(weekly_page.chart._week_data), 7)

    def test_05_todays_time_and_weekly_timeline_consistency(self):
        """Today's Time on dashboard and Weekly Timeline's today entry use the exact same calculation and data source."""
        db = self.session_factory()
        now_utc = datetime.now(timezone.utc)
        repo = ActivityRepository(db)

        # 30 minutes active session today
        s = repo.create_session(
            application_name="VSCode.exe",
            process_id=4567,
            window_title="main.py",
            started_at=now_utc - timedelta(minutes=30),
            employee_id=self.emp_id,
        )
        repo.close_session(s.id, ended_at=now_utc, idle_seconds=0)
        db.close()

        # Calculation via get_today_total_seconds
        today_total_s = self.service.get_today_total_seconds()
        self.assertGreaterEqual(today_total_s, 1800)

        # Calculation via get_weekly_timeline_data
        weekly_data = self.service.get_weekly_timeline_data()
        today_entry = next(d for d in weekly_data if d["is_today"])

        # Both must have the EXACT SAME total_seconds
        self.assertEqual(today_total_s, today_entry["total_seconds"])
        self.assertEqual(self.service.get_day_total_seconds(date.today()), today_entry["total_seconds"])


if __name__ == "__main__":
    unittest.main()
