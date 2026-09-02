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
from ui.weekly_timeline import WeeklyTimelinePage
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

        # Set window icon explicitly
        from PySide6.QtGui import QIcon
        import os
        import sys
        if getattr(sys, "frozen", False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, "assets", "ihrms-logo-icon.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

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

        # Apply RBAC permissions on UI controls first
        self._apply_rbac_permissions()

        # Ensure startup registration matches settings
        initial_settings = self._settings_service.get_settings()
        from system import startup
        if initial_settings.start_with_system:
            startup.set_enabled(True)

        # Start tracking automatically if permitted by RBAC
        from services.session_service import SessionService
        session = SessionService().current_user
        if session and session.tracking_permitted:
            logger.info("Auto-starting tracking on login based on RBAC permissions.")
            self.start_tracking()
        else:
            logger.info("Auto-starting tracking skipped due to RBAC permissions.")

        # Update system state
        self._update_dialog = None
        self._latest_installer_path: str | None = None
        self._latest_version: str | None = None
        self._is_force_update: bool = False

        # Trigger background automatic update check shortly after startup
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self._check_for_updates)

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

        # Tracking status icon next to status badge
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(24, 24)
        self.status_icon.setStyleSheet("margin-right: 4px; background: transparent;")
        header_layout.addWidget(self.status_icon)

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

        self.update_button = QPushButton("🚀 Update Available")
        self.update_button.setObjectName("PrimaryButton")
        self.update_button.setVisible(False)
        self.update_button.setStyleSheet(
            "background-color: #1a73e8; color: #ffffff; font-weight: 600; "
            "border-radius: 4px; padding: 5px 12px; margin-right: 6px;"
        )
        self.update_button.clicked.connect(self._on_update_button_clicked)
        header_layout.addWidget(self.update_button)

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

        self.weekly_page = (
            WeeklyTimelinePage(
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

        self.dashboard_page.weekly_timeline_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.weekly_page)
        )
        self.weekly_page.back_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.dashboard_page)
        )

        self.tabs.addTab(
            self.dashboard_page,
            "Dashboard",
        )

        self.tabs.addTab(
            self.weekly_page,
            "Weekly Timeline",
        )

        # self.tabs.addTab(
        #     self.settings_page,
        #     "Settings",
        # )

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
                "This version of iHRMS Monitor "
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
            on_check_updates=lambda: self._check_for_updates(manual=True),
        )

        self.tray.show()

    def _apply_rbac_permissions(self) -> None:
        """Enforce RBAC permissions on Start/Stop tracking buttons and tray menu."""
        from services.session_service import SessionService
        session = SessionService().current_user

        # Unconditionally hide "Stop Tracking" button and tray menu stop action per request
        self.stop_button.hide()
        if hasattr(self, "tray") and self.tray:
            self.tray.stop_action.setVisible(False)

        if session and not session.tracking_permitted:
            logger.info("Enforcing RBAC tracking restrictions: hiding start/stop tracking controls")
            self.start_button.hide()
            if hasattr(self, "status_icon") and self.status_icon:
                self.status_icon.hide()
            self.status_badge.hide()
            if hasattr(self, "tray") and self.tray:
                self.tray.start_action.setVisible(False)
        else:
            self.start_button.show()
            if hasattr(self, "status_icon") and self.status_icon:
                self.status_icon.show()
            self.status_badge.show()
            if hasattr(self, "tray") and self.tray:
                self.tray.start_action.setVisible(True)

    def _update_status_icon(self) -> None:
        """Update the Shield+Pulse icon based on the current tracking/idle state."""
        if not hasattr(self, "status_icon") or not self.status_icon:
            return
            
        from services.session_service import SessionService
        session = SessionService().current_user
        if session and not session.tracking_permitted:
            self.status_icon.hide()
            return

        is_active = False
        is_idle = False
        
        # Check current state from status badge property
        tracking_prop = self.status_badge.property("tracking")
        if tracking_prop == "true":
            is_active = True
        elif tracking_prop == "idle":
            is_active = True
            is_idle = True
            
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
        from PySide6.QtCore import Qt
        
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Set color based on state
        if is_active:
            if is_idle:
                color = QColor("#b06000") # Idle (amber)
            else:
                color = QColor("#137333") # Active (green)
        else:
            color = QColor("#a50e0e") # Inactive (red)
            
        # Draw Shield Path
        path = QPainterPath()
        path.moveTo(4, 5)
        path.quadTo(12, 3, 20, 5)
        path.quadTo(20, 14, 12, 21)
        path.quadTo(4, 14, 4, 5)
        
        painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        
        # Draw Pulse/Activity Line inside the shield
        pulse_path = QPainterPath()
        pulse_path.moveTo(7, 12)
        pulse_path.lineTo(9, 12)
        pulse_path.lineTo(11, 8)
        pulse_path.lineTo(13, 16)
        pulse_path.lineTo(15, 12)
        pulse_path.lineTo(17, 12)
        
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(pulse_path)
        
        painter.end()
        
        self.status_icon.setPixmap(pixmap)
        self.status_icon.show()

    # ==========================================================
    # TRACKING CONTROL
    # ==========================================================

    @Slot()
    def start_tracking(
        self,
    ) -> None:
        """Start tracking."""
        from services.session_service import SessionService
        session = SessionService().current_user
        if session and not session.tracking_permitted:
            logger.warning("Start tracking requested but blocked by RBAC permissions.")
            return

        # Update UI state immediately to show Active
        self.status_badge.setText("Tracking")
        self.status_badge.setProperty("tracking", "true")
        self._refresh_badge_style()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        if hasattr(self, "tray") and self.tray:
            self.tray.set_tracking_state(True)
        if hasattr(self, "settings_page") and self.settings_page:
            self.settings_page.update_capture_status(True)

        self._request_start.emit()

    @Slot()
    def stop_tracking(
        self,
    ) -> None:
        """Stop tracking."""
        # Update UI state immediately to show Inactive
        self.status_badge.setText("Not Tracking")
        self.status_badge.setProperty("tracking", "false")
        self._refresh_badge_style()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if hasattr(self, "tray") and self.tray:
            self.tray.set_tracking_state(False)
        if hasattr(self, "settings_page") and self.settings_page:
            self.settings_page.update_capture_status(False)

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
        self._apply_rbac_permissions()

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
        self._apply_rbac_permissions()

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
        if hasattr(self, "weekly_page") and self.weekly_page.isVisible():
            self.weekly_page.refresh()
        self._apply_rbac_permissions()

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

        self._update_status_icon()

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
        current_widget = self.tabs.currentWidget()
        if hasattr(self, "weekly_page") and current_widget == self.weekly_page:
            self.weekly_page.refresh()
        elif hasattr(self, "dashboard_page") and current_widget == self.dashboard_page:
            self.dashboard_page.refresh()
        elif hasattr(self, "settings_page") and current_widget == self.settings_page:
            self.settings_page.reload()
            if hasattr(self, "_tracker") and self._tracker:
                self.settings_page.update_capture_status(self._tracker.is_tracking)

    @Slot()
    def logout(self) -> None:
        logger.info("Logging out user")
        self.stop_tracking()
        self._shutdown()

        # Flush pending activities and screenshots for this user before clearing session
        try:
            from services.sync_service import SyncService
            logger.info("Flushing pending activity and screenshots for user before logout...")
            SyncService().sync_activity_now()
        except Exception as flush_err:
            logger.warning("Could not flush sync on logout: %s", flush_err)

        from services.session_service import SessionService
        SessionService().logout()

        # Clear saved session for auto-login
        try:
            from services.secure_session import SessionStore
            SessionStore().clear_session()
        except Exception:
            logger.warning("Failed to clear saved session", exc_info=True)

        self.hide()
        if hasattr(self, "tray") and self.tray.tray_icon:
            self.tray.tray_icon.hide()

        if self._login_window:
            self._login_window.main_window = None
            self._login_window.show_and_clear()
        else:
            from ui.login_window import LoginWindow
            self._login_window = LoginWindow()
            self._login_window.show()

    # -- tray actions -----------------------------------------------------------

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
        """Handle application close by hiding to tray instead of quitting."""

        if self._really_quit:
            self._shutdown()
            event.accept()
            return

        event.ignore()
        self.hide()
        if hasattr(self, "tray") and self.tray:
            self.tray.show_message(
                APP_NAME,
                "Still tracking in the background.",
            )

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

    # ==========================================================
    # AUTOMATIC UPDATES
    # ==========================================================

    def _check_for_updates(self, manual: bool = False) -> None:
        """Trigger background version check from update API."""
        try:
            from config.api_config import ApiConfig
            from services.session_service import SessionService
            from services.update_service import UpdateService

            api_config = ApiConfig()
            api_url = api_config.api_url
            session = SessionService().current_user
            indo_code = session.indo_code if session else None
            api_key = session.api_key if session else None

            def on_available(version: str, download_url: str, force: bool):
                logger.info("Update available: v%s (force=%s)", version, force)
                self._latest_version = version
                self._is_force_update = force
                self.update_button.setVisible(True)
                self.update_button.setText(f"🚀 Update v{version}")
                if hasattr(self, "tray") and self.tray:
                    self.tray.show_message(
                        "iHRMS Monitor Update",
                        f"A new version (v{version}) is downloading in the background.",
                    )
                if manual:
                    self._show_update_dialog(version, force, None)

            def on_progress(percent: int, downloaded: int, total: int):
                if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
                    self._update_dialog.update_progress(percent, downloaded, total)

            def on_completed(installer_path: str, version: str, force: bool):
                logger.info("Update installer downloaded: %s", installer_path)
                self._latest_installer_path = installer_path
                self._latest_version = version
                self._is_force_update = force

                self.update_button.setVisible(True)
                self.update_button.setText(f"Restart & Install v{version}")
                self.update_button.setStyleSheet(
                    "background-color: #0f9d58; color: #ffffff; font-weight: 700; "
                    "border-radius: 4px; padding: 5px 12px; margin-right: 6px;"
                )

                if hasattr(self, "tray") and self.tray:
                    self.tray.show_message(
                        "iHRMS Monitor Update Ready",
                        f"Version {version} is ready to install. Click to restart and update.",
                    )

                if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
                    self._update_dialog.set_download_complete(installer_path)
                elif force or manual:
                    self._show_update_dialog(version, force, installer_path)

            def on_error(err_msg: str):
                logger.warning("Update check failed: %s", err_msg)
                if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
                    self._update_dialog.set_error(err_msg)
                elif manual:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "Check for Updates", f"Could not check for updates:\n{err_msg}")

            UpdateService().check_for_updates(
                api_url=api_url,
                indo_code=indo_code,
                api_key=api_key,
                auto_download=True,
                on_available=on_available,
                on_progress=on_progress,
                on_completed=on_completed,
                on_error=on_error,
            )

        except Exception as err:
            logger.exception("Failed to start update check: %s", err)

    def _show_update_dialog(self, version: str, is_force: bool, installer_path: str | None = None) -> None:
        """Display the update dialog."""
        from ui.update_dialog import UpdateDialog

        if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
            self._update_dialog.raise_()
            self._update_dialog.activateWindow()
            return

        self._update_dialog = UpdateDialog(
            version=version,
            is_force=is_force,
            installer_path=installer_path,
            parent=self,
        )
        self._update_dialog.show()

    def _on_update_button_clicked(self) -> None:
        """Handle header update button click."""
        version = self._latest_version or "Latest"
        self._show_update_dialog(
            version=version,
            is_force=self._is_force_update,
            installer_path=self._latest_installer_path,
        )

        