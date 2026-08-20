"""The core, platform-independent activity-tracking state machine.

This module contains ZERO operating-system-specific code and zero Qt code,
which is what makes it independently unit-testable (see ``tests/``). It is
driven by whatever calls ``poll()`` on a timer - in the real application
that's ``tracker.tracker_worker.TrackerWorker`` running on a ``QThread``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from database.repository import ActivityRepository
from platform_support.base import ActiveApplication, PlatformActivityProvider
from tracker.activity_session import CurrentSession
from utils.logger import get_logger

logger = get_logger(__name__)

SessionFactory = Callable[[], "Session"]  # type: ignore[name-defined]  # sqlalchemy.orm.Session


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TrackerState:
    """A snapshot of the tracker's current state, consumed by the UI."""

    is_tracking: bool
    is_idle: bool
    current_application: str | None
    current_window_title: str | None
    idle_seconds: float


class ActivityTracker:
    """Owns the session-creation/close logic described in the product spec.

    Rules implemented here:
        * A new session is created when the focused application changes.
        * If only the window title changes (same app), the existing open
          session's title is updated in place (configurable).
        * Idle time is never counted toward an application's active usage:
          crossing the idle threshold closes the current session; activity
          resuming starts a fresh one.
    """

    def __init__(
        self,
        provider: PlatformActivityProvider,
        session_factory,
        idle_threshold_seconds: float,
        track_window_titles: bool = True,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._provider = provider
        self._session_factory = session_factory
        self._idle_threshold_seconds = idle_threshold_seconds
        self._track_window_titles = track_window_titles
        self._clock = clock

        self._is_tracking = False
        self._is_idle = False
        self._current: CurrentSession | None = None
        self._last_idle_seconds = 0.0

    # -- public configuration -------------------------------------------------

    def set_idle_threshold(self, seconds: float) -> None:
        self._idle_threshold_seconds = seconds

    def set_track_window_titles(self, enabled: bool) -> None:
        self._track_window_titles = enabled

    @property
    def is_tracking(self) -> bool:
        return self._is_tracking

    # -- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        """Begin tracking. Safe to call if already tracking (no-op)."""
        if self._is_tracking:
            return
        logger.info("Tracker started")
        self._is_tracking = True
        self._is_idle = False
        self._current = None

    def stop(self) -> None:
        """Stop tracking and safely close any open session.

        Order of operations, per spec:
            1. Stop polling (caller's responsibility - they just stop calling poll()).
            2. Close current session.
            3. Save final duration.
            4. (Caller emits a tracking-stopped signal / updates UI.)
        """
        if not self._is_tracking:
            return
        logger.info("Tracker stopping")
        self._close_current_session()
        self._is_tracking = False
        self._is_idle = False

    # -- main loop --------------------------------------------------------------

    def poll(self) -> TrackerState:
        """Perform one tracking tick. Call this periodically (e.g. every 1s).

        Never raises: any error from the platform provider or database is
        caught, logged, and the tracker continues on the next tick.
        """
        if not self._is_tracking:
            return self._state()

        try:
            idle_seconds = self._safe_get_idle_seconds()
            self._last_idle_seconds = idle_seconds

            was_idle = self._is_idle
            now_idle = idle_seconds >= self._idle_threshold_seconds

            if now_idle and not was_idle:
                self._on_became_idle()
            elif not now_idle and was_idle:
                self._on_became_active()

            self._is_idle = now_idle

            if not self._is_idle:
                self._poll_active_application()

        except Exception:  # noqa: BLE001 - the tracker loop must never die
            logger.exception("Unexpected error during tracker poll()")

        return self._state()

    # -- internal helpers ---------------------------------------------------

    def _poll_active_application(self) -> None:
        active = self._safe_get_active_application()
        if active is None:
            return

        title = active.window_title if self._track_window_titles else None

        if self._current is None:
            self._open_new_session(active, title)
            return

        if self._current.matches_application(active.application_name, active.process_id):
            if title != self._current.window_title:
                self._current.window_title = title
                self._update_session_title(title)
            return

        # Application changed: close old, open new.
        self._close_current_session()
        self._open_new_session(active, title)

    def _open_new_session(self, active: ActiveApplication, title: str | None) -> None:
        now = self._clock()
        db_session = self._session_factory()
        try:
            repo = ActivityRepository(db_session)
            record = repo.create_session(
                application_name=active.application_name,
                process_id=active.process_id,
                window_title=title,
                started_at=now,
            )
            self._current = CurrentSession(
                db_id=record.id,
                application_name=active.application_name,
                process_id=active.process_id,
                window_title=title,
                started_at=now,
            )
            logger.info("Started new session for %s", active.application_name)
        finally:
            db_session.close()

    def _update_session_title(self, title: str | None) -> None:
        if self._current is None:
            return
        db_session = self._session_factory()
        try:
            repo = ActivityRepository(db_session)
            repo.update_session_window_title(self._current.db_id, title)
        finally:
            db_session.close()

    def _close_current_session(self) -> None:
        if self._current is None:
            return
        now = self._clock()
        db_session = self._session_factory()
        try:
            repo = ActivityRepository(db_session)
            repo.close_session(self._current.db_id, now)
            logger.info(
                "Closed session for %s (duration recorded)",
                self._current.application_name,
            )
        finally:
            db_session.close()
            self._current = None

    def _on_became_idle(self) -> None:
        logger.info("User became idle; closing current session")
        self._close_current_session()

    def _on_became_active(self) -> None:
        logger.info("User activity resumed after idle")
        # A fresh session will be opened on the next _poll_active_application call.

    def _safe_get_active_application(self) -> ActiveApplication | None:
        try:
            return self._provider.get_active_application()
        except Exception:  # noqa: BLE001
            logger.exception("Platform provider failed to get active application")
            return None

    def _safe_get_idle_seconds(self) -> float:
        try:
            return self._provider.get_idle_seconds()
        except Exception:  # noqa: BLE001
            logger.exception("Platform provider failed to get idle seconds")
            return 0.0

    def _state(self) -> TrackerState:
        return TrackerState(
            is_tracking=self._is_tracking,
            is_idle=self._is_idle,
            current_application=self._current.application_name if self._current else None,
            current_window_title=self._current.window_title if self._current else None,
            idle_seconds=self._last_idle_seconds,
        )
