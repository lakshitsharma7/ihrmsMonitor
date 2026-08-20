"""Tests for database.repository - session creation/closing/aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database.repository import ActivityRepository, SettingsRepository


def test_create_and_close_session(session_factory):
    db = session_factory()
    repo = ActivityRepository(db)

    start = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    record = repo.create_session("Chrome", 1234, "GitHub", start)
    assert record.id is not None
    assert record.ended_at is None
    assert record.duration_seconds == 0

    end = start + timedelta(minutes=15)
    closed = repo.close_session(record.id, end)
    assert closed is not None
    assert closed.ended_at is not None
    assert closed.duration_seconds == 15 * 60


def test_update_window_title(session_factory):
    db = session_factory()
    repo = ActivityRepository(db)
    start = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    record = repo.create_session("Chrome", 1234, "Tab A", start)

    repo.update_session_window_title(record.id, "Tab B")

    db2 = session_factory()
    fetched = db2.get(type(record), record.id)
    assert fetched.window_title == "Tab B"


def test_get_application_usage_groups_and_sorts(session_factory):
    db = session_factory()
    repo = ActivityRepository(db)
    start = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)

    s1 = repo.create_session("Chrome", 1, None, start)
    repo.close_session(s1.id, start + timedelta(minutes=10))

    s2 = repo.create_session("VS Code", 2, None, start + timedelta(minutes=10))
    repo.close_session(s2.id, start + timedelta(minutes=40))

    s3 = repo.create_session("Chrome", 1, None, start + timedelta(minutes=40))
    repo.close_session(s3.id, start + timedelta(minutes=50))

    usage = repo.get_application_usage(start, start + timedelta(hours=2))
    usage_by_name = {u.application_name: u.total_seconds for u in usage}

    assert usage_by_name["Chrome"] == 20 * 60
    assert usage_by_name["VS Code"] == 30 * 60
    # Sorted descending by total time.
    assert usage[0].application_name == "VS Code"


def test_open_session_not_double_counted_until_closed(session_factory):
    db = session_factory()
    repo = ActivityRepository(db)
    start = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    repo.create_session("Chrome", 1, None, start)

    total = repo.get_total_duration_seconds(start, start + timedelta(hours=1))
    assert total == 0  # not yet closed, so no duration counted


def test_settings_repository_defaults_and_update(session_factory):
    db = session_factory()
    repo = SettingsRepository(db)

    settings = repo.get_or_create()
    assert settings.idle_threshold == 300
    assert settings.tracking_enabled is False

    updated = repo.update(idle_threshold=600, tracking_enabled=True)
    assert updated.idle_threshold == 600
    assert updated.tracking_enabled is True

    # Only one settings row should ever exist.
    again = repo.get_or_create()
    assert again.id == updated.id
