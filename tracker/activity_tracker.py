"""Platform-independent activity tracking state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from typing import Callable

from database.repository import ActivityRepository
from platform_support.base import (
    ActiveApplication,
    PlatformActivityProvider,
)
from tracker.activity_session import CurrentSession
from utils.logger import get_logger

from services.activity_service import ActivityService
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

    is_workpulse: bool
    is_idle: bool
    current_application: str | None
    current_window_title: str | None
    idle_seconds: float

    @property
    def is_tracking(self) -> bool:
        """Alias for is_workpulse."""
        return self.is_workpulse


# ==============================================================
# ACTIVITY TRACKER
# ==============================================================


class ActivityTracker:
    """
    Core activity tracking state machine.

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
        screenshot_config=None,
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

        self._is_workpulse = False

        self._is_idle = False

        self._current: CurrentSession | None = None

        self._last_idle_seconds = 0.0

        from config.screenshot_config import ScreenshotConfig, get_screenshot_config
        self._screenshot_config: ScreenshotConfig = screenshot_config or get_screenshot_config()

        self._screenshot_interval_type = screenshot_interval_type

        self._screenshot_custom_interval_seconds = screenshot_custom_interval_seconds

        self._capture_on_switch = capture_on_switch

        self._last_screenshot_time = None
        self._window_last_screenshot_time = None
        self._last_captured_window_identity: tuple | None = None
        self._last_screenshot_attempt_time = None
        self._pending_switch_capture = False
        self._rapid_switch_debounce_seconds = 1.0
        self._default_same_window_interval_seconds = 1800.0  # 30 minutes
        self._window_last_capture_times: dict[tuple, datetime] = {}

        # Drives the periodic activity sync dynamically from API (sync_interval_seconds)
        self._last_sync_time = None
        self._last_settings_fetch_time = None

        # Tracks wall-clock timestamp between polls to detect system sleep / hibernate
        self._last_poll_time = None

        # Tracks idle state and timestamps to calculate and send idle time accurately
        self._idle_start_time = None
        self._last_active_session_id = None
        self._current_idle_session_id = None
        self._idle_application_name = None
        self._idle_process_id = None
        self._idle_window_title = None
        self._session_idle_base_seconds = 0
        self._last_resumed_idle_seconds = 0.0
        self._last_persisted_idle_seconds: int | None = None

    def _update_ongoing_idle_session(
        self,
        total_idle: int,
    ) -> None:
        """Update the ongoing session in database with the currently accumulated idle seconds."""
        target_id = self._current_idle_session_id or self._last_active_session_id
        if not target_id or total_idle <= 0:
            return
        if getattr(self, "_last_persisted_idle_seconds", None) == total_idle:
            return
        self._last_persisted_idle_seconds = total_idle
        db_session = self._session_factory()
        try:
            repo = ActivityRepository(db_session)
            repo.update_session_idle_seconds(target_id, total_idle)
        except Exception as err:
            logger.debug("Failed to update ongoing idle session #%s: %s", target_id, err)
        finally:
            db_session.close()

    @property
    def current_idle_session_id(self) -> int | None:
        """Return the session ID currently undergoing an unresolved idle state, if any."""
        if self._is_idle:
            return self._current_idle_session_id or self._last_active_session_id
        return None

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
        """Enable or disable window-title workpulse."""

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
        if interval_type == "custom" and custom_interval_seconds > 0:
            self._screenshot_config.screenshot_interval_minutes = float(custom_interval_seconds) / 60.0
        self._screenshot_config.capture_on_window_change = capture_on_switch

    def set_screenshot_config(self, config) -> None:
        """Update the active screenshot configuration."""
        self._screenshot_config = config

    @property
    def screenshot_config(self):
        """Return the active screenshot configuration."""
        return self._screenshot_config

    def _get_window_identity(
        self,
        application_name: str | None,
        process_id: int | None,
        window_title: str | None,
        window_handle: int | None = None,
    ) -> tuple:
        """Construct the strongest reliable window identity available.

        Uses native window handle + process ID + app name when window handle is available.
        Falls back to (application_name, process_id, title).
        """
        if window_handle is not None and window_handle != 0:
            return (window_handle, process_id, application_name or "")
        title = window_title if self._track_window_titles else None
        return (application_name or "", process_id, title)

    def _get_same_window_interval_seconds(self) -> float:
        """Return the same-window screenshot interval in seconds.

        Defaults to the configured screenshot_interval_minutes (30 minutes / 1800.0s).
        If legacy custom interval is configured and positive, respects that.
        """
        if (
            self._screenshot_interval_type == "custom"
            and self._screenshot_custom_interval_seconds > 0
        ):
            return float(self._screenshot_custom_interval_seconds)
        return self._screenshot_config.interval_seconds

    @property
    def is_workpulse(self) -> bool:
        """Return whether tracking/workpulse is currently active."""
        return self._is_workpulse

    @property
    def is_tracking(self) -> bool:
        """Return whether tracking is currently active (alias for is_workpulse)."""
        return self._is_workpulse

    @property
    def is_idle(self) -> bool:
        """Return whether the user is currently idle."""

        return self._is_idle

    # ==========================================================
    # START
    # ==========================================================

    def start(self) -> None:
        """
        Start activity tracking.

        Any stale open database session from a previous
        application run is closed first.
        """

        if self._is_workpulse:
            return

        try:
            logger.info(
                "Starting activity tracker"
            )

            self._close_stale_database_session()

            self._is_workpulse = True

            self._is_idle = False

            self._current = None

            self._last_idle_seconds = 0.0
            self._session_idle_base_seconds = 0
            self._last_resumed_idle_seconds = 0.0
            self._last_persisted_idle_seconds = None

            self._last_screenshot_time = self._clock()
            self._window_last_screenshot_time = None
            self._last_captured_window_identity = None
            self._last_screenshot_attempt_time = None
            self._pending_switch_capture = False

            # Record system and workpulse start time
            try:
                from services.attendance_service import AttendanceService
                AttendanceService().record_workpulse_start()
            except Exception as att_err:
                logger.debug("Could not record workpulse start time in AttendanceService: %s", att_err)

            logger.info(
                "Activity tracker started"
            )

            # A previous run may have collected logs it never managed to send
            # (no connection, or the machine was shut down). Push those now
            # rather than making them wait a full cycle. Run on a daemon thread
            # so tracker startup and initial polling are never blocked by network latency.
            self._last_sync_time = self._clock()
            self._last_settings_fetch_time = self._clock()

            import threading
            threading.Thread(target=self._sync_activity, name="StartupActivitySync", daemon=True).start()

        except Exception as exc:
            self._is_workpulse = False
            logger.exception("Failed to start activity tracker")
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="TRACKER_START_ERROR",
                    error_message=f"Failed to start activity tracker: {exc}",
                    exc=exc,
                )
            except Exception:
                pass
            raise

    # ==========================================================
    # STOP
    # ==========================================================

    def stop(self) -> None:
        """Stop workpulse and close the current session."""

        if not self._is_workpulse:
            return

        try:
            logger.info(
                "Stopping activity tracker"
            )

            # If user was idle when stopping, persist final idle duration to database session
            if self._is_idle and self._idle_start_time is not None:
                target_id = self._current_idle_session_id or self._last_active_session_id
                if target_id is not None:
                    now = self._clock()
                    current_idle = max(0, int((now - self._idle_start_time).total_seconds()))
                    if current_idle <= 7200:
                        total_idle = int(self._session_idle_base_seconds + current_idle)
                        db_session = self._session_factory()
                        try:
                            repo = ActivityRepository(db_session)
                            repo.update_session_idle_seconds(target_id, total_idle)
                            logger.info(
                                "Persisted final idle on stop: session_id=%s idle_seconds=%d",
                                target_id,
                                total_idle,
                            )
                        except Exception as idle_err:
                            logger.error("Failed to persist final idle on stop: %s", idle_err)
                        finally:
                            db_session.close()

            self._close_current_session()

            self._is_workpulse = False

            self._is_idle = False

            self._last_idle_seconds = 0.0
            self._session_idle_base_seconds = 0
            self._last_resumed_idle_seconds = 0.0
            self._last_persisted_idle_seconds = None
            self._current_idle_session_id = None
            self._last_active_session_id = None
            self._idle_start_time = None
            self._window_last_screenshot_time = None
            self._last_captured_window_identity = None
            self._last_screenshot_attempt_time = None
            self._pending_switch_capture = False

            logger.info(
                "Activity tracker stopped"
            )
        except Exception as exc:
            logger.exception("Failed to stop activity tracker cleanly")
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="TRACKER_STOP_ERROR",
                    error_message=f"Failed to stop activity tracker cleanly: {exc}",
                    exc=exc,
                )
            except Exception:
                pass
            raise

    # ==========================================================
    # MAIN POLLING LOOP
    # ==========================================================

    def poll(self) -> TrackerState:
        """
        Perform one workpulse tick.

        The worker should normally call this once per second.
        """

        if not self._is_workpulse:
            return self._state()

        try:
            now = self._clock()

            # --------------------------------------------------
            # System sleep / hibernate / suspend detection.
            #
            # The timer polls every ~1s. If the wall-clock elapsed time
            # between polls exceeds 10s, the laptop went to sleep or hibernated.
            # Reinitialize state and close pre-sleep session so sleep time is
            # NEVER counted as working or idle time.
            # --------------------------------------------------
            if self._last_poll_time is not None:
                gap_seconds = (now - self._last_poll_time).total_seconds()
                if gap_seconds > 10.0:
                    logger.info(
                        "System sleep / suspend detected: elapsed %.1fs between polls. "
                        "Reinitializing tracker state after resume.",
                        gap_seconds,
                    )
                    self.handle_system_resume(now=now)

            self._last_poll_time = now

            # --------------------------------------------------
            # Get idle time.
            # --------------------------------------------------

            prev_idle = self._last_idle_seconds
            idle_seconds = (
                self._safe_get_idle_seconds()
            )

            self._last_idle_seconds = (
                idle_seconds
            )

            # Dynamically adopt API-driven idle threshold from SyncService
            if self._sync_service is not None:
                api_idle = getattr(self._sync_service, "current_idle_threshold_seconds", None)
                if api_idle is not None:
                    try:
                        api_idle_int = int(api_idle)
                        if api_idle_int > 0 and api_idle_int != self._idle_threshold_seconds:
                            logger.info(
                                "ActivityTracker: Updating idle_threshold_seconds from API: %d seconds (previous: %d seconds)",
                                api_idle_int,
                                self._idle_threshold_seconds,
                            )
                            self._idle_threshold_seconds = api_idle_int
                    except (ValueError, TypeError):
                        pass

            was_idle = self._is_idle

            is_locked = False
            if hasattr(self._provider, "is_workstation_locked"):
                try:
                    is_locked = bool(self._provider.is_workstation_locked())
                except Exception:
                    is_locked = False

            now_idle = (
                idle_seconds >= self._idle_threshold_seconds
                or is_locked
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

            elif not now_idle and not was_idle and prev_idle > 0 and idle_seconds == 0:

                # User was idling for a short period (< threshold) and returned to active
                self._last_resumed_idle_seconds = float(prev_idle)

            self._is_idle = now_idle

            # Update ongoing idle session with latest calculated idle
            if self._is_idle and self._idle_start_time is not None:
                current_idle = max(0, int((now - self._idle_start_time).total_seconds()))
                if current_idle <= 7200:
                    total_idle = int(self._session_idle_base_seconds + current_idle)
                    self._update_ongoing_idle_session(total_idle)

            # --------------------------------------------------
            # Track active application.
            # --------------------------------------------------

            if not self._is_idle:

                self._poll_active_application()

                # Check screenshot interval scheduler
                now = self._clock()

                # Handle pending debounced screenshot capture if focus has settled
                if (
                    self._pending_switch_capture
                    and self._current is not None
                    and self._capture_on_switch
                    and self._screenshot_config.should_capture_on_window_change()
                ):
                    time_since_last = (
                        (now - self._last_screenshot_attempt_time).total_seconds()
                        if self._last_screenshot_attempt_time is not None
                        else 999999.0
                    )
                    if time_since_last >= self._rapid_switch_debounce_seconds:
                        self._capture_screenshot_for_current_session()
                        self._window_last_screenshot_time = now
                        self._last_screenshot_attempt_time = now
                        self._pending_switch_capture = False

                # Same-window interval scheduler (active in 'interval' or 'both' mode):
                if self._screenshot_config.should_capture_on_interval() and self._current is not None:
                    interval_seconds = self._get_same_window_interval_seconds()
                    current_window_id = self._get_window_identity(
                        self._current.application_name,
                        self._current.process_id,
                        self._current.window_title,
                        window_handle=getattr(self._current, "window_handle", None),
                    )

                    last_capture = self._window_last_capture_times.get(
                        current_window_id, self._window_last_screenshot_time
                    )
                    if last_capture is None:
                        self._window_last_capture_times[current_window_id] = now
                        self._window_last_screenshot_time = now
                    else:
                        elapsed = (now - last_capture).total_seconds()
                        if elapsed >= interval_seconds:
                            logger.info(
                                "Same window active for %.1f min (interval=%.1f min). Capturing periodic screenshot.",
                                elapsed / 60.0,
                                interval_seconds / 60.0,
                            )
                            saved = self._capture_screenshot_for_current_session()
                            if saved:
                                self._window_last_capture_times[current_window_id] = now
                            self._window_last_screenshot_time = now
                            self._last_screenshot_attempt_time = now

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

            # Refresh dynamic settings periodically from API so changes like 300s -> 60s
            # are adopted promptly without waiting for a lengthy sync cycle or rebuilding.
            if self._sync_service is not None:
                if self._last_settings_fetch_time is None:
                    self._last_settings_fetch_time = now
                elif (now - self._last_settings_fetch_time).total_seconds() >= min(sync_interval, 60.0):
                    self._last_settings_fetch_time = now
                    if self._clock is not _default_clock:
                        try:
                            self._sync_service.fetch_settings()
                            sync_interval = self._get_sync_interval_seconds()
                        except Exception as fetch_err:
                            logger.debug("Periodic settings fetch deferred: %s", fetch_err)
                    elif not getattr(self, "_settings_fetching", False):
                        self._settings_fetching = True
                        def _bg_fetch():
                            try:
                                self._sync_service.fetch_settings()
                            except Exception as fetch_err:
                                logger.debug("Periodic settings fetch deferred: %s", fetch_err)
                            finally:
                                self._settings_fetching = False
                        threading.Thread(target=_bg_fetch, name="TrackerSettingsFetch", daemon=True).start()

            if self._last_sync_time is None:
                self._last_sync_time = now

            elif (now - self._last_sync_time).total_seconds() >= sync_interval:
                self._last_sync_time = now

                from datetime import timedelta
                next_sync_dt = now + timedelta(seconds=sync_interval)
                logger.info(
                    "Activity sync interval reached (%d seconds / %.1f min). Next sync scheduled for %s",
                    sync_interval,
                    sync_interval / 60.0,
                    next_sync_dt.strftime("%Y-%m-%d %H:%M:%S"),
                )

                self._sync_activity()

        except Exception as exc:  # noqa: BLE001

            logger.exception(
                "Unexpected error during tracker poll()"
            )
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="TRACKER_POLL_ERROR",
                    error_message=f"Unexpected error during tracker poll(): {exc}",
                    exc=exc,
                )
            except Exception:
                pass

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

        # Check calendar date rollover: if the day changed while workpulse,
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

        current_window_id = self._get_window_identity(
            active.application_name,
            active.process_id,
            title,
            window_handle=getattr(active, "window_handle", None),
        )

        if self._current is None:

            self._open_new_session(
                active,
                title,
            )

            if (
                self._capture_on_switch
                and self._screenshot_config.should_capture_on_window_change()
            ):
                saved = self._capture_screenshot_for_current_session()
                if saved:
                    self._window_last_capture_times[current_window_id] = now
                self._window_last_screenshot_time = now
                self._last_captured_window_identity = current_window_id
                self._last_screenshot_attempt_time = now
                self._pending_switch_capture = False
            else:
                self._window_last_screenshot_time = now
                if current_window_id not in self._window_last_capture_times:
                    self._window_last_capture_times[current_window_id] = now
                self._last_captured_window_identity = current_window_id
                self._last_screenshot_attempt_time = None
                self._pending_switch_capture = False

            return

        # ------------------------------------------------------
        # Same application + same process + same window title.
        # ------------------------------------------------------

        active_hwnd = getattr(active, "window_handle", None)
        curr_hwnd = getattr(self._current, "window_handle", None)
        is_same_window = (
            self._current.matches_application(
                active.application_name,
                active.process_id,
            )
            and (
                not self._track_window_titles
                or title == self._current.window_title
            )
            and (
                active_hwnd is None
                or curr_hwnd is None
                or active_hwnd == curr_hwnd
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
        # Capture screenshot for NEW session if window-change mode is active.
        # ------------------------------------------------------

        screenshot_path = None
        if (
            self._capture_on_switch
            and self._screenshot_config.should_capture_on_window_change()
        ):
            time_since_last_attempt = (
                (now - self._last_screenshot_attempt_time).total_seconds()
                if self._last_screenshot_attempt_time is not None
                else 999999.0
            )

            # Avoid duplicate screenshots on rapid focus bounce back to recently captured window
            if (
                self._last_captured_window_identity == current_window_id
                and time_since_last_attempt < self._get_same_window_interval_seconds()
            ):
                logger.debug(
                    "Rapid focus switch back to recently captured window %s ignored",
                    current_window_id,
                )
                self._pending_switch_capture = False
            elif time_since_last_attempt < self._rapid_switch_debounce_seconds:
                logger.debug(
                    "Rapid focus switch detected (%.2fs < %.2fs); deferring capture until focus settles",
                    time_since_last_attempt,
                    self._rapid_switch_debounce_seconds,
                )
                self._pending_switch_capture = True
            else:
                screenshot_path = (
                    self._capture_screenshot_for_current_session()
                )
                if screenshot_path:
                    self._window_last_capture_times[current_window_id] = now
                self._window_last_screenshot_time = now
                self._last_captured_window_identity = current_window_id
                self._last_screenshot_attempt_time = now
                self._pending_switch_capture = False
        else:
            # Window-change capture is disabled (e.g. interval-only mode)
            self._window_last_screenshot_time = now
            if current_window_id not in self._window_last_capture_times:
                self._window_last_capture_times[current_window_id] = now
            self._last_captured_window_identity = current_window_id
            self._pending_switch_capture = False

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

        if not self._screenshot_config.screenshot_enabled:
            logger.debug("Screenshot capture is disabled in configuration.")
            return None

        if self._current is None:

            logger.warning(
                "Cannot capture screenshot: "
                "there is no current session"
            )

            return None

        now = self._clock()
        self._last_screenshot_time = now
        self._window_last_screenshot_time = now
        self._last_screenshot_attempt_time = now
        if self._current is not None:
            current_id = self._get_window_identity(
                self._current.application_name,
                self._current.process_id,
                self._current.window_title,
                window_handle=getattr(self._current, "window_handle", None),
            )
            self._last_captured_window_identity = current_id
            self._window_last_capture_times[current_id] = now

        # If current session already has a screenshot associated, checkpoint the session
        # so this periodic screenshot belongs to a new contiguous segment and does not overwrite.
        has_existing_screenshot = False
        db_session = self._session_factory()
        try:
            from database.models import ActivitySession
            rec = db_session.get(ActivitySession, self._current.db_id)
            if rec and rec.screenshot_path:
                has_existing_screenshot = True
        except Exception:
            pass
        finally:
            db_session.close()

        if has_existing_screenshot:
            now = self._clock()
            active_app = ActiveApplication(self._current.application_name, self._current.process_id)
            title = self._current.window_title
            self._close_current_session_at(now)
            self._open_new_session(active_app, title)

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

            from services.session_service import SessionService
            curr_user = SessionService().current_user
            emp_id = None
            if curr_user:
                emp_id = curr_user.employee_id or curr_user.indo_code or curr_user.username or None
            if not emp_id:
                try:
                    from services.secure_session import SessionStore
                    saved = SessionStore().load_session()
                    if saved:
                        emp_id = saved.get("employee_id") or saved.get("indo_code") or saved.get("username") or None
                except Exception:
                    pass

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
                    employee_id=emp_id,
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
                idle_seconds=0,
                window_handle=getattr(active, "window_handle", None),
            )
            self._session_idle_base_seconds = 0

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
        current_idle = self._current.idle_seconds

        db_session = self._session_factory()
        try:
            repository = ActivityRepository(db_session)
            repository.close_session(session_id, ended_at, idle_seconds=current_idle)
            logger.info(
                "Closed session: app=%s session_id=%s ended_at=%s idle_seconds=%s",
                application_name,
                session_id,
                ended_at,
                current_idle,
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
            repository.update_session_heartbeat(self._current.db_id, now, idle_seconds=self._current.idle_seconds)
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
    # POWER / SLEEP / RESUME MANAGEMENT
    # ==========================================================

    def handle_system_suspend(self, now: datetime | None = None) -> None:
        """Handle system entering sleep or hibernate mode."""
        suspend_time = now or self._clock()
        logger.info("ActivityTracker: System entering sleep/suspend. Closing active session cleanly at %s", suspend_time)

        if self._current is not None:
            self._close_current_session_at(suspend_time)
        elif self._is_idle and self._idle_start_time and self._last_active_session_id:
            current_idle = max(0, int((suspend_time - self._idle_start_time).total_seconds()))
            if current_idle <= 7200:
                total_idle = int(self._session_idle_base_seconds + current_idle)
                db_session = self._session_factory()
                try:
                    repo = ActivityRepository(db_session)
                    repo.update_session_idle_seconds(self._last_active_session_id, total_idle)
                    logger.info(
                        "Persisted final idle on suspend: session_id=%s idle_seconds=%d",
                        self._last_active_session_id,
                        total_idle,
                    )
                except Exception as idle_err:
                    logger.error("Failed to persist final idle on suspend: %s", idle_err)
                finally:
                    db_session.close()

        self._is_idle = False
        self._idle_start_time = None
        self._last_active_session_id = None
        self._current_idle_session_id = None
        self._idle_application_name = None
        self._idle_process_id = None
        self._idle_window_title = None
        self._session_idle_base_seconds = 0
        self._last_resumed_idle_seconds = 0.0
        self._last_persisted_idle_seconds = None
        self._last_poll_time = suspend_time

    def handle_system_resume(self, now: datetime | None = None) -> None:
        """Handle system resume from sleep or hibernate mode."""
        resume_time = now or self._clock()
        logger.info("ActivityTracker: System resumed from sleep/suspend at %s. Resetting idle state.", resume_time)

        # Close previous active session at last active time before sleep so sleep is never counted
        if self._current is not None:
            close_at = self._last_poll_time or resume_time
            self._close_current_session_at(close_at)

        # Reset all stale idle workpulse states
        self._is_idle = False
        self._idle_start_time = None
        self._last_active_session_id = None
        self._current_idle_session_id = None
        self._idle_application_name = None
        self._idle_process_id = None
        self._idle_window_title = None
        self._last_idle_seconds = 0.0
        self._session_idle_base_seconds = 0
        self._last_resumed_idle_seconds = 0.0
        self._last_persisted_idle_seconds = None

        # Reset poll timing marker to current wake time
        self._last_poll_time = resume_time

        # Reinitialize platform provider / idle detector
        if hasattr(self._provider, "reset_after_resume"):
            try:
                self._provider.reset_after_resume()
            except Exception as reset_err:
                logger.debug("Provider reset_after_resume failed: %s", reset_err)

        # Immediately check active application so workpulse resumes
        if self._is_workpulse:
            self._poll_active_application()

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

        idle_app = self._current.application_name if self._current else "Unknown"
        session_id = self._current.db_id if self._current else None
        logger.info(
            "[IDLE_DETECTED] timestamp=%s last_input_time=%s session_id=%s app=%s idle_seconds=%.1fs threshold=%ss",
            now.strftime("%Y-%m-%d %H:%M:%S"),
            last_input_time.strftime("%Y-%m-%d %H:%M:%S"),
            session_id,
            idle_app,
            idle_seconds,
            self._idle_threshold_seconds,
        )

        if self._current is not None:
            self._last_active_session_id = self._current.db_id
            self._current_idle_session_id = self._current.db_id
            self._idle_application_name = self._current.application_name
            self._idle_process_id = self._current.process_id
            self._idle_window_title = self._current.window_title
            self._session_idle_base_seconds = self._current.idle_seconds or 0
            self._close_current_session_at(last_input_time)

            # Immediately persist initial idle elapsed up to now
            initial_idle = int((now - last_input_time).total_seconds())
            if initial_idle > 0:
                self._update_ongoing_idle_session(self._session_idle_base_seconds + initial_idle)
        else:
            self._last_active_session_id = None
            self._current_idle_session_id = None
            self._idle_application_name = None
            self._idle_process_id = None
            self._idle_window_title = None
            self._session_idle_base_seconds = 0

    # ==========================================================
    # ACTIVE AGAIN
    # ==========================================================

    def _on_became_active(
        self,
    ) -> None:
        """Handle activity resuming after idle."""

        now = self._clock()
        idle_duration = 0
        idle_start_str = "None"
        if self._idle_start_time:
            idle_start_str = self._idle_start_time.strftime("%Y-%m-%d %H:%M:%S")
            idle_duration = max(0, int((now - self._idle_start_time).total_seconds()))
            # Sanity clamp: if idle duration spans across sleep/offline (> 2 hours),
            # discard it so sleep time is never saved as session idle time
            if idle_duration > 7200:
                logger.warning(
                    "Sanitizing anomalous idle duration spanning sleep/offline: %ds -> 0s",
                    idle_duration,
                )
                idle_duration = 0

        app_name = getattr(self, "_idle_application_name", None) or "Unknown"
        session_id = getattr(self, "_last_active_session_id", None)
        try:
            formatted_duration = ActivityService.format_duration(idle_duration)
        except Exception:
            formatted_duration = f"{idle_duration}s"

        logger.info(
            "[IDLE_RESUMED] timestamp=%s idle_start=%s resumed_at=%s calculated_idle_duration=%ds (%s) session_id=%s app=%s",
            now.strftime("%Y-%m-%d %H:%M:%S"),
            idle_start_str,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            idle_duration,
            formatted_duration,
            session_id,
            app_name,
        )

        final_idle = int(self._session_idle_base_seconds + idle_duration)
        if self._last_active_session_id and final_idle > 0:
            db_session = self._session_factory()
            try:
                repo = ActivityRepository(db_session)
                repo.update_session_idle_seconds(self._last_active_session_id, final_idle)
                logger.info(
                    "[DATABASE_UPDATE_RESULT] Session #%s idle_seconds updated: prev=%ds added=%ds total=%ds",
                    self._last_active_session_id,
                    self._session_idle_base_seconds,
                    idle_duration,
                    final_idle,
                )
            except Exception as err:
                logger.error("Failed to update idle seconds for session %s: %s", self._last_active_session_id, err)
            finally:
                db_session.close()

        # Check foreground application immediately upon resumption
        active = self._safe_get_active_application()
        title = active.window_title if (active and self._track_window_titles) else None

        # Multiple idle periods in one session:
        # If the user resumed in the exact same application and process, resume the session
        # so multiple idle intervals within the same application session accumulate together.
        same_session = False
        if (
            self._last_active_session_id is not None
            and active is not None
            and active.application_name == getattr(self, "_idle_application_name", None)
            and active.process_id == getattr(self, "_idle_process_id", None)
        ):
            db_session = self._session_factory()
            try:
                from database.models import ActivitySession
                record = db_session.get(ActivitySession, self._last_active_session_id)
                if record is not None:
                    # Re-open the session by clearing ended_at so subsequent work continues in this session
                    record.ended_at = None
                    db_session.commit()
                    self._current = CurrentSession(
                        db_id=record.id,
                        application_name=record.application_name,
                        process_id=record.process_id,
                        window_title=record.window_title,
                        started_at=record.started_at,
                        idle_seconds=record.idle_seconds or 0,
                    )
                    same_session = True
                    logger.info(
                        "Resumed ongoing session #%s for app=%s (idle accumulated: %ds)",
                        record.id,
                        record.application_name,
                        record.idle_seconds,
                    )
            except Exception as resume_err:
                logger.debug("Failed to re-open previous session for same app: %s", resume_err)
            finally:
                db_session.close()

        if not same_session:
            # Active application changed while idle or new app was brought forward
            self._last_active_session_id = None

        self._idle_start_time = None
        self._idle_application_name = None
        self._idle_process_id = None
        self._idle_window_title = None
        self._current_idle_session_id = None
        self._is_idle = False
        self._last_resumed_idle_seconds = float(idle_duration)
        self._last_idle_seconds = 0.0
        self._last_persisted_idle_seconds = None

    # ==========================================================
    # ACTIVITY SYNC
    # ==========================================================

    def _get_sync_interval_seconds(self) -> int:
        """Return the current sync interval in seconds dynamically from SyncService."""
        if self._sync_service is not None:
            configured = getattr(self._sync_service, "current_sync_interval_seconds", None)
            if configured is not None:
                try:
                    val = int(configured)
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    pass
            # Try to load cached API setting if not yet loaded in memory
            cached_fn = getattr(self._sync_service, "_load_cached_setting", None)
            if callable(cached_fn):
                val = cached_fn("sync_interval_seconds")
                if val is not None:
                    try:
                        val_int = int(val)
                        if val_int > 0:
                            return val_int
                    except (ValueError, TypeError):
                        pass
        return 60

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

        sync_lock = getattr(self._sync_service, "_sync_lock", None)
        if sync_lock is not None and hasattr(sync_lock, "locked"):
            try:
                if sync_lock.locked() is True:
                    logger.info("Activity sync already running in background; skipping duplicate trigger.")
                    return
            except Exception:
                pass

        try:
            # Checkpoint the current active session at now so all synced sessions
            # have a definitive start and end time without overlap or open guessing.
            now = self._clock()
            if self._current is not None:
                active_app = ActiveApplication(self._current.application_name, self._current.process_id)
                title = self._current.window_title
                self._close_current_session_at(now)
                self._open_new_session(active_app, title)

            exclude_ids = [self.current_idle_session_id] if self.current_idle_session_id else None

            def _run_sync():
                try:
                    if exclude_ids:
                        try:
                            success = self._sync_service.sync_activity_now(exclude_session_ids=exclude_ids)
                        except TypeError:
                            success = self._sync_service.sync_activity_now()
                    else:
                        success = self._sync_service.sync_activity_now()
                    if success:
                        logger.info("Activity sync completed")
                    else:
                        logger.warning("Activity sync failed")
                except Exception as sync_err:
                    logger.exception("Activity sync background thread error: %s", sync_err)

            threading.Thread(target=_run_sync, name="ActivitySyncWorker", daemon=True).start()

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Activity sync raised an exception"
            )
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="SYNC_TRIGGER_ERROR",
                    error_message=f"Activity sync trigger raised an exception: {exc}",
                    exc=exc,
                )
            except Exception:
                pass

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

        except Exception as exc:  # noqa: BLE001

            logger.exception(
                "Platform provider failed "
                "to get active application"
            )
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="APPLICATION_DETECTION_ERROR",
                    error_message=f"Platform provider failed to get active application: {exc}",
                    exc=exc,
                )
            except Exception:
                pass

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

        except Exception as exc:  # noqa: BLE001

            logger.exception(
                "Platform provider failed "
                "to get idle seconds"
            )
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="IDLE_DETECTION_ERROR",
                    error_message=f"Platform provider failed to get idle seconds: {exc}",
                    exc=exc,
                )
            except Exception:
                pass

            return 0.0

    # ==========================================================
    # STATE
    # ==========================================================

    def _state(
        self,
    ) -> TrackerState:
        """Return the current tracker state."""

        if self._is_idle:
            if self._idle_start_time is not None:
                current_idle = max(0.0, (self._clock() - self._idle_start_time).total_seconds())
                effective_idle = float(self._session_idle_base_seconds + current_idle)
            else:
                effective_idle = float(self._last_idle_seconds)
        elif self._last_idle_seconds > 0:
            effective_idle = float(self._last_idle_seconds)
        else:
            if self._current is not None and self._current.idle_seconds > 0:
                effective_idle = float(self._current.idle_seconds)
            else:
                effective_idle = float(self._last_resumed_idle_seconds)

        if self._is_idle:
            idle_int = max(0, int(effective_idle))
            h = idle_int // 3600
            m = (idle_int % 3600) // 60
            s = idle_int % 60
            idle_win_title = f"Idle - {h:02d}:{m:02d}:{s:02d}"
            app_name = self._current.application_name if self._current else (self._idle_application_name or "Idle")
        else:
            idle_win_title = self._current.window_title if self._current else None
            app_name = self._current.application_name if self._current else None

        return TrackerState(
            is_workpulse=self._is_workpulse,

            is_idle=self._is_idle,

            current_application=app_name,

            current_window_title=idle_win_title,

            idle_seconds=effective_idle,
        )