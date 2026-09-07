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
        tracking_started: emitted once tracking actually begins.
        tracking_stopped: emitted once tracking has fully stopped and any
            open session has been closed.
    """

    state_changed = Signal(object)  # TrackerState
    tracking_started = Signal()
    tracking_stopped = Signal()

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
            self._timer = QTimer()
            self._timer.setInterval(self._poll_interval_ms)
            self._timer.timeout.connect(self._on_tick)
        if self._tracker.is_tracking and not self._timer.isActive():
            self._timer.start()

    @Slot()
    def start_tracking(self) -> None:
        try:
            if self._timer is not None and self._timer.isActive() and self._tracker.is_tracking:
                logger.debug("TrackerWorker: tracking timer is already active, ignoring duplicate start")
                return
            if self._timer is None:
                self.setup()
            self._tracker.start()
            if self._timer is not None and not self._timer.isActive():
                self._timer.start()
            logger.info("TrackerWorker: tracking started")
            self.tracking_started.emit()
            # Immediately execute an initial poll so the GUI receives active state instantly
            self._on_tick()
        except Exception:  # noqa: BLE001
            logger.exception("TrackerWorker failed to start tracking")

    @Slot()
    def stop_tracking(self) -> None:
        try:
            if not self._tracker.is_tracking and (self._timer is None or not self._timer.isActive()):
                logger.debug("TrackerWorker: tracking is already stopped, ignoring duplicate stop")
                return
            if self._timer is not None:
                self._timer.stop()
            self._tracker.stop()
            logger.info("TrackerWorker: tracking stopped")
            self.tracking_stopped.emit()
            self.state_changed.emit(self._tracker.poll())
        except Exception:  # noqa: BLE001
            logger.exception("TrackerWorker failed to stop tracking cleanly")

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
        state: TrackerState = self._tracker.poll()
        self.state_changed.emit(state)


def build_tracker_thread(tracker: ActivityTracker) -> tuple[QThread, TrackerWorker]:
    """Construct a QThread + TrackerWorker pair, wired together correctly.

    The caller owns the returned objects and is responsible for calling
    ``thread.start()`` and, on shutdown, ``thread.quit()`` / ``thread.wait()``.
    """
    thread = QThread()
    worker = TrackerWorker(tracker)
    worker.moveToThread(thread)
    thread.started.connect(worker.setup)
    return thread, worker
