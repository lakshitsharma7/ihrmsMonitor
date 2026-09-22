"""Tests for services.activity_service and services.settings_service."""

from __future__ import annotations

from datetime import datetime, timezone

from database.repository import ActivityRepository
from services.activity_service import ActivityService
from services.settings_service import SettingsService


def test_today_total_and_usage(session_factory):
    now = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)

    db = session_factory()
    repo = ActivityRepository(db)
    s1 = repo.create_session("Chrome", 1, None, now.replace(hour=9))
    repo.close_session(s1.id, now.replace(hour=10))  # 1h
    s2 = repo.create_session("VS Code", 2, None, now.replace(hour=10))
    repo.close_session(s2.id, now.replace(hour=10, minute=45))  # 45m

    service = ActivityService(session_factory)
    total = service.get_today_total_seconds(now=now)
    assert total == 3600 + 45 * 60

    usage = service.get_today_application_usage(now=now)
    assert usage[0].application_name == "Chrome"

    timeline = service.get_today_timeline(now=now)
    assert len(timeline) == 2


def test_format_duration():
    assert ActivityService.format_duration(0) == "0s"
    assert ActivityService.format_duration(59) == "59s"
    assert ActivityService.format_duration(60) == "1m"
    assert ActivityService.format_duration(3600) == "1h"
    assert ActivityService.format_duration(3600 + 90) == "1h 1m"


def test_settings_service_roundtrip(session_factory):
    service = SettingsService(session_factory)
    settings = service.get_settings()
    assert settings.idle_threshold == 180

    updated = service.update_settings(idle_threshold=120, track_window_titles=False)
    assert updated.idle_threshold == 120
    assert updated.track_window_titles is False

    reloaded = service.get_settings()
    assert reloaded.idle_threshold == 120
    assert reloaded.track_window_titles is False

