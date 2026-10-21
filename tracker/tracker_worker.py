"""Qt worker that runs :class:`tracker.activity_tracker.ActivityTracker`.

The tracker's own logic (session open/close, idle detection) is completely
Qt-free and unit-tested on its own. This module is the thin adapter that
runs it on a background ``QThread`` using a ``QTimer`` and re-emits its
state as Qt signals for the GUI to consume - the GUI thread is never
blocked.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from config.settings import POLL_INTERVAL_SECONDS
from tracker.activity_tracker import ActivityTracker, TrackerState
from utils.logger import get_logger

logger = get_logger(__name__)


class TrackerWorker(QObject):
    """Lives on a background ``QThread``; polls the tracker on a QTimer.

    Signals:
        state_changed: emitted after every poll with the latest TrackerState.
        workpulse_started: emitted once workpulse actually begins.
        workpulse_stopped: emitted once workpulse has fully stopped and any
            open session has been closed.
    """

    state_changed = Signal(object)  # TrackerState
    workpulse_started = Signal()
    workpulse_stopped = Signal()
    tracking_started = workpulse_started
    tracking_stopped = workpulse_stopped

    def __init__(self, tracker: ActivityTracker, poll_interval_seconds: float = POLL_INTERVAL_SECONDS) -> None:
        super().__init__()
        self._tracker = tracker
        self._poll_interval_ms = int(poll_interval_seconds * 1000)
        self._timer: QTimer | None = None

    # -- slots (invoked via signal/queued-connection from the GUI thread) -----

    @Slot()
    def setup(self) -> None:
        """Create the QTimer. Must be called after this object has moved to its thread."""
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(self._poll_interval_ms)
            self._timer.timeout.connect(self._on_tick)
        if self._tracker.is_workpulse and not self._timer.isActive():
            self._timer.start()

    @Slot()
    def start_workpulse(self) -> None:
        try:
            if self._timer is not None and self._timer.isActive() and self._tracker.is_workpulse:
                logger.debug("TrackerWorker: tracking timer is already active, ignoring duplicate start")
                return
            if self._timer is None:
                self.setup()
            self._tracker.start()
            if self._timer is not None and not self._timer.isActive():
                self._timer.start()
            logger.info("TrackerWorker: tracking started")
            self.workpulse_started.emit()
            # Immediately execute an initial poll so the GUI receives active state instantly
            self._on_tick()
        except Exception as exc:  # noqa: BLE001
            logger.exception("TrackerWorker failed to start tracking")
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="TRACKING_START_ERROR",
                    error_message=f"TrackerWorker failed to start tracking: {exc}",
                    exc=exc,
                )
            except Exception:
                pass

    start_tracking = start_workpulse

    @Slot()
    def stop_workpulse(self) -> None:
        try:
            if not self._tracker.is_workpulse and (self._timer is None or not self._timer.isActive()):
                logger.debug("TrackerWorker: tracking is already stopped, ignoring duplicate stop")
                return
            if self._timer is not None:
                self._timer.stop()
            self._tracker.stop()
            logger.info("TrackerWorker: tracking stopped")
            self.workpulse_stopped.emit()
            self.state_changed.emit(self._tracker.poll())
        except Exception as exc:  # noqa: BLE001
            logger.exception("TrackerWorker failed to stop tracking cleanly")
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="TRACKING_STOP_ERROR",
                    error_message=f"TrackerWorker failed to stop tracking cleanly: {exc}",
                    exc=exc,
                )
            except Exception:
                pass

    stop_tracking = stop_workpulse

    @Slot()
    def cleanup(self) -> None:
        """Stop tracking timer and tracker instance before thread exit."""
        try:
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
            if self._tracker.is_workpulse:
                self._tracker.stop()
                logger.info("TrackerWorker: tracking stopped on cleanup")
        except Exception as exc:  # noqa: BLE001
            logger.debug("TrackerWorker cleanup error: %s", exc)

    @Slot(float, bool, str, int, bool)
    def apply_settings(self, idle_threshold_seconds: float, track_window_titles: bool,
                       screenshot_interval_type: str, screenshot_custom_interval_seconds: int,
                       capture_on_switch: bool) -> None:
        self._tracker.set_idle_threshold(idle_threshold_seconds)
        self._tracker.set_track_window_titles(track_window_titles)
        self._tracker.set_screenshot_settings(
            screenshot_interval_type,
            screenshot_custom_interval_seconds,
            capture_on_switch
        )

    @Slot()
    def handle_system_suspend(self) -> None:
        try:
            self._tracker.handle_system_suspend()
        except Exception:
            logger.exception("TrackerWorker failed to handle system suspend")

    @Slot()
    def handle_system_resume(self) -> None:
        try:
            self._tracker.handle_system_resume()
            self._on_tick()
        except Exception:
            logger.exception("TrackerWorker failed to handle system resume")

    # -- internal ---------------------------------------------------------------

    def _on_tick(self) -> None:
        try:
            state: TrackerState = self._tracker.poll()
            self.state_changed.emit(state)
        except Exception as exc:
            logger.exception("Unexpected exception during TrackerWorker._on_tick: %s", exc)
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="TRACKER_WORKER_TICK_ERROR",
                    error_message=f"TrackerWorker._on_tick failed: {exc}",
                    exc=exc,
                )
            except Exception:
                pass


def build_tracker_thread(tracker: ActivityTracker) -> tuple[QThread, TrackerWorker]:
    """Construct a QThread + TrackerWorker pair, wired together correctly.

    The caller owns the returned objects and is responsible for calling
    ``thread.start()`` and, on shutdown, ``thread.quit()`` / ``thread.wait()``.
    """
    thread = QThread()
    worker = TrackerWorker(tracker)
    worker.moveToThread(thread)
    thread.started.connect(worker.setup)
    thread.finished.connect(worker.deleteLater)
    return thread, worker
