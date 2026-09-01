"""Platform-independent activity tracking state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from database.repository import ActivityRepository
from platform_support.base import (
    ActiveApplication,
    PlatformActivityProvider,
)
from tracker.activity_session import CurrentSession
from utils.logger import get_logger

from config.settings import SYNC_INTERVAL_SECONDS
from services.screenshot import capture_screenshot


logger = get_logger(__name__)


# ==============================================================
# CLOCK
# ==============================================================


def _default_clock() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


# ==============================================================
# TRACKER STATE
# ==============================================================


@dataclass
class TrackerState:
    """Current tracker state consumed by the UI."""

    is_tracking: bool
    is_idle: bool
    current_application: str | None
    current_window_title: str | None
    idle_seconds: float


# ==============================================================
# ACTIVITY TRACKER
# ==============================================================


class ActivityTracker:
    """
    Core activity-tracking state machine.

    Behaviour:

    1. Create a session when tracking starts.
    2. Keep the same session while the same application/process
       remains active.
    3. Create a new session when the application changes.
    4. Capture a screenshot for the NEW session after the session
       has been created.
    5. Screenshot filename contains the session ID.
    6. Close the current session when the user becomes idle.
    7. Create a new session when the user becomes active again.
    8. Close stale sessions when the tracker starts.
    9. Trigger activity synchronization after an application change.
    """

    def __init__(
        self,
        provider: PlatformActivityProvider,
        session_factory,
        idle_threshold_seconds: float,
        track_window_titles: bool = True,
        clock: Callable[[], datetime] = _default_clock,
        sync_service=None,
        screenshot_interval_type: str = "3_min",
        screenshot_custom_interval_seconds: int = 180,
        capture_on_switch: bool = True,
    ) -> None:

        self._provider = provider

        self._session_factory = session_factory

        self._idle_threshold_seconds = (
            idle_threshold_seconds
        )

        self._track_window_titles = (
            track_window_titles
        )

        self._clock = clock

        self._sync_service = sync_service

        self._is_tracking = False

        self._is_idle = False

        self._current: CurrentSession | None = None

        self._last_idle_seconds = 0.0

        self._screenshot_interval_type = screenshot_interval_type

        self._screenshot_custom_interval_seconds = screenshot_custom_interval_seconds

        self._capture_on_switch = capture_on_switch

        self._last_screenshot_time = None

        # Drives the periodic activity sync (see SYNC_INTERVAL_SECONDS).
        self._last_sync_time = None

        # Tracks wall-clock timestamp between polls to detect system sleep / hibernate
        self._last_poll_time = None

        # Tracks idle state and timestamps to calculate and send idle time accurately
        self._idle_start_time = None
        self._last_active_session_id = None

    # ==========================================================
    # CONFIGURATION
    # ==========================================================

    def set_idle_threshold(
        self,
        seconds: float,
    ) -> None:
        """Change the idle threshold."""

        self._idle_threshold_seconds = seconds

    def set_track_window_titles(
        self,
        enabled: bool,
    ) -> None:
        """Enable or disable window-title tracking."""

        self._track_window_titles = enabled

    def set_screenshot_settings(
        self,
        interval_type: str,
        custom_interval_seconds: int,
        capture_on_switch: bool,
    ) -> None:
        """Update screenshot scheduling parameters."""
        self._screenshot_interval_type = interval_type
        self._screenshot_custom_interval_seconds = custom_interval_seconds
        self._capture_on_switch = capture_on_switch

    @property
    def is_tracking(self) -> bool:
        """Return whether tracking is currently active."""

        return self._is_tracking

    # ==========================================================
    # START
    # ==========================================================

    def start(self) -> None:
        """
        Start activity tracking.

        Any stale open database session from a previous
        application run is closed first.
        """

        if self._is_tracking:
            return

        logger.info(
            "Starting activity tracker"
        )

        self._close_stale_database_session()

        self._is_tracking = True

        self._is_idle = False

        self._current = None

        self._last_idle_seconds = 0.0

        self._last_screenshot_time = self._clock()

        logger.info(
            "Activity tracker started"
        )

        # A previous run may have collected logs it never managed to send
        # (no connection, or the machine was shut down). Push those now
        # rather than making them wait a full cycle.
        self._last_sync_time = self._clock()

        self._sync_activity()

    # ==========================================================
    # STOP
    # ==========================================================

    def stop(self) -> None:
        """Stop tracking and close the current session."""

        if not self._is_tracking:
            return

        logger.info(
            "Stopping activity tracker"
        )

        self._close_current_session()

        self._is_tracking = False

        self._is_idle = False

        self._last_idle_seconds = 0.0

        logger.info(
            "Activity tracker stopped"
        )

    # ==========================================================
    # MAIN POLLING LOOP
    # ==========================================================

    def poll(self) -> TrackerState:
        """
        Perform one tracking tick.

        The worker should normally call this once per second.
        """

        if not self._is_tracking:
            return self._state()

        try:
            now = self._clock()

            # --------------------------------------------------
            # System sleep / hibernate / suspend detection.
            #
            # The timer polls every ~1s. If the wall-clock elapsed time
            # between polls exceeds 10s, the laptop went to sleep or hibernated.
            # Close the previous session at the moment the laptop went to sleep
            # so sleep/offline time is NEVER counted as working time.
            # --------------------------------------------------
            if self._last_poll_time is not None:
                gap_seconds = (now - self._last_poll_time).total_seconds()
                if gap_seconds > 10.0:
                    logger.info(
                        "System sleep / suspend detected: elapsed %.1fs between polls. "
                        "Closing previous session at last active time.",
                        gap_seconds,
                    )
                    if self._current is not None:
                        self._close_current_session_at(self._last_poll_time)
                    self._is_idle = False

            self._last_poll_time = now

            # --------------------------------------------------
            # Get idle time.
            # --------------------------------------------------

            idle_seconds = (
                self._safe_get_idle_seconds()
            )

            self._last_idle_seconds = (
                idle_seconds
            )

            was_idle = self._is_idle

            now_idle = (
                idle_seconds
                >= self._idle_threshold_seconds
            )

            # --------------------------------------------------
            # User became idle.
            # --------------------------------------------------

            if now_idle and not was_idle:

                self._on_became_idle(idle_seconds)

            # --------------------------------------------------
            # User became active again.
            # --------------------------------------------------

            elif not now_idle and was_idle:

                self._on_became_active()

            self._is_idle = now_idle

            # --------------------------------------------------
            # Track active application.
            # --------------------------------------------------

            if not self._is_idle:

                self._poll_active_application()

                # Check screenshot interval scheduler
                now = self._clock()
                interval_seconds = 180
                if self._screenshot_interval_type == "3_min":
                    interval_seconds = 3 * 60
                elif self._screenshot_interval_type == "5_min":
                    interval_seconds = 5 * 60
                elif self._screenshot_interval_type == "10_min":
                    interval_seconds = 10 * 60
                elif self._screenshot_interval_type == "custom":
                    interval_seconds = self._screenshot_custom_interval_seconds

                if self._last_screenshot_time is None:
                    self._last_screenshot_time = now
                else:
                    elapsed = (now - self._last_screenshot_time).total_seconds()
                    if elapsed >= interval_seconds:
                        self._capture_screenshot_for_current_session()

            # --------------------------------------------------
            # Periodic activity sync.
            #
            # Runs off the tracker's own poll loop, so it needs no user
            # interaction and keeps running while the app sits in the tray.
            # Checked even while idle: logs collected before the user went
            # idle still need to go out.
            # --------------------------------------------------

            now = self._clock()
            sync_interval = self._get_sync_interval_seconds()

            if self._last_sync_time is None:
                self._last_sync_time = now

            elif (now - self._last_sync_time).total_seconds() >= sync_interval:
                self._last_sync_time = now

                logger.info(
                    "Activity sync interval reached (%d seconds / %.1f hours)",
                    sync_interval,
                    sync_interval / 3600.0,
                )

                self._sync_activity()

        except Exception:  # noqa: BLE001

            logger.exception(
                "Unexpected error during tracker poll()"
            )

        return self._state()

    # ==========================================================
    # ACTIVE APPLICATION
    # ==========================================================

    def _poll_active_application(
        self,
    ) -> None:
        """Check and update the active application session."""

        active = (
            self._safe_get_active_application()
        )

        if active is None:
            return

        now = self._clock()

        # Check calendar date rollover: if the day changed while tracking,
        # close the session at local midnight and open a new session for today.
        if self._current is not None:
            now_local = now.astimezone()
            curr_local = self._current.started_at.astimezone()
            if now_local.date() != curr_local.date():
                logger.info(
                    "Calendar date rolled over from %s to %s. Splitting session at midnight.",
                    curr_local.date(),
                    now_local.date(),
                )
                from datetime import time
                midnight_utc = datetime.combine(now_local.date(), time.min).astimezone(timezone.utc)
                self._close_current_session_at(midnight_utc)

        # ------------------------------------------------------
        # Window title.
        # ------------------------------------------------------

        title = (
            active.window_title
            if self._track_window_titles
            else None
        )

        # ------------------------------------------------------
        # No current session.
        #
        # This happens:
        #
        # - tracker started
        # - user returned from idle
        # - previous session closed
        # ------------------------------------------------------

        if self._current is None:

            self._open_new_session(
                active,
                title,
            )

            if self._capture_on_switch:
                self._capture_screenshot_for_current_session()

            return

        # ------------------------------------------------------
        # Same application + same process + same window title.
        # ------------------------------------------------------

        is_same_window = (
            self._current.matches_application(
                active.application_name,
                active.process_id,
            )
            and (
                not self._track_window_titles
                or title == self._current.window_title
            )
        )

        if is_same_window:
            # Keep database record updated with current elapsed time
            self._heartbeat_current_session(now)
            return

        # ======================================================
        # APPLICATION OR WINDOW CHANGED
        # ======================================================

        previous_application = (
            self._current.application_name
        )
        previous_title = (
            self._current.window_title
        )
        previous_session_id = (
            self._current.db_id
        )

        logger.info(
            "Active activity changed: [id=%s app=%s title=%r] -> [app=%s title=%r]",
            previous_session_id,
            previous_application,
            previous_title,
            active.application_name,
            title,
        )

        # ------------------------------------------------------
        # STEP 1:
        # Close OLD session.
        # ------------------------------------------------------

        self._close_current_session_at(now)

        # ------------------------------------------------------
        # STEP 2:
        # Create NEW session.
        # ------------------------------------------------------

        self._open_new_session(
            active,
            title,
        )

        # ------------------------------------------------------
        # STEP 3:
        # Capture screenshot for NEW session.
        #
        # IMPORTANT:
        # self._current.db_id now belongs to the NEW app.
        # ------------------------------------------------------

        screenshot_path = None
        if self._capture_on_switch:
            screenshot_path = (
                self._capture_screenshot_for_current_session()
            )

        # ------------------------------------------------------
        # STEP 4:
        # Log screenshot.
        # ------------------------------------------------------

        if screenshot_path:

            logger.info(
                "Screenshot associated with "
                "session=%s app=%s path=%s",
                self._current.db_id
                if self._current
                else None,
                active.application_name,
                screenshot_path,
            )

        else:

            logger.warning(
                "No screenshot captured for "
                "session=%s app=%s",
                self._current.db_id
                if self._current
                else None,
                active.application_name,
            )

        # ------------------------------------------------------
        # STEP 5:
        # Nothing to send here.
        #
        # The session is already stored locally. Sending is handled by the
        # periodic sync in poll(), so an application switch no longer fires
        # its own API request.
        # ------------------------------------------------------

    # ==========================================================
    # SCREENSHOT
    # ==========================================================

    def _capture_screenshot_for_current_session(
        self,
    ) -> str | None:
        """
        Capture a screenshot for the current activity session.

        The existing capture_screenshot() function creates the
        screenshot first. We then rename it so the filename
        contains the ActivitySession ID.

        Final filename:

            session_<ID>_<timestamp>.png

        Example:

            session_42_2026-08-24_07-35-12-123456.png
        """

        if self._current is None:

            logger.warning(
                "Cannot capture screenshot: "
                "there is no current session"
            )

            return None

        self._last_screenshot_time = self._clock()

        session_id = self._current.db_id

        try:

            # --------------------------------------------------
            # Capture using existing screenshot service.
            # --------------------------------------------------

            # The capture service names the file after the session, so
            # there is nothing to rename afterwards. The previous
            # capture-then-rename step raced with the file still being
            # written and silently dropped the screenshot.
            screenshot_path = capture_screenshot(
                activity_session_id=session_id,
            )

            if not screenshot_path:

                logger.warning(
                    "No screenshot file was produced for session=%s; "
                    "see the capture error above",
                    session_id,
                )

                return None

            logger.info(
                "Screenshot saved: "
                "session=%s path=%s",
                session_id,
                screenshot_path,
            )

            # Associate screenshot path in local database
            db_session = self._session_factory()
            try:
                ActivityRepository(db_session).update_session_screenshot_path(
                    session_id,
                    screenshot_path,
                )
            except Exception as db_err:
                logger.error("Failed to associate screenshot path in database: %s", db_err)
            finally:
                db_session.close()

            return screenshot_path

        except Exception:  # noqa: BLE001

            logger.exception(
                "Failed to capture screenshot "
                "for session=%s",
                session_id,
            )

            return None

    # ==========================================================
    # OPEN NEW SESSION
    # ==========================================================

    def _open_new_session(
        self,
        active: ActiveApplication,
        title: str | None,
    ) -> None:
        """Create a new database activity session."""

        now = self._clock()

        db_session = (
            self._session_factory()
        )

        try:

            repository = (
                ActivityRepository(
                    db_session
                )
            )

            record = (
                repository.create_session(
                    application_name=(
                        active.application_name
                    ),
                    process_id=(
                        active.process_id
                    ),
                    window_title=title,
                    started_at=now,
                )
            )

            # --------------------------------------------------
            # IMPORTANT:
            # Set _current immediately after DB creation so
            # screenshot capture can use record.id.
            # --------------------------------------------------

            self._current = CurrentSession(
                db_id=record.id,
                application_name=(
                    active.application_name
                ),
                process_id=(
                    active.process_id
                ),
                window_title=title,
                started_at=now,
            )

            logger.info(
                "Started new session: "
                "app=%s session_id=%s pid=%s",
                active.application_name,
                record.id,
                active.process_id,
            )

        finally:

            db_session.close()

    # ==========================================================
    # UPDATE WINDOW TITLE
    # ==========================================================

    def _update_session_title(
        self,
        title: str | None,
    ) -> None:
        """Update the current session's window title."""

        if self._current is None:
            return

        db_session = (
            self._session_factory()
        )

        try:

            repository = (
                ActivityRepository(
                    db_session
                )
            )

            repository.update_session_window_title(
                self._current.db_id,
                title,
            )

        finally:

            db_session.close()

    # ==========================================================
    # CLOSE CURRENT SESSION
    # ==========================================================

    def _close_current_session_at(
        self,
        ended_at: datetime,
    ) -> None:
        """Close the currently tracked session at a specific timestamp."""
        if self._current is None:
            return

        session_id = self._current.db_id
        application_name = self._current.application_name

        db_session = self._session_factory()
        try:
            repository = ActivityRepository(db_session)
            repository.close_session(session_id, ended_at)
            logger.info(
                "Closed session: app=%s session_id=%s ended_at=%s",
                application_name,
                session_id,
                ended_at,
            )
        finally:
            db_session.close()
            self._current = None

    def _close_current_session(
        self,
    ) -> None:
        """Close the currently tracked session."""
        self._close_current_session_at(self._clock())

    def _heartbeat_current_session(
        self,
        now: datetime,
    ) -> None:
        """Periodically update the open session in database with current elapsed time."""
        if self._current is None:
            return

        db_session = self._session_factory()
        try:
            repository = ActivityRepository(db_session)
            repository.update_session_heartbeat(self._current.db_id, now)
        finally:
            db_session.close()

    # ==========================================================
    # CLOSE STALE DATABASE SESSION
    # ==========================================================

    def _close_stale_database_session(
        self,
    ) -> None:
        """
        Close an old open session from a previous tracker run safely without extending offline time.
        """
        db_session = self._session_factory()
        try:
            repository = ActivityRepository(db_session)
            closed = repository.close_stale_sessions()
            if closed > 0:
                logger.info("Closed %d stale open database sessions without extending duration", closed)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to close stale database session"
            )
        finally:
            db_session.close()

    # ==========================================================
    # IDLE
    # ==========================================================

    def _on_became_idle(
        self,
        idle_seconds: float = 0.0,
    ) -> None:
        """Handle the user becoming idle."""

        now = self._clock()
        last_input_time = now - timedelta(seconds=max(0.0, idle_seconds))
        self._idle_start_time = last_input_time

        logger.info(
            "User became idle after %.1fs of inactivity; closing active session at %s",
            idle_seconds,
            last_input_time,
        )

        if self._current is not None:
            self._last_active_session_id = self._current.db_id
            self._close_current_session_at(last_input_time)
        else:
            self._last_active_session_id = None

    # ==========================================================
    # ACTIVE AGAIN
    # ==========================================================

    def _on_became_active(
        self,
    ) -> None:
        """Handle activity resuming after idle."""

        now = self._clock()
        idle_duration = 0
        if self._idle_start_time:
            idle_duration = max(0, int((now - self._idle_start_time).total_seconds()))

        logger.info(
            "User activity resumed after idle. Total idle duration: %ds",
            idle_duration,
        )

        if self._last_active_session_id and idle_duration > 0:
            db_session = self._session_factory()
            try:
                repo = ActivityRepository(db_session)
                repo.update_session_idle_seconds(self._last_active_session_id, idle_duration)
            except Exception as err:
                logger.error("Failed to update idle seconds for session %s: %s", self._last_active_session_id, err)
            finally:
                db_session.close()

        self._idle_start_time = None
        self._last_active_session_id = None

    # ==========================================================
    # ACTIVITY SYNC
    # ==========================================================

    def _get_sync_interval_seconds(self) -> int:
        """Return the current sync interval in seconds (default 2 hours)."""
        if self._sync_service is not None:
            configured = getattr(self._sync_service, "current_sync_interval_seconds", None)
            if configured and int(configured) > 0:
                return int(configured)
        return SYNC_INTERVAL_SECONDS

    def _sync_activity(
        self,
    ) -> None:
        """
        Request an immediate activity synchronization.

        SyncService controls the actual sync window.
        """

        if self._sync_service is None:

            logger.debug(
                "SyncService not configured; "
                "skipping activity sync"
            )

            return

        try:
            # Checkpoint the current active session at now so all synced sessions
            # have a definitive start and end time without overlap or open guessing.
            now = self._clock()
            if self._current is not None:
                active_app = ActiveApplication(self._current.application_name, self._current.process_id)
                title = self._current.window_title
                self._close_current_session_at(now)
                self._open_new_session(active_app, title)

            success = (
                self._sync_service
                .sync_activity_now()
            )

            if success:

                logger.info(
                    "Activity sync completed"
                )

            else:

                logger.warning(
                    "Activity sync failed"
                )

        except Exception:  # noqa: BLE001

            logger.exception(
                "Activity sync raised an exception"
            )

    # ==========================================================
    # PLATFORM: ACTIVE APPLICATION
    # ==========================================================

    def _safe_get_active_application(
        self,
    ) -> ActiveApplication | None:
        """Safely get the active application."""

        try:

            return (
                self._provider
                .get_active_application()
            )

        except Exception:  # noqa: BLE001

            logger.exception(
                "Platform provider failed "
                "to get active application"
            )

            return None

    # ==========================================================
    # PLATFORM: IDLE TIME
    # ==========================================================

    def _safe_get_idle_seconds(
        self,
    ) -> float:
        """Safely get system idle time."""

        try:

            return (
                self._provider
                .get_idle_seconds()
            )

        except Exception:  # noqa: BLE001

            logger.exception(
                "Platform provider failed "
                "to get idle seconds"
            )

            return 0.0

    # ==========================================================
    # STATE
    # ==========================================================

    def _state(
        self,
    ) -> TrackerState:
        """Return the current tracker state."""

        return TrackerState(
            is_tracking=self._is_tracking,

            is_idle=self._is_idle,

            current_application=(
                self._current.application_name
                if self._current
                else None
            ),

            current_window_title=(
                self._current.window_title
                if self._current
                else None
            ),

            idle_seconds=(
                self._last_idle_seconds
            ),
        )