"""Main application window."""

from __future__ import annotations

import getpass
import platform

from PySide6.QtCore import QMetaObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
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
from tracker.tracker_worker import build_tracker_thread
from services.sync_service import SyncService
from ui.dashboard import DashboardPage
from ui.settings import SettingsPage
from utils.logger import get_logger


logger = get_logger(__name__)


# ==============================================================
# USER / DEVICE INFORMATION
# ==============================================================


def get_mac_user_info() -> tuple[str, str]:
    """
    Get macOS user's full name and best-effort email.

    Name:
        NSFullUserName()

    Email:
        macOS Contacts "Me" card.

    No email is hardcoded.
    """

    name = ""
    email = ""

    # ----------------------------------------------------------
    # Get macOS username + full name
    # ----------------------------------------------------------

    try:
        from Foundation import (
            NSFullUserName,
            NSUserName,
        )

        username = str(
            NSUserName() or ""
        ).strip()

        full_name = str(
            NSFullUserName() or ""
        ).strip()

        name = full_name or username

        logger.info(
            "macOS username: %s",
            username,
        )

        logger.info(
            "macOS full name: %s",
            name,
        )

    except Exception:
        logger.exception(
            "Unable to read macOS user name"
        )

    # ----------------------------------------------------------
    # Get email from macOS Contacts "Me" card
    # ----------------------------------------------------------

    try:
        from Contacts import (
            CNContactEmailAddressesKey,
            CNContactStore,
        )

        store = (
            CNContactStore.alloc().init()
        )

        contact, error = (
            store.unifiedMeContactWithKeysToFetch_error_(
                [
                    CNContactEmailAddressesKey,
                ],
                None,
            )
        )

        if error:
            logger.warning(
                "Contacts lookup returned error: %s",
                error,
            )

        if contact:
            email_addresses = (
                contact.emailAddresses()
            )

            if email_addresses:
                for address in email_addresses:
                    value = str(
                        address.value() or ""
                    ).strip()

                    if value:
                        email = value
                        break

    except Exception:
        logger.exception(
            "Unable to read email from macOS Contacts"
        )
    

    # ----------------------------------------------------------
    # Console diagnostics
    # ----------------------------------------------------------

    print(
        "================================"
    )

    print(
        "DETECTED MAC USER INFORMATION"
    )

    print(
        "================================"
    )

    print(
        f"Name  : {name or 'Not available'}"
    )

    print(
        f"Email : {email or 'Not available'}"
    )

    print(
        "================================"
    )

    logger.info(
        "Detected name: %s",
        name or "Not available",
    )

    logger.info(
        "Detected email: %s",
        email or "Not available",
    )

    return name, email


def get_user_device_info() -> dict[str, str]:
    """
    Collect user/device information.

    This function is cross-platform.

    Returns:
        Dictionary containing:
        name
        email
        username
        device
        platform
        os_version
    """

    username = (
        getpass.getuser()
        or "Not available"
    )

    device_name = (
        platform.node()
        or "Not available"
    )

    platform_name = (
        platform.system()
        or "Not available"
    )

    os_version = (
        platform.platform()
        or "Not available"
    )

    name = ""
    email = ""

    # ----------------------------------------------------------
    # macOS
    # ----------------------------------------------------------

    if platform_name == "Darwin":
        name, email = (
            get_mac_user_info()
        )

    # ----------------------------------------------------------
    # Windows
    # ----------------------------------------------------------

    elif platform_name == "Windows":

        # Windows username is available through getpass.
        username = (
            getpass.getuser()
            or "Not available"
        )

        # Try Windows API for full display name.
        try:
            import ctypes

            GetUserNameEx = (
                ctypes.windll.secur32.GetUserNameExW
            )

            NameDisplay = 3

            size = ctypes.c_ulong(0)

            GetUserNameEx(
                NameDisplay,
                None,
                ctypes.byref(size),
            )

            if size.value > 0:
                buffer = ctypes.create_unicode_buffer(
                    size.value
                )

                if GetUserNameEx(
                    NameDisplay,
                    buffer,
                    ctypes.byref(size),
                ):
                    name = buffer.value.strip()

        except Exception:
            logger.exception(
                "Unable to read Windows display name"
            )

        if not name:
            name = username

        # Windows does not provide a universal
        # local-account email.
        email = ""

    # ----------------------------------------------------------
    # Other platform
    # ----------------------------------------------------------

    else:
        name = username
        email = ""

    return {
        "name": name or "Not available",
        "email": email or "Not available",
        "username": username,
        "device": device_name,
        "platform": platform_name,
        "os_version": os_version,
    }


# ==============================================================
# USER / DEVICE DIALOG
# ==============================================================


class UserDeviceDialog(QDialog):
    """Dialog showing user and device information."""

    def __init__(
        self,
        information: dict[str, str],
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle(
            "User & Device Information"
        )

        self.setMinimumWidth(
            480
        )

        # ------------------------------------------------------
        # Main layout
        # ------------------------------------------------------

        root = QVBoxLayout(
            self
        )

        root.setContentsMargins(
            20,
            20,
            20,
            20,
        )

        root.setSpacing(
            18
        )

        # ------------------------------------------------------
        # Title
        # ------------------------------------------------------

        title = QLabel(
            "User & Device Information"
        )

        title.setObjectName(
            "DialogTitle"
        )

        root.addWidget(
            title
        )

        # ------------------------------------------------------
        # Form
        # ------------------------------------------------------

        form = QFormLayout()

        form.setHorizontalSpacing(
            25
        )

        form.setVerticalSpacing(
            12
        )

        form.addRow(
            "Name:",
            QLabel(
                information["name"]
            ),
        )

        form.addRow(
            "Email:",
            QLabel(
                information["email"]
            ),
        )

        form.addRow(
            "Username:",
            QLabel(
                information["username"]
            ),
        )

        form.addRow(
            "Device:",
            QLabel(
                information["device"]
            ),
        )

        form.addRow(
            "Platform:",
            QLabel(
                information["platform"]
            ),
        )

        form.addRow(
            "OS Version:",
            QLabel(
                information["os_version"]
            ),
        )

        root.addLayout(
            form
        )

        # ------------------------------------------------------
        # Close button
        # ------------------------------------------------------

        buttons = QHBoxLayout()

        buttons.addStretch()

        close_button = QPushButton(
            "Close"
        )

        close_button.clicked.connect(
            self.accept
        )

        buttons.addWidget(
            close_button
        )

        root.addLayout(
            buttons
        )


# ==============================================================
# MAIN WINDOW
# ==============================================================


class MainWindow(QMainWindow):
    """Main Activity Tracker window."""

    _request_start = Signal()
    _request_stop = Signal()
    _request_apply_settings = Signal(
        float,
        bool,
        str,
        int,
        bool,
    )

    def __init__(self, login_window=None) -> None:
        super().__init__()

        self._login_window = login_window
        self._activity_service = ActivityService(get_session)
        self._settings_service = SettingsService(get_session)

        self._really_quit = False

        # ------------------------------------------------------
        # Build UI
        # ------------------------------------------------------

        self._build_ui()

        self._build_tracker()

        self._build_tray()

        # Initial UI state: tracking is stopped until the worker
        # confirms that tracking has actually started.
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        # ------------------------------------------------------
        # Initial settings
        # ------------------------------------------------------

        initial_settings = (
            self._settings_service.get_settings()
        )

        if initial_settings.tracking_enabled:
            self.start_tracking()

    # ==========================================================
    # BUILD UI
    # ==========================================================

    def _build_ui(self) -> None:
        """Build main application interface."""

        central = QWidget()

        root = QVBoxLayout(
            central
        )

        root.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        root.setSpacing(
            0
        )

        # ======================================================
        # HEADER
        # ======================================================

        header = QWidget()

        header.setObjectName(
            "HeaderBar"
        )

        header_layout = QHBoxLayout(
            header
        )

        header_layout.setContentsMargins(
            16,
            12,
            16,
            12,
        )

        header_layout.setSpacing(
            10
        )

        # ------------------------------------------------------
        # App title
        # ------------------------------------------------------

        title_label = QLabel(
            APP_NAME
        )

        title_label.setObjectName(
            "AppTitle"
        )

        header_layout.addWidget(
            title_label
        )

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

        # ------------------------------------------------------
        # Tracking controls
        # ------------------------------------------------------

        self.start_button = QPushButton("Start Tracking")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self.start_tracking)
        header_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Tracking")
        self.stop_button.setObjectName("SecondaryButton")
        self.stop_button.clicked.connect(self.stop_tracking)
        self.stop_button.setEnabled(False)
        header_layout.addWidget(self.stop_button)

        self.user_button = QPushButton(
            "User / Device"
        )

        self.user_button.setObjectName(
            "SecondaryButton"
        )
        self.user_button.clicked.connect(
            self._show_user_device_info
        )
        header_layout.addWidget(self.user_button)

        self.logout_button = QPushButton("Logout")
        self.logout_button.setObjectName("SecondaryButton")
        self.logout_button.clicked.connect(self.logout)
        header_layout.addWidget(self.logout_button)

        root.addWidget(header)

        self.tabs = QTabWidget()

        self.dashboard_page = (
            DashboardPage(
                self._activity_service
            )
        )

        self.settings_page = (
            SettingsPage(
                self._settings_service
            )
        )

        self.settings_page.settings_changed.connect(
            self._on_settings_changed
        )

        self.tabs.addTab(
            self.dashboard_page,
            "Dashboard",
        )

        self.tabs.addTab(
            self.settings_page,
            "Settings",
        )

        self.tabs.currentChanged.connect(self._on_tab_changed)

        root.addWidget(
            self.tabs
        )

        self.setCentralWidget(
            central
        )

        self.dashboard_page.refresh()

    # ==========================================================
    # USER / DEVICE
    # ==========================================================

    def _show_user_device_info(
        self,
    ) -> None:
        """Detect and display current user/device information."""

        information = (
            get_user_device_info()
        )

        # ------------------------------------------------------
        # Console output
        # ------------------------------------------------------

        print(
            "================================"
        )

        print(
            "USER / DEVICE INFORMATION"
        )

        print(
            "================================"
        )

        print(
            f"Name      : {information['name']}"
        )

        print(
            f"Email     : {information['email']}"
        )

        print(
            f"Username  : {information['username']}"
        )

        print(
            f"Device    : {information['device']}"
        )

        print(
            f"Platform  : {information['platform']}"
        )

        print(
            f"OS Version: {information['os_version']}"
        )

        print(
            "================================"
        )

        # ------------------------------------------------------
        # Dialog
        # ------------------------------------------------------

        dialog = UserDeviceDialog(
            information=information,
            parent=self,
        )

        dialog.exec()

    # ==========================================================
    # TRACKER
    # ==========================================================

    def _build_tracker(self) -> None:
        """Create the platform activity provider and worker."""

        try:
            provider = (
                create_activity_provider()
            )

        except Exception:
            logger.exception(
                "Failed to create platform activity provider"
            )

            QMessageBox.critical(
                self,
                APP_NAME,
                "This version of Activity Tracker "
                "supports Windows and macOS.",
            )

            provider = None

        settings = (
            self._settings_service.get_settings()
        )

        self._tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=(
                settings.idle_threshold
            ),
            track_window_titles=(
                settings.track_window_titles
            ),
            sync_service=SyncService(),
            screenshot_interval_type=settings.screenshot_interval_type,
            screenshot_custom_interval_seconds=settings.screenshot_custom_interval,
            capture_on_switch=settings.capture_on_switch,
        )

        (
            self._thread,
            self._worker,
        ) = build_tracker_thread(
            self._tracker
        )

        self._worker.state_changed.connect(
            self._on_tracker_state_changed
        )

        self._worker.tracking_started.connect(
            self._on_tracking_started
        )

        self._worker.tracking_stopped.connect(
            self._on_tracking_stopped
        )

        self._request_start.connect(
            self._worker.start_tracking
        )

        self._request_stop.connect(
            self._worker.stop_tracking
        )

        self._request_apply_settings.connect(
            self._worker.apply_settings
        )

        self._thread.start()

    # ==========================================================
    # TRAY
    # ==========================================================

    def _build_tray(self) -> None:
        """Create system tray controller."""

        self.tray = TrayController(
            parent=self,
            on_show_dashboard=self._show_and_raise,
            on_start_tracking=self.start_tracking,
            on_stop_tracking=self.stop_tracking,
            on_show_today_activity=(
                self._show_today_activity
            ),
            on_show_settings=(
                self._show_settings
            ),
            on_exit=self._exit_application,
        )

        self.tray.show()

    # ==========================================================
    # TRACKING CONTROL
    # ==========================================================

    @Slot()
    def start_tracking(
        self,
    ) -> None:
        """Start tracking."""

        self._request_start.emit()

    @Slot()
    def stop_tracking(
        self,
    ) -> None:
        """Stop tracking."""

        self._request_stop.emit()

    @Slot()
    def _on_tracking_started(
        self,
    ) -> None:
        """Update UI after tracking starts."""

        self.status_badge.setText(
            "Tracking"
        )

        self.status_badge.setProperty(
            "tracking",
            "true",
        )

        self._refresh_badge_style()

        self.start_button.setEnabled(
            False
        )

        self.stop_button.setEnabled(
            True
        )

        self.tray.set_tracking_state(
            True
        )
        self.settings_page.update_capture_status(True)

    @Slot()
    def _on_tracking_stopped(
        self,
    ) -> None:
        """Update UI after tracking stops."""

        self.status_badge.setText(
            "Not Tracking"
        )

        self.status_badge.setProperty(
            "tracking",
            "false",
        )

        self._refresh_badge_style()

        self.start_button.setEnabled(
            True
        )

        self.stop_button.setEnabled(
            False
        )

        self.tray.set_tracking_state(
            False
        )
        self.settings_page.update_capture_status(False)

        self.dashboard_page.refresh()

    @Slot(object)
    def _on_tracker_state_changed(
        self,
        state: TrackerState,
    ) -> None:
        """Update dashboard from tracker state."""

        self.dashboard_page.update_tracker_state(
            state
        )

        if state.is_idle:
            self.status_badge.setText(
                "Idle"
            )

            self.status_badge.setProperty(
                "tracking",
                "idle",
            )

            self._refresh_badge_style()

        elif state.is_tracking:
            self.status_badge.setText(
                "Tracking"
            )

            self.status_badge.setProperty(
                "tracking",
                "true",
            )

            self._refresh_badge_style()

        self.dashboard_page.refresh()

    # ==========================================================
    # SETTINGS
    # ==========================================================

    def _refresh_badge_style(
        self,
    ) -> None:
        """Refresh tracking status styling."""

        self.status_badge.style().unpolish(
            self.status_badge
        )

        self.status_badge.style().polish(
            self.status_badge
        )

    @Slot(object)
    def _on_settings_changed(
        self,
        settings: AppSettings,
    ) -> None:
        """Apply changed settings to tracker."""

        self._request_apply_settings.emit(
            float(settings.idle_threshold),
            bool(settings.track_window_titles),
            str(settings.screenshot_interval_type),
            int(settings.screenshot_custom_interval),
            bool(settings.capture_on_switch),
        )

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        if index == 1:  # Settings tab
            self.settings_page.reload()
            if hasattr(self, "_tracker") and self._tracker:
                self.settings_page.update_capture_status(self._tracker.is_tracking)

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

        self.showNormal()

        self.raise_()

        self.activateWindow()

    def _show_and_raise(self) -> None:
        """Show the main window and bring it to the foreground."""

        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _show_today_activity(
        self,
    ) -> None:
        """Show today's activity."""

        self._show_and_raise()

        self.tabs.setCurrentWidget(
            self.dashboard_page
        )

        self.dashboard_page.refresh()

    def _show_settings(
        self,
    ) -> None:
        """Open settings."""

        self._show_and_raise()

        self.tabs.setCurrentWidget(
            self.settings_page
        )

    def _exit_application(
        self,
    ) -> None:
        """Exit application."""

        self._really_quit = True

        self.close()

    # ==========================================================
    # SHUTDOWN
    # ==========================================================

    def closeEvent(
        self,
        event,
    ) -> None:  # noqa: N802
        """Handle application close."""

        if self._really_quit:
            self._shutdown()

            event.accept()

            return

        box = QMessageBox(
            self
        )

        box.setWindowTitle(
            APP_NAME
        )

        box.setText(
            "What would you like to do?"
        )

        stop_btn = box.addButton(
            "Stop Tracking",
            QMessageBox.ButtonRole.DestructiveRole,
        )

        continue_btn = box.addButton(
            "Continue Tracking in Background",
            QMessageBox.ButtonRole.AcceptRole,
        )

        cancel_btn = box.addButton(
            "Cancel",
            QMessageBox.ButtonRole.RejectRole,
        )

        box.setDefaultButton(
            continue_btn
        )

        box.exec()

        clicked = (
            box.clickedButton()
        )

        # ------------------------------------------------------
        # Stop and exit
        # ------------------------------------------------------

        if clicked == stop_btn:
            self.stop_tracking()

            self._shutdown()

            event.accept()

        # ------------------------------------------------------
        # Continue in background
        # ------------------------------------------------------

        elif clicked == continue_btn:
            event.ignore()

            self.hide()

            self.tray.show_message(
                APP_NAME,
                "Still tracking in the background.",
            )

        # ------------------------------------------------------
        # Cancel
        # ------------------------------------------------------

        elif clicked == cancel_btn:
            event.ignore()

    def _shutdown(
        self,
    ) -> None:
        """Stop tracker and cleanly shut down."""

        logger.info(
            "Shutting down application"
        )

        try:
            QMetaObject.invokeMethod(
                self._worker,
                "stop_tracking",
                Qt.ConnectionType.BlockingQueuedConnection,
            )

        except Exception:
            logger.exception(
                "Error stopping tracker during shutdown"
            )

        self._thread.quit()

        self._thread.wait(
            3000
        )
        