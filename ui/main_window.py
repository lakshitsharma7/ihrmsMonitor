"""Main application window."""

from __future__ import annotations

import getpass
import platform

from PySide6.QtCore import QMetaObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
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

    from config.settings import get_running_app_version
    from utils.device import get_device_identifier

    app_version = get_running_app_version()
    device_id = get_device_identifier()

    return {
        "name": name or "Not available",
        "email": email or "Not available",
        "username": username,
        "device": device_name,
        "platform": platform_name,
        "os_version": os_version,
        "app_version": app_version,
        "device_identifier": device_id,
    }


# ==============================================================
# USER / DEVICE DIALOG
# ==============================================================


class UserDeviceDialog(QDialog):
    """Dialog showing user, device, and fleet update verification status."""

    def __init__(
        self,
        information: dict[str, str],
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle("User, Device & Fleet Update Verification")
        self.resize(820, 560)
        self.setMinimumWidth(680)

        # ------------------------------------------------------
        # Main layout
        # ------------------------------------------------------
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # Title
        title = QLabel("Device & Fleet Update Status")
        title.setObjectName("DialogTitle")
        root.addWidget(title)

        # Tabs: Current Device | All Enrolled Laptops
        tabs = QTabWidget(self)

        # --- Tab 1: Current Laptop ---
        tab_current = QWidget()
        current_layout = QVBoxLayout(tab_current)
        current_layout.setContentsMargins(15, 15, 15, 15)
        current_layout.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(25)
        form.setVerticalSpacing(10)

        form.addRow("Name:", QLabel(information.get("name", "Not available")))
        form.addRow("Email:", QLabel(information.get("email", "Not available")))
        form.addRow("Username:", QLabel(information.get("username", "Not available")))
        form.addRow("Device / Hostname:", QLabel(information.get("device", "Not available")))
        form.addRow("Platform:", QLabel(information.get("platform", "Not available")))
        form.addRow("OS Version:", QLabel(information.get("os_version", "Not available")))
        form.addRow("Device ID:", QLabel(information.get("device_identifier", "Not available")))

        app_ver = information.get("app_version", get_running_app_version())
        ver_lbl = QLabel(f"{app_ver} (authoritative build)")
        ver_lbl.setStyleSheet("font-weight: bold; color: #3b82f6;")
        form.addRow("Installed Version:", ver_lbl)

        # Status badge for this device
        from services.device_registry_service import DeviceRegistryService
        cur_status = "Updated"
        try:
            cur_dev = None
            for d in DeviceRegistryService().get_all_devices():
                if d["device_identifier"] == information.get("device_identifier"):
                    cur_dev = d
                    break
            if cur_dev:
                cur_status = cur_dev["update_status"]
        except Exception:
            pass

        status_lbl = QLabel(cur_status)
        if cur_status == "Updated":
            status_lbl.setStyleSheet("font-weight: bold; color: #10b981;")
        elif "Pending" in cur_status:
            status_lbl.setStyleSheet("font-weight: bold; color: #f59e0b;")
        elif "Failed" in cur_status:
            status_lbl.setStyleSheet("font-weight: bold; color: #ef4444;")
        else:
            status_lbl.setStyleSheet("color: #6b7280;")
        form.addRow("Update Status:", status_lbl)

        current_layout.addLayout(form)
        current_layout.addStretch()
        tabs.addTab(tab_current, "This Laptop")

        # --- Tab 2: Enrolled Laptops Fleet Status ---
        tab_fleet = QWidget()
        fleet_layout = QVBoxLayout(tab_fleet)
        fleet_layout.setContentsMargins(15, 15, 15, 15)
        fleet_layout.setSpacing(10)

        # Summary Badges Row
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-weight: bold; font-size: 13px; padding: 8px; background: #f3f4f6; border-radius: 4px;")
        fleet_layout.addWidget(self.summary_label)

        # Table
        self.fleet_table = QTableWidget()
        self.fleet_table.setColumnCount(6)
        self.fleet_table.setHorizontalHeaderLabels([
            "Hostname / Laptop",
            "User / Emp ID",
            "Installed Version",
            "Latest Server",
            "Update Status",
            "Last Seen / Sync",
        ])
        self.fleet_table.horizontalHeader().setStretchLastSection(True)
        self.fleet_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.fleet_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.fleet_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fleet_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        fleet_layout.addWidget(self.fleet_table)

        # Refresh Fleet Button
        fleet_btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Fleet Status")
        refresh_btn.clicked.connect(self._populate_fleet_table)
        fleet_btn_row.addWidget(refresh_btn)
        fleet_btn_row.addStretch()
        fleet_layout.addLayout(fleet_btn_row)

        tabs.addTab(tab_fleet, "All Enrolled Laptops")
        root.addWidget(tabs)

        self._populate_fleet_table()

        # Close button
        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    def _populate_fleet_table(self) -> None:
        try:
            from services.device_registry_service import DeviceRegistryService
            svc = DeviceRegistryService()
            summary = svc.get_device_summary()
            self.summary_label.setText(
                f"Total Laptops: {summary['total']}  |  "
                f"Updated: {summary['updated']}  |  "
                f"Pending: {summary['pending']}  |  "
                f"Failed: {summary['failed']}  |  "
                f"Offline: {summary['offline']}"
            )

            devices = svc.get_all_devices()
            self.fleet_table.setRowCount(len(devices))

            for row, d in enumerate(devices):
                host_item = QTableWidgetItem(d.get("hostname") or "Unknown")
                emp_str = f"{d.get('username') or ''} ({d.get('employee_id') or '-'})".strip()
                emp_item = QTableWidgetItem(emp_str)
                inst_ver_item = QTableWidgetItem(d.get("installed_version") or get_running_app_version())
                latest_ver_item = QTableWidgetItem(str(d.get("latest_version") or "N/A"))

                status_text = d.get("update_status", "Unknown")
                status_item = QTableWidgetItem(status_text)
                if status_text == "Updated":
                    status_item.setForeground(Qt.GlobalColor.darkGreen)
                elif "Pending" in status_text:
                    status_item.setForeground(Qt.GlobalColor.darkYellow)
                elif "Failed" in status_text:
                    status_item.setForeground(Qt.GlobalColor.red)
                    if d.get("failure_reason"):
                        status_item.setToolTip(f"Failure Reason: {d['failure_reason']}")
                else:
                    status_item.setForeground(Qt.GlobalColor.gray)

                last_str = d.get("last_seen") or d.get("last_sync") or "Never"
                if "T" in str(last_str):
                    last_str = last_str.split(".")[0].replace("T", " ")
                last_item = QTableWidgetItem(str(last_str))

                self.fleet_table.setItem(row, 0, host_item)
                self.fleet_table.setItem(row, 1, emp_item)
                self.fleet_table.setItem(row, 2, inst_ver_item)
                self.fleet_table.setItem(row, 3, latest_ver_item)
                self.fleet_table.setItem(row, 4, status_item)
                self.fleet_table.setItem(row, 5, last_item)
        except Exception as e:
            logger.debug("Failed to populate fleet table: %s", e)


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

        self.setWindowTitle(APP_NAME)
        self.resize(1024, 720)
        self.setMinimumSize(920, 600)

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
        self._offline_update_pending: bool = False

        # Fast retry timer when offline or update is pending
        from PySide6.QtCore import QTimer
        self._offline_update_retry_timer = QTimer(self)
        self._offline_update_retry_timer.setInterval(30 * 1000)  # 30 seconds
        self._offline_update_retry_timer.timeout.connect(lambda: self._check_for_updates(manual=False))

        # Trigger background automatic update check shortly after startup
        QTimer.singleShot(2000, self._check_for_updates)

        # Also schedule recurring update checks every 2 hours for continuously open laptops
        self._periodic_update_timer = QTimer(self)
        self._periodic_update_timer.setInterval(2 * 60 * 60 * 1000)
        self._periodic_update_timer.timeout.connect(lambda: self._check_for_updates(manual=False))
        self._periodic_update_timer.start()

        # Record device heartbeat with current running app version
        try:
            from services.device_registry_service import DeviceRegistryService
            from utils.device import get_device_identifier
            DeviceRegistryService().record_heartbeat(
                employee_id=getattr(session, "employee_id", None),
                username=getattr(session, "username", None),
                device_token=getattr(session, "device_token", None),
            )
            my_status = "Updated"
            for d in DeviceRegistryService().get_all_devices():
                if d["device_identifier"] == get_device_identifier():
                    my_status = d["update_status"]
                    break
            self.dashboard_page.set_update_status(my_status)
            if my_status == "Update Pending":
                self._offline_update_pending = True
        except Exception:
            pass

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
        self.start_button.hide()

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

        from config.settings import get_running_app_version
        self.dashboard_page = (
            DashboardPage(
                self._activity_service
            )
        )
        self.dashboard_page.set_version(get_running_app_version())

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

        # Unconditionally hide "Stop Tracking" and "Start Tracking" buttons
        self.stop_button.hide()
        self.start_button.hide()
        if hasattr(self, "tray") and self.tray:
            self.tray.stop_action.setVisible(False)

        if session and not session.tracking_permitted:
            logger.info("Enforcing RBAC tracking restrictions: hiding tracking controls")
            if hasattr(self, "status_icon") and self.status_icon:
                self.status_icon.hide()
            self.status_badge.hide()
            if hasattr(self, "tray") and self.tray:
                self.tray.start_action.setVisible(False)
        else:
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

        # If an update check was pending/deferred due to offline status and sync succeeds, trigger check immediately
        if getattr(self, "_offline_update_pending", False):
            from services.sync_service import SyncService
            if SyncService.last_sync_status == "Sent":
                logger.info("Internet connection restored via sync. Auto-initiating pending update check.")
                self._offline_update_pending = False
                if getattr(self, "_offline_update_retry_timer", None) and self._offline_update_retry_timer.isActive():
                    self._offline_update_retry_timer.stop()
                self._check_for_updates(manual=False)

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
            SyncService.reset_sync_state()
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

        login_win = self._login_window
        if login_win:
            login_win.main_window = None
            login_win.show_and_clear()
        else:
            from ui.login_window import LoginWindow
            login_win = LoginWindow()
            login_win.show()

        self.close()
        self.deleteLater()

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
        """Trigger background version check from update API using unified pipeline."""
        try:
            from config.api_config import ApiConfig
            from services.session_service import SessionService
            from services.update_service import UpdateService

            api_config = ApiConfig()
            try:
                api_url = api_config.base_url
            except Exception:
                api_url = ""
            session = SessionService().current_user
            indo_code = session.indo_code if session else None
            api_key = session.api_key if session else None

            def on_phase(phase: str, desc: str):
                logger.info("Pipeline phase changed: %s (%s)", phase, desc)
                if phase == "done":
                    self._offline_update_pending = False
                    from config.settings import get_running_app_version
                    self.dashboard_page.set_version(get_running_app_version())
                    self.dashboard_page.set_update_status("Updated")
                    self.update_button.setVisible(False)
                    if getattr(self, "_offline_update_retry_timer", None) and self._offline_update_retry_timer.isActive():
                        self._offline_update_retry_timer.stop()
                elif phase == "uploading_pending":
                    self.dashboard_page.set_update_status("Syncing before update...")
                elif phase == "downloading":
                    ver_str = f" v{self._latest_version}" if self._latest_version else ""
                    self.dashboard_page.set_update_status(f"Downloading{ver_str}...")
                elif phase == "installing":
                    self.dashboard_page.set_update_status("Installing update...")

            def on_progress(pct: int, cur: int, tot: int):
                if 0 <= pct <= 100:
                    ver_str = f" v{self._latest_version}" if self._latest_version else ""
                    self.dashboard_page.set_update_status(f"Downloading{ver_str} ({pct}%)")

            def on_available(version: str, download_url: str, force: bool):
                logger.info("Pipeline update available: v%s (force=%s)", version, force)
                self._offline_update_pending = False
                self._latest_version = version
                self._is_force_update = force
                self.dashboard_page.set_update_status(f"Pending (v{version} available)")
                self.update_button.setVisible(True)
                self.update_button.setText(f"🚀 Updating v{version}...")
                if hasattr(self, "tray") and self.tray:
                    self.tray.show_message(
                        "iHRMS Monitor Update",
                        f"New version v{version} is preparing to install.",
                    )
                self._show_update_dialog(version, force, None, worker=getattr(self, "_pipeline_worker", None))

            def on_completed(installer_path: str, version: str, force: bool):
                logger.info("Pipeline update downloaded: %s", installer_path)
                self._latest_installer_path = installer_path
                self._latest_version = version
                self._is_force_update = force
                self.dashboard_page.set_update_status(f"Ready to Restart (v{version})")

                self.update_button.setVisible(True)
                self.update_button.setText(f"Restarting v{version}...")
                self.update_button.setStyleSheet(
                    "background-color: #0f9d58; color: #ffffff; font-weight: 700; "
                    "border-radius: 4px; padding: 5px 12px; margin-right: 6px;"
                )

                if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
                    self._update_dialog._on_download_completed(installer_path, version, force)

            def on_error(phase: str, err_msg: str):
                logger.warning("Pipeline update error (%s): %s", phase, err_msg)
                is_offline = any(term in err_msg.lower() for term in ("connect", "timeout", "network", "offline", "unreachable", "name resolution", "temporary failure"))
                if is_offline:
                    self._offline_update_pending = True
                    self.dashboard_page.set_update_status("Update Pending (Offline)")
                    if getattr(self, "_offline_update_retry_timer", None) and not self._offline_update_retry_timer.isActive():
                        self._offline_update_retry_timer.start(30000)
                else:
                    self.dashboard_page.set_update_status("Failed")
                    self.update_button.setText(f"Retry Update v{self._latest_version or ''}")

                # Ensure active tracking is running and unaffected by update errors
                try:
                    from services.session_service import SessionService
                    session = SessionService().current_user
                    if session and session.tracking_permitted:
                        if not self._tracker or not getattr(self._tracker, "is_tracking", False):
                            logger.info("Ensuring tracking remains active after update failure.")
                            self.start_tracking()
                except Exception as track_err:
                    logger.debug("Could not verify tracking in update on_error: %s", track_err)

                if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
                    self._update_dialog._on_error_occurred(phase, err_msg)
                elif manual:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "Check for Updates", f"Update error ({phase}):\n{err_msg}")

            def on_ready_to_install(installer_path: str):
                logger.info("Pipeline update ready to install received on Main Thread: %s", installer_path)
                self._latest_installer_path = installer_path
                self._really_quit = True
                if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
                    try:
                        self._update_dialog.close()
                    except Exception:
                        pass
                from services.update_service import install_update_and_restart
                install_update_and_restart(installer_path, exit_process=True)

            self._pipeline_worker = UpdateService().start_pipeline(
                api_url=api_url,
                indo_code=indo_code,
                api_key=api_key,
                on_phase=on_phase,
                on_progress=on_progress,
                on_available=on_available,
                on_download_completed=on_completed,
                on_ready_to_install=on_ready_to_install,
                on_error=on_error,
            )

        except Exception as err:
            logger.exception("Failed to start update pipeline: %s", err)

    def _show_update_dialog(
        self,
        version: str,
        is_force: bool,
        installer_path: str | None = None,
        worker: object | None = None,
    ) -> None:
        """Display the update dialog and attach pipeline worker."""
        from ui.update_dialog import UpdateDialog

        if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
            if worker:
                self._update_dialog.attach_pipeline_worker(worker)
            self._update_dialog.raise_()
            self._update_dialog.activateWindow()
            return

        self._update_dialog = UpdateDialog(
            version=version,
            is_force=is_force,
            installer_path=installer_path,
            parent=self,
            pipeline_worker=worker,
        )
        self._update_dialog.show()

    def _on_update_button_clicked(self) -> None:
        """Handle header update button click."""
        version = self._latest_version or "Latest"
        self._show_update_dialog(
            version=version,
            is_force=self._is_force_update,
            installer_path=self._latest_installer_path,
            worker=getattr(self, "_pipeline_worker", None),
        )

        