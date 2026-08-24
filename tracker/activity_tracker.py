"""Platform-independent activity tracking state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from database.repository import ActivityRepository
from platform_support.base import (
    ActiveApplication,
    PlatformActivityProvider,
)
from tracker.activity_session import CurrentSession
from utils.logger import get_logger

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

                self._on_became_idle()

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
        # Same application + same process.
        # ------------------------------------------------------

        if self._current.matches_application(
            active.application_name,
            active.process_id,
        ):

            # --------------------------------------------------
            # Only update window title.
            # --------------------------------------------------

            if (
                title
                != self._current.window_title
            ):

                self._current.window_title = (
                    title
                )

                self._update_session_title(
                    title
                )

                if self._capture_on_switch:
                    self._capture_screenshot_for_current_session()

            return

        # ======================================================
        # APPLICATION CHANGED
        # ======================================================

        previous_application = (
            self._current.application_name
        )

        previous_session_id = (
            self._current.db_id
        )

        logger.info(
            "Application changed: "
            "%s -> %s",
            previous_application,
            active.application_name,
        )

        logger.info(
            "Closing previous session: "
            "id=%s app=%s",
            previous_session_id,
            previous_application,
        )

        # ------------------------------------------------------
        # STEP 1:
        # Close OLD session.
        # ------------------------------------------------------

        self._close_current_session()

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
        # Sync activity.
        # ------------------------------------------------------

        self._sync_activity()

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

            original_path = capture_screenshot()

            if not original_path:

                logger.warning(
                    "capture_screenshot() returned None "
                    "for session=%s",
                    session_id,
                )

                return None

            original_path = Path(
                original_path
            )

            if not original_path.exists():

                logger.warning(
                    "Screenshot path does not exist: %s",
                    original_path,
                )

                return None

            # --------------------------------------------------
            # Create session-specific filename.
            # --------------------------------------------------

            timestamp = (
                datetime.now().strftime(
                    "%Y-%m-%d_%H-%M-%S-%f"
                )
            )

            new_filename = (
                f"session_{session_id}_"
                f"{timestamp}"
                f"{original_path.suffix or '.png'}"
            )

            new_path = (
                original_path.parent
                / new_filename
            )

            # --------------------------------------------------
            # Rename the screenshot.
            # --------------------------------------------------

            original_path.rename(
                new_path
            )

            logger.info(
                "Screenshot saved: "
                "session=%s path=%s",
                session_id,
                new_path,
            )

            return str(new_path)

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

    def _close_current_session(
        self,
    ) -> None:
        """Close the currently tracked session."""

        if self._current is None:
            return

        now = self._clock()

        session_id = (
            self._current.db_id
        )

        application_name = (
            self._current.application_name
        )

        db_session = (
            self._session_factory()
        )

        try:

            repository = (
                ActivityRepository(
                    db_session
                )
            )

            repository.close_session(
                session_id,
                now,
            )

            logger.info(
                "Closed session: "
                "app=%s session_id=%s",
                application_name,
                session_id,
            )

        finally:

            db_session.close()

            self._current = None

    # ==========================================================
    # CLOSE STALE DATABASE SESSION
    # ==========================================================

    def _close_stale_database_session(
        self,
    ) -> None:
        """
        Close an old open session from a previous tracker run.
        """

        db_session = (
            self._session_factory()
        )

        try:

            repository = (
                ActivityRepository(
                    db_session
                )
            )

            stale_session = (
                repository.get_open_session()
            )

            if stale_session is None:
                return

            logger.warning(
                "Found stale open session: "
                "id=%s app=%s started_at=%s",
                stale_session.id,
                stale_session.application_name,
                stale_session.started_at,
            )

            repository.close_session(
                stale_session.id,
                self._clock(),
            )

            logger.info(
                "Stale session closed: id=%s",
                stale_session.id,
            )

        except Exception:  # noqa: BLE001

            logger.exception(
                "Failed to close stale "
                "database session"
            )

        finally:

            db_session.close()

    # ==========================================================
    # IDLE
    # ==========================================================

    def _on_became_idle(
        self,
    ) -> None:
        """Handle the user becoming idle."""

        logger.info(
            "User became idle; "
            "closing current session"
        )

        self._close_current_session()

    # ==========================================================
    # ACTIVE AGAIN
    # ==========================================================

    def _on_became_active(
        self,
    ) -> None:
        """
        Handle activity resuming after idle.

        The next poll creates a new session and captures
        its screenshot.
        """

        logger.info(
            "User activity resumed after idle"
        )

    # ==========================================================
    # ACTIVITY SYNC
    # ==========================================================

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