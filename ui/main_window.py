"""Main application window.

Wires together the dashboard, settings page, background tracker thread, and
system tray into a single cohesive window, and implements the "what would
you like to do?" close-behavior described in the spec.
"""

from __future__ import annotations

from PySide6.QtCore import QMetaObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config.settings import APP_NAME
from database.database import get_session
from platform_support import create_activity_provider
from services.activity_service import ActivityService
from services.settings_service import AppSettings, SettingsService
from system.tray import TrayController
from tracker.activity_tracker import ActivityTracker, TrackerState
from tracker.tracker_worker import TrackerWorker, build_tracker_thread
from ui.dashboard import DashboardPage
from ui.settings import SettingsPage
from utils.logger import get_logger

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """
    Threading note:
        ``TrackerWorker`` (and its internal ``QTimer``) lives on a separate
        ``QThread``. Qt requires that a ``QObject`` only be manipulated from
        the thread that owns it, so the GUI thread must never call
        ``self._worker.start_tracking()`` etc. directly - it must go
        through a signal/slot connection instead, which Qt automatically
        delivers via a thread-safe queued connection when the sender and
        receiver live on different threads. The ``_request_*`` signals
        below exist for exactly this reason.
    """

    _request_start = Signal()
    _request_stop = Signal()
    _request_apply_settings = Signal(float, bool)

    def __init__(self, login_window=None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 700)

        self._login_window = login_window
        self._activity_service = ActivityService(get_session)
        self._settings_service = SettingsService(get_session)

        self._really_quit = False

        self._build_ui()
        self._build_tracker()
        self._build_tray()

        initial_settings = self._settings_service.get_settings()
        if initial_settings.tracking_enabled:
            self.start_tracking()

    # -- UI construction --------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("HeaderBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        title_label = QLabel(APP_NAME)
        title_label.setObjectName("AppTitle")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        from services.session_service import SessionService
        session = SessionService().current_user
        display_name = session.full_name if (session and session.full_name) else "User"

        self.user_label = QLabel(f"Welcome, {display_name}")
        self.user_label.setStyleSheet("font-weight: 600; color: #5f6368; margin-right: 10px;")
        header_layout.addWidget(self.user_label)

        self.status_badge = QLabel("Not Tracking")
        self.status_badge.setObjectName("StatusBadge")
        self.status_badge.setProperty("tracking", "false")
        header_layout.addWidget(self.status_badge)

        self.start_button = QPushButton("Start Tracking")
        self.start_button.clicked.connect(self.start_tracking)
        header_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Tracking")
        self.stop_button.setObjectName("StopButton")
        self.stop_button.clicked.connect(self.stop_tracking)
        self.stop_button.setEnabled(False)
        header_layout.addWidget(self.stop_button)

        self.logout_button = QPushButton("Logout")
        self.logout_button.setObjectName("SecondaryButton")
        self.logout_button.clicked.connect(self.logout)
        header_layout.addWidget(self.logout_button)

        root.addWidget(header)

        self.tabs = QTabWidget()
        self.dashboard_page = DashboardPage(self._activity_service)
        self.settings_page = SettingsPage(self._settings_service)
        self.settings_page.settings_changed.connect(self._on_settings_changed)

        self.tabs.addTab(self.dashboard_page, "Dashboard")
        self.tabs.addTab(self.settings_page, "Settings")
        root.addWidget(self.tabs)

        self.setCentralWidget(central)
        self.dashboard_page.refresh()

    def _build_tracker(self) -> None:
        try:
            provider = create_activity_provider()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to create platform activity provider")
            QMessageBox.critical(
                self,
                APP_NAME,
                "This version of Activity Tracker supports Windows and macOS.",
            )
            provider = None

        settings = self._settings_service.get_settings()

        self._tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=settings.idle_threshold,
            track_window_titles=settings.track_window_titles,
        )
        self._thread, self._worker = build_tracker_thread(self._tracker)
        self._worker.state_changed.connect(self._on_tracker_state_changed)
        self._worker.tracking_started.connect(self._on_tracking_started)
        self._worker.tracking_stopped.connect(self._on_tracking_stopped)

        # Cross-thread control: these connections are automatically queued
        # by Qt because the worker lives on a different thread, so it's
        # safe for GUI-thread code to just emit the signals below.
        self._request_start.connect(self._worker.start_tracking)
        self._request_stop.connect(self._worker.stop_tracking)
        self._request_apply_settings.connect(self._worker.apply_settings)

        self._thread.start()

    def _build_tray(self) -> None:
        self.tray = TrayController(
            parent=self,
            on_show_dashboard=self._show_and_raise,
            on_start_tracking=self.start_tracking,
            on_stop_tracking=self.stop_tracking,
            on_show_today_activity=self._show_today_activity,
            on_show_settings=self._show_settings,
            on_exit=self._exit_application,
        )
        self.tray.show()

    # -- tracking control --------------------------------------------------------

    @Slot()
    def start_tracking(self) -> None:
        self._request_start.emit()

    @Slot()
    def stop_tracking(self) -> None:
        self._request_stop.emit()

    @Slot()
    def _on_tracking_started(self) -> None:
        self.status_badge.setText("Tracking")
        self.status_badge.setProperty("tracking", "true")
        self._refresh_badge_style()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.tray.set_tracking_state(True)

    @Slot()
    def _on_tracking_stopped(self) -> None:
        self.status_badge.setText("Not Tracking")
        self.status_badge.setProperty("tracking", "false")
        self._refresh_badge_style()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.tray.set_tracking_state(False)
        self.dashboard_page.refresh()

    @Slot(object)
    def _on_tracker_state_changed(self, state: TrackerState) -> None:
        self.dashboard_page.update_tracker_state(state)
        if state.is_idle:
            self.status_badge.setText("Idle")
            self.status_badge.setProperty("tracking", "idle")
            self._refresh_badge_style()
        elif state.is_tracking:
            self.status_badge.setText("Tracking")
            self.status_badge.setProperty("tracking", "true")
            self._refresh_badge_style()
        # Periodically refresh dashboard aggregates too (cheap SQLite reads).
        self.dashboard_page.refresh()

    def _refresh_badge_style(self) -> None:
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

    @Slot(object)
    def _on_settings_changed(self, settings: AppSettings) -> None:
        self._request_apply_settings.emit(float(settings.idle_threshold), settings.track_window_titles)

    @Slot()
    def logout(self) -> None:
        logger.info("Logging out user")
        self.stop_tracking()
        self._shutdown()

        from services.session_service import SessionService
        SessionService().logout()

        self.hide()
        if hasattr(self, "tray") and self.tray.tray_icon:
            self.tray.tray_icon.hide()

        if self._login_window:
            self._login_window.show_and_clear()
        else:
            from ui.login_window import LoginWindow
            self._login_window = LoginWindow()
            self._login_window.show()

    # -- tray actions -----------------------------------------------------------

    def _show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_today_activity(self) -> None:
        self._show_and_raise()
        self.tabs.setCurrentWidget(self.dashboard_page)
        self.dashboard_page.refresh()

    def _show_settings(self) -> None:
        self._show_and_raise()
        self.tabs.setCurrentWidget(self.settings_page)

    def _exit_application(self) -> None:
        self._really_quit = True
        self.close()

    # -- shutdown -----------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._really_quit:
            self._shutdown()
            event.accept()
            return

        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText("What would you like to do?")
        stop_btn = box.addButton("Stop Tracking", QMessageBox.ButtonRole.DestructiveRole)
        continue_btn = box.addButton("Continue Tracking in Background", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(continue_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked == stop_btn:
            self.stop_tracking()
            self._shutdown()
            event.accept()
        elif clicked == continue_btn:
            event.ignore()
            self.hide()
            self.tray.show_message(APP_NAME, "Still tracking in the background.")
        else:
            event.ignore()

    def _shutdown(self) -> None:
        logger.info("Shutting down application")
        try:
            # Unlike start_tracking()/stop_tracking() above (fire-and-forget
            # signals), shutdown needs stop_tracking() to have *finished*
            # (session closed, duration saved) before we tear the worker
            # thread down - so this one blocking queued call is intentional.
            QMetaObject.invokeMethod(
                self._worker,
                "stop_tracking",
                Qt.ConnectionType.BlockingQueuedConnection,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Error stopping tracker during shutdown")
        self._thread.quit()
        self._thread.wait(3000)
