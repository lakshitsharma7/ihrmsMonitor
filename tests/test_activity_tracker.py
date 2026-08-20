"""Tests for tracker.activity_tracker.ActivityTracker.

Uses a fake PlatformActivityProvider so this logic is fully testable
without any real OS API or GUI - satisfying the spec's requirement that
"Platform-specific functionality must be isolated behind clean interfaces"
and that shared business logic be independently testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database.repository import ActivityRepository
from platform_support.base import ActiveApplication, PlatformActivityProvider
from tracker.activity_tracker import ActivityTracker


class FakeClock:
    """Deterministic clock the test can advance manually."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self._now


class FakeProvider(PlatformActivityProvider):
    """A scriptable fake standing in for a real Windows/macOS provider."""

    def __init__(self) -> None:
        self.active_application: ActiveApplication | None = None
        self.idle_seconds: float = 0.0
        self.raise_on_get_active = False

    def get_active_application(self):
        if self.raise_on_get_active:
            raise RuntimeError("simulated platform failure")
        return self.active_application

    def get_idle_seconds(self) -> float:
        return self.idle_seconds


def _make_tracker(session_factory, provider, idle_threshold=300, clock=None):
    return ActivityTracker(
        provider=provider,
        session_factory=session_factory,
        idle_threshold_seconds=idle_threshold,
        track_window_titles=True,
        clock=clock or (lambda: datetime.now(timezone.utc)),
    )


def test_new_session_created_on_application_switch(session_factory):
    provider = FakeProvider()
    clock = FakeClock(datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc))
    tracker = _make_tracker(session_factory, provider, clock=clock)
    tracker.start()

    provider.active_application = ActiveApplication("Chrome", 1, "GitHub")
    state = tracker.poll()
    assert state.current_application == "Chrome"

    clock.advance(60)
    provider.active_application = ActiveApplication("VS Code", 2, "main.py")
    state = tracker.poll()
    assert state.current_application == "VS Code"

    db = session_factory()
    repo = ActivityRepository(db)
    sessions = repo.get_sessions_between(
        datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc),
    )
    assert len(sessions) == 2
    chrome = next(s for s in sessions if s.application_name == "Chrome")
    assert chrome.ended_at is not None
    assert chrome.duration_seconds == 60


def test_window_title_change_updates_same_session(session_factory):
    provider = FakeProvider()
    clock = FakeClock(datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc))
    tracker = _make_tracker(session_factory, provider, clock=clock)
    tracker.start()

    provider.active_application = ActiveApplication("Chrome", 1, "Tab A")
    tracker.poll()

    clock.advance(5)
    provider.active_application = ActiveApplication("Chrome", 1, "Tab B")
    tracker.poll()

    db = session_factory()
    repo = ActivityRepository(db)
    sessions = repo.get_sessions_between(
        datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc),
    )
    # Still just one session - the title was updated in place, not replaced.
    assert len(sessions) == 1
    assert sessions[0].window_title == "Tab B"


def test_idle_closes_session_and_resuming_opens_new_one(session_factory):
    provider = FakeProvider()
    clock = FakeClock(datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc))
    tracker = _make_tracker(session_factory, provider, idle_threshold=300, clock=clock)
    tracker.start()

    provider.active_application = ActiveApplication("Chrome", 1, "GitHub")
    provider.idle_seconds = 0
    tracker.poll()

    # User goes idle.
    clock.advance(10)
    provider.idle_seconds = 301
    state = tracker.poll()
    assert state.is_idle is True

    db = session_factory()
    repo = ActivityRepository(db)
    open_session = repo.get_open_session()
    assert open_session is None  # closed when idle kicked in

    # User comes back.
    clock.advance(5)
    provider.idle_seconds = 0
    provider.active_application = ActiveApplication("Chrome", 1, "GitHub")
    state = tracker.poll()
    assert state.is_idle is False
    assert state.current_application == "Chrome"


def test_stop_closes_open_session(session_factory):
    provider = FakeProvider()
    clock = FakeClock(datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc))
    tracker = _make_tracker(session_factory, provider, clock=clock)
    tracker.start()

    provider.active_application = ActiveApplication("Slack", 3, None)
    tracker.poll()

    clock.advance(30)
    tracker.stop()

    db = session_factory()
    repo = ActivityRepository(db)
    assert repo.get_open_session() is None
    sessions = repo.get_sessions_between(
        datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc),
    )
    assert sessions[0].duration_seconds == 30


def test_provider_failure_does_not_raise(session_factory):
    provider = FakeProvider()
    provider.raise_on_get_active = True
    tracker = _make_tracker(session_factory, provider)
    tracker.start()

    # Must not raise even though the provider explodes.
    state = tracker.poll()
    assert state.is_tracking is True
    assert state.current_application is None


def test_start_stop_state_transitions(session_factory):
    provider = FakeProvider()
    tracker = _make_tracker(session_factory, provider)

    assert tracker.is_tracking is False
    tracker.start()
    assert tracker.is_tracking is True
    tracker.start()  # no-op, must not raise or duplicate state
    assert tracker.is_tracking is True
    tracker.stop()
    assert tracker.is_tracking is False
    tracker.stop()  # no-op
    assert tracker.is_tracking is False
