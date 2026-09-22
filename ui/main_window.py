"""Main application window."""

from __future__ import annotations

import getpass
import os
import platform
import sys
import threading
import time
import webbrowser

from PySide6.QtCore import QMetaObject, QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
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


def _asset_path(relative: str) -> str:
    """Return the absolute path to a bundled asset."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _load_icon(name: str) -> QIcon:
    """Load an icon from ``assets/icons`` with SVG preference and PNG fallback."""
    for extension in (".svg", ".png"):
        path = _asset_path(os.path.join("assets", "icons", name + extension))
        if os.path.isfile(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    return QIcon()



from config.settings import APP_NAME, get_running_app_version
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
from ui.attendance_page import AttendancePage
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
        # pyrefly: ignore [missing-import]
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
        # pyrefly: ignore [missing-import]
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
    """Collect user/device information prioritizing active session context.

    This function is cross-platform.
    """
    from services.session_service import SessionService

    session = SessionService().current_user

    username = (
        session.username
        if session and session.username
        else (getpass.getuser() or "Not available")
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

    name = session.full_name if session and session.full_name else ""
    email = getattr(session, "email", "") if session else ""

    # ----------------------------------------------------------
    # macOS
    # ----------------------------------------------------------

    if not name and platform_name == "Darwin":
        name, email = (
            get_mac_user_info()
        )

    # ----------------------------------------------------------
    # Windows
    # ----------------------------------------------------------

    elif not name and platform_name == "Windows":
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

    if not name:
        name = username

    from config.settings import get_running_app_version
    from utils.device import get_device_identifier

    app_version = get_running_app_version()
    device_id = get_device_identifier()

    return {
        "name": name or "Not available",
        "email": email or (username if "@" in str(username) else "Not available"),
        "username": username,
        "employee_id": (session.employee_id or session.indo_code) if session else "Not available",
        "role": (session.role or session.user_type) if session else "Not available",
        "company_code": session.company_code if session else "Not available",
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

        # Tabs: User & Device Information
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
        form.addRow("Employee ID:", QLabel(information.get("employee_id", "Not available")))
        form.addRow("Username:", QLabel(information.get("username", "Not available")))
        form.addRow("Email:", QLabel(information.get("email", "Not available")))
        form.addRow("Company Code:", QLabel(information.get("company_code", "Not available")))
        form.addRow("Role / Type:", QLabel(information.get("role", "Not available")))
        form.addRow("Device / Hostname:", QLabel(information.get("device", "Not available")))
        form.addRow("Platform / OS:", QLabel(f"{information.get('platform', '')} ({information.get('os_version', '')})"))
        form.addRow("Device ID:", QLabel(information.get("device_identifier", "Not available")))

        app_ver = information.get("app_version", get_running_app_version())
        ver_lbl = QLabel(f"{app_ver} (authoritative build)")
        ver_lbl.setStyleSheet("font-weight: bold; color: #3b82f6;")
        form.addRow("Installed Version:", ver_lbl)

        # Status badge for this device
        from services.device_registry_service import DeviceRegistryService
        cur_status = "Update Successful"
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
        if cur_status in ("Update Successful", "Updated"):
            status_lbl.setStyleSheet("font-weight: bold; color: #10b981;")
        elif "Pending" in cur_status:
            status_lbl.setStyleSheet("font-weight: bold; color: #f59e0b;")
        elif "Failed" in cur_status or "Error" in cur_status:
            status_lbl.setStyleSheet("font-weight: bold; color: #ef4444;")
        else:
            status_lbl.setStyleSheet("color: #6b7280;")
        form.addRow("Update Status:", status_lbl)

        current_layout.addLayout(form)
        current_layout.addStretch()
        tabs.addTab(tab_current, "User & Device")
        root.addWidget(tabs)

        # Close button
        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)


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
    _request_system_suspend = Signal()
    _request_system_resume = Signal()

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

        # Listen for dynamic permission updates pushed from backend
        from services.session_service import SessionService
        SessionService().register_permission_listener(self._apply_rbac_permissions)

        # Ensure startup registration matches settings
        initial_settings = self._settings_service.get_settings()
        from system import startup
        if initial_settings.start_with_system:
            startup.set_enabled(True)

        # Auto-start tracking on startup based on active session & RBAC permissions
        from services.session_service import SessionService
        session = SessionService().current_user

        if session is not None and not getattr(session, "tracking_permitted", True):
            logger.info("Auto-starting tracking skipped due to RBAC permissions.")
            if hasattr(self, "dashboard_page") and self.dashboard_page:
                self.dashboard_page.set_tracking_active(False)
        else:
            logger.info("Auto-starting tracking on startup based on active session and RBAC permissions.")
            self.start_tracking()

        is_running_tests = "unittest" in sys.modules or any("unittest" in str(a).lower() for a in sys.argv)

        # Post-render check: ensure tracking is definitely active
        from PySide6.QtCore import QTimer
        if not is_running_tests:
            QTimer.singleShot(200, self._ensure_tracking_started)

        # Update system state
        self._update_dialog = None
        self._latest_installer_path: str | None = None
        self._latest_version: str | None = None
        self._is_force_update: bool = False
        self._offline_update_pending: bool = False

        # Fast retry timer when offline or update is pending
        self._offline_update_retry_timer = QTimer(self)
        self._offline_update_retry_timer.setInterval(30 * 1000)  # 30 seconds
        self._offline_update_retry_timer.timeout.connect(lambda: self._check_for_updates(manual=False))

        if not is_running_tests:
            # Trigger background automatic update check shortly after startup
            QTimer.singleShot(2000, self._check_for_updates)

            # Also schedule recurring update checks every 2 hours for continuously open laptops
            self._periodic_update_timer = QTimer(self)
            self._periodic_update_timer.setInterval(2 * 60 * 60 * 1000)
            self._periodic_update_timer.timeout.connect(lambda: self._check_for_updates(manual=False))
            self._periodic_update_timer.start()
        else:
            self._periodic_update_timer = None

        # Verify post-restart update status and record device heartbeat with current running app version
        try:
            from services.update_state import UpdateStateManager
            from services.device_registry_service import DeviceRegistryService
            from utils.device import get_device_identifier

            UpdateStateManager().check_post_restart_status()

            DeviceRegistryService().record_heartbeat(
                employee_id=getattr(session, "employee_id", None),
                username=getattr(session, "username", None),
                device_token=getattr(session, "device_token", None),
            )
            my_status = "Update Successful"
            for d in DeviceRegistryService().get_all_devices():
                if d["device_identifier"] == get_device_identifier():
                    my_status = d["update_status"]
                    break
            self.dashboard_page.set_update_status(my_status)
            if my_status == "Update Pending":
                self._offline_update_pending = True
        except Exception:
            pass

        if not is_running_tests:
            # Trigger initial backend settings sync and setup periodic refresh timer
            QTimer.singleShot(500, self._sync_permissions_from_backend)
            self._periodic_settings_timer = QTimer(self)
            self._periodic_settings_timer.setInterval(60 * 1000)
            self._periodic_settings_timer.timeout.connect(self._sync_permissions_from_backend)
            self._periodic_settings_timer.start()
        else:
            self._periodic_settings_timer = None

        # macOS-only: defer Screen Recording permission check until window is visible
        if sys.platform == "darwin" and not is_running_tests:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(800, self._check_mac_screen_recording_permission)

    def _sync_permissions_from_backend(self) -> None:
        """Fetch latest backend configuration to dynamically apply permission changes in a background thread."""
        if getattr(self, "_syncing_permissions", False):
            return
        self._syncing_permissions = True

        def _bg_fetch():
            try:
                from services.sync_service import SyncService
                SyncService().fetch_settings()
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self._apply_rbac_permissions)
            except Exception as err:
                logger.debug("Background settings sync encountered: %s", err)
            finally:
                self._syncing_permissions = False

        threading.Thread(target=_bg_fetch, name="SettingsSyncWorker", daemon=True).start()

    # ==========================================================
    # macOS SCREEN RECORDING PERMISSION  (ISOLATED FROM AUTO-UPDATE)
    # ==========================================================

    def _check_mac_screen_recording_permission(self) -> None:
        """Check macOS Screen Recording TCC permission on startup.

        This method is ONLY called on darwin and is completely separate from
        the auto-update pipeline.  It must NEVER modify ``update_button``,
        call ``UpdateService``, or touch ``UpdateStateManager``.
        """
        if sys.platform != "darwin":
            return
        try:
            from services.mac_permission_service import (
                has_screen_recording_permission,
                reset_relaunch_state,
            )
            if has_screen_recording_permission():
                # Permission granted (normal path after relaunch)
                logger.info("macOS Screen Recording permission: granted")
                reset_relaunch_state()  # Clear loop counter on successful grant
                # Ensure screenshot tracking is active now that permission exists
                self._ensure_tracking_started()
                return
            logger.warning(
                "macOS Screen Recording permission: NOT granted. "
                "Scheduling user prompt."
            )
            self._prompt_mac_screen_recording()
        except Exception as exc:
            logger.debug("_check_mac_screen_recording_permission error: %s", exc)

    def _prompt_mac_screen_recording(self) -> None:
        """Show a user-friendly dialog explaining Screen Recording permission.

        Offers 'Open Settings' to navigate directly to the Privacy pane and
        'Quit & Reopen' to relaunch the app once the user has toggled the
        permission switch.

        A persistent loop-guard (mac_permission_service.can_relaunch) prevents
        infinite relaunch cycles if the user never actually enables the
        permission.
        """
        if sys.platform != "darwin":
            return
        try:
            from services.mac_permission_service import (
                can_relaunch,
                open_screen_recording_settings,
                relaunch_application,
                request_screen_recording_permission,
            )

            # Trigger the TCC alert so the app registers with Privacy DB
            request_screen_recording_permission()

            ok, reason = can_relaunch()
            if not ok:
                # Relaunch limit reached – show a plain info message and stop.
                logger.error(
                    "macOS Screen Recording relaunch limit reached: %s", reason
                )
                msg = QMessageBox(self)
                msg.setWindowTitle("Screen Recording Permission Required")
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setText(
                    "Workpulse needs Screen Recording permission to capture "
                    "screenshots for attendance tracking.\n\n"
                    f"{reason}"
                )
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.exec()
                return

            msg = QMessageBox(self)
            msg.setWindowTitle("Screen Recording Permission Required")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(
                "Workpulse needs Screen Recording permission to capture "
                "screenshots for attendance tracking."
            )
            msg.setInformativeText(
                "1. Click \"Open Settings\" below.\n"
                "2. Find Workpulse in the list and enable the toggle.\n"
                "3. Return here and click \"Quit & Reopen\"."
            )
            open_btn = msg.addButton("Open Settings", QMessageBox.ButtonRole.ActionRole)
            relaunch_btn = msg.addButton("Quit & Reopen", QMessageBox.ButtonRole.AcceptRole)
            msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            clicked = msg.clickedButton()
            if clicked is open_btn:
                open_screen_recording_settings()
                # Re-show the dialog so the user can click Quit & Reopen
                # after they enable the permission.
                from PySide6.QtCore import QTimer
                QTimer.singleShot(500, self._prompt_mac_screen_recording)
            elif clicked is relaunch_btn:
                logger.info(
                    "User clicked 'Quit & Reopen' for Screen Recording permission."
                )
                # Clean shutdown -> relaunch (mac_permission_service handles
                # both QApplication.quit() and the new process spawn)
                self._really_quit = True
                relaunch_application()
        except Exception as exc:
            logger.debug("_prompt_mac_screen_recording error: %s", exc)

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
        display_name = session.display_name if session else "User"

        self.user_label = QLabel(f"Welcome, {display_name}")
        self.user_label.setStyleSheet("font-weight: 600; color: #5f6368; margin-right: 10px;")
        header_layout.addWidget(self.user_label)

        # Tracking status icon next to status badge
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(24, 24)
        self.status_icon.setStyleSheet("margin-right: 4px; background: transparent;")
        header_layout.addWidget(self.status_icon)

        self.status_badge = QLabel("Offline")
        self.status_badge.setObjectName("StatusBadge")
        self.status_badge.setProperty("tracking", "false")
        self.status_badge.setCursor(Qt.CursorShape.ArrowCursor)
        self.status_badge.setToolTip("Activity Tracking Status")
        header_layout.addWidget(self.status_badge)

        # ------------------------------------------------------
        # HRMS Portal Button (with Globe Icon)
        # ------------------------------------------------------
        self.hrms_button = QPushButton(" HRMS")
        self.hrms_button.setObjectName("SecondaryButton")
        self.hrms_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hrms_button.setToolTip("Open HRMS Web Portal (https://ihrms.indovisionservices.in)")

        globe_icon = _load_icon("globe")
        if not globe_icon.isNull():
            self.hrms_button.setIcon(globe_icon)
            self.hrms_button.setIconSize(QSize(18, 18))

        self.hrms_button.clicked.connect(self._open_hrms_portal)
        header_layout.addWidget(self.hrms_button)

        # ------------------------------------------------------
        # Tracking controls (Internal, hidden from all users)
        # ------------------------------------------------------

        self.start_button = QPushButton("Start Tracking")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self.start_tracking)
        self.start_button.setVisible(False)
        self.start_button.hide()
        header_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Tracking")
        self.stop_button.setObjectName("SecondaryButton")
        self.stop_button.clicked.connect(lambda: self.stop_tracking(manual=False))
        self.stop_button.setEnabled(False)
        self.stop_button.setVisible(False)
        self.stop_button.hide()


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

        self.attendance_page = (
            AttendancePage(
                self._attendance_service if hasattr(self, "_attendance_service") else None
            )
        )
        self.weekly_page = self.attendance_page

        self.settings_page = (
            SettingsPage(
                self._settings_service
            )
        )

        self.settings_page.settings_changed.connect(
            self._on_settings_changed
        )

        self.dashboard_page.attendance_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.attendance_page)
        )
        self.dashboard_page.weekly_timeline_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.attendance_page)
        )
        self.attendance_page.back_requested.connect(
            lambda: self.tabs.setCurrentWidget(self.dashboard_page)
        )
        self.dashboard_page.tracking_start_requested.connect(
            self.start_tracking
        )
        self.dashboard_page.tracking_stop_requested.connect(
            lambda: self.stop_tracking(manual=True)
        )
        self.dashboard_page.pause_state_changed.connect(
            self._on_pause_state_changed
        )

        self.tabs.addTab(
            self.dashboard_page,
            "Dashboard",
        )

        self.tabs.addTab(
            self.attendance_page,
            "Attendance",
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

    def _on_header_refresh_clicked(self) -> None:
        """Trigger asynchronous dashboard and attendance refresh from top header button."""
        if hasattr(self, "dashboard_page") and self.dashboard_page is not None:
            self.dashboard_page.refresh(async_mode=True)
        if hasattr(self, "attendance_page") and self.attendance_page is not None and hasattr(self, "tabs") and self.tabs.currentWidget() == self.attendance_page:
            self.attendance_page.refresh(async_mode=True)
        elif hasattr(self, "weekly_page") and self.weekly_page is not None and hasattr(self, "tabs") and self.tabs.currentWidget() == self.weekly_page:
            self.weekly_page.refresh(async_mode=True)

    # ==========================================================
    # USER / DEVICE
    # ==========================================================

    def _show_user_device_info(
        self,
    ) -> None:
        """Detect and display current user/device information."""
        from services.session_service import SessionService
        session = SessionService().current_user
        if session and not getattr(session, "allow_user_device", True):
            logger.warning("User/Device view requested but blocked by backend permission.")
            return

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
        if hasattr(self, "_thread") and self._thread is not None and self._thread.isRunning():
            logger.warning("_build_tracker called when thread is already running; skipping to prevent duplicate workers")
            return

        try:
            provider = (
                create_activity_provider()
            )

        except Exception as exc:
            logger.exception(
                "Failed to create platform activity provider"
            )
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="TRACKING_PROVIDER_ERROR",
                    error_message=f"Failed to create platform activity provider: {exc}",
                    exc=exc,
                )
            except Exception:
                pass

            QMessageBox.critical(
                self,
                APP_NAME,
                f"This version of {APP_NAME} "
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

        self._request_system_suspend.connect(
            self._worker.handle_system_suspend
        )

        self._request_system_resume.connect(
            self._worker.handle_system_resume
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
            on_stop_tracking=lambda: self.stop_tracking(manual=True),
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
        """Enforce RBAC permissions on Start/Stop tracking, User/Device, and Logout controls."""
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app and QThread.currentThread() != app.thread():
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._apply_rbac_permissions)
            return

        from services.session_service import SessionService
        session = SessionService().current_user

        # Unconditionally hide "Stop Tracking" and "Start Tracking" buttons for all users
        self.stop_button.setVisible(False)
        self.stop_button.hide()
        self.start_button.setVisible(False)
        self.start_button.hide()
        if hasattr(self, "tray") and self.tray:
            if hasattr(self.tray, "stop_action") and self.tray.stop_action:
                self.tray.stop_action.setVisible(False)
            if hasattr(self.tray, "start_action") and self.tray.start_action:
                self.tray.start_action.setVisible(False)

        if session and not session.tracking_permitted:
            logger.info("Enforcing RBAC tracking restrictions: hiding tracking status")
            if hasattr(self, "status_icon") and self.status_icon:
                self.status_icon.hide()
            self.status_badge.hide()
        else:
            if hasattr(self, "status_icon") and self.status_icon:
                self.status_icon.show()
            self.status_badge.show()

        # User/Device button removed from UI; underlying logic retained.

        # Dynamic Logout control visibility and access
        allow_logout = getattr(session, "allow_logout", True) if session else True
        if hasattr(self, "logout_button") and self.logout_button:
            self.logout_button.setVisible(allow_logout)
            self.logout_button.setEnabled(allow_logout)

        display_name = session.display_name if session else "User"
        if hasattr(self, "user_label") and self.user_label:
            self.user_label.setText(f"Welcome, {display_name}")

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
        is_paused = False
        
        # Check current state from status badge property
        tracking_prop = self.status_badge.property("tracking")
        if tracking_prop == "true":
            is_active = True
        elif tracking_prop == "idle":
            is_active = True
            is_idle = True
        elif tracking_prop == "paused":
            is_active = True
            is_paused = True
            
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
        from PySide6.QtCore import Qt
        
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Set color based on state
        if is_active:
            if is_paused or is_idle:
                color = QColor("#b06000") # Idle / Paused (amber)
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

        # Update persistent tracking state
        from services.secure_session import SessionStore
        store = SessionStore()
        store.set_tracking_manually_stopped(False)
        store.set_tracking_active(True)

        # Update UI state immediately to show Active
        self.status_badge.setText("Online")
        self.status_badge.setProperty("tracking", "true")
        self._refresh_badge_style()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        if hasattr(self, "tray") and self.tray:
            self.tray.set_tracking_state(True)
        if hasattr(self, "settings_page") and self.settings_page:
            self.settings_page.update_capture_status(True)
        if hasattr(self, "dashboard_page") and self.dashboard_page:
            self.dashboard_page.set_tracking_active(True)
            if self.dashboard_page.current_app_label.text() in ("Not tracking", ""):
                self.dashboard_page.current_app_label.setText("Detecting...")

        # Guard against duplicate start if tracker is already tracking
        if hasattr(self, "_tracker") and self._tracker.is_tracking:
            logger.debug("ActivityTracker is already tracking; skipping duplicate start.")
            return

        self._request_start.emit()

    def _ensure_tracking_started(self) -> None:
        """Verify tracking has started after login/startup; if not, trigger start_tracking if not manually stopped."""
        from services.secure_session import SessionStore
        if SessionStore().is_tracking_manually_stopped():
            logger.debug("Tracking was manually stopped; skipping _ensure_tracking_started.")
            return

        from services.session_service import SessionService
        session = SessionService().current_user
        if (session is None or getattr(session, "tracking_permitted", True)) and hasattr(self, "_tracker") and not self._tracker.is_tracking:
            logger.info("Ensuring tracking is active after login/startup.")
            self.start_tracking()

    @Slot()
    def stop_tracking(
        self,
        manual: bool = True,
    ) -> None:
        """Stop tracking.
        
        Args:
            manual: If True, records that the user manually stopped tracking,
                    preserving the stopped state across restarts.
                    If False, automated/internal stop (e.g. before update).
        """
        if manual:
            from services.secure_session import SessionStore
            store = SessionStore()
            store.set_tracking_manually_stopped(True)
            store.set_tracking_active(False)

        # Update UI state immediately to show Inactive
        self.status_badge.setText("Offline")
        self.status_badge.setProperty("tracking", "false")
        self._refresh_badge_style()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if hasattr(self, "tray") and self.tray:
            self.tray.set_tracking_state(False)
        if hasattr(self, "settings_page") and self.settings_page:
            self.settings_page.update_capture_status(False)
        if hasattr(self, "dashboard_page") and self.dashboard_page:
            self.dashboard_page.set_tracking_active(False)

        self._request_stop.emit()

    @Slot()
    def stop_tracking_for_update(self) -> None:
        """Stop tracking cleanly before an auto-update without setting the manual stop flag."""
        logger.info("Stopping tracking cleanly before auto-update installation.")
        self.stop_tracking(manual=False)

    @Slot()
    def _on_tracking_started(
        self,
    ) -> None:
        """Update UI after tracking starts."""
        from services.secure_session import SessionStore
        if SessionStore().is_tracking_manually_stopped():
            logger.debug("Stale tracking_started signal received while tracking is marked stopped; ignoring")
            return

        self.status_badge.setText(
            "Online"
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
        if hasattr(self, "dashboard_page") and self.dashboard_page:
            self.dashboard_page.set_tracking_active(True)
        self._apply_rbac_permissions()

    @Slot()
    def _on_tracking_stopped(
        self,
    ) -> None:
        """Update UI after tracking stops."""
        from services.secure_session import SessionStore
        if SessionStore().is_tracking_active() or (hasattr(self, "_tracker") and self._tracker.is_tracking):
            logger.debug("Stale tracking_stopped signal received while tracking is active; ignoring")
            return

        self.status_badge.setText(
            "Offline"
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
        if hasattr(self, "dashboard_page") and self.dashboard_page:
            self.dashboard_page.set_tracking_active(False)

        self.dashboard_page.refresh()
        self._apply_rbac_permissions()

    @Slot(object)
    def _on_tracker_state_changed(
        self,
        state: TrackerState,
    ) -> None:
        """Update dashboard from tracker state."""
        from services.secure_session import SessionStore
        store = SessionStore()
        if not state.is_tracking and (store.is_tracking_active() or (hasattr(self, "_tracker") and self._tracker.is_tracking)):
            logger.debug("Stale inactive TrackerState received while tracking is active; ignoring")
            return
        if state.is_tracking and store.is_tracking_manually_stopped():
            logger.debug("Stale active TrackerState received while tracking is manually stopped; ignoring")
            return

        self.dashboard_page.update_tracker_state(
            state
        )

        if getattr(self.dashboard_page, "_is_paused", False) or store.is_tracking_paused():
            self.status_badge.setText(
                "Paused"
            )

            self.status_badge.setProperty(
                "tracking",
                "paused",
            )

            self._refresh_badge_style()

        elif state.is_idle:
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
                "Online"
            )

            self.status_badge.setProperty(
                "tracking",
                "true",
            )

            self._refresh_badge_style()
        else:
            self.status_badge.setText(
                "Offline"
            )

            self.status_badge.setProperty(
                "tracking",
                "false",
            )

            self._refresh_badge_style()

        now_ts = time.time()
        last_refresh_ts = getattr(self, "_last_table_refresh_ts", 0)
        last_app = getattr(self, "_last_rendered_app", None)
        last_idle = getattr(self, "_last_rendered_idle", None)

        app_switched = (state.current_application != last_app) or (state.is_idle != last_idle)
        time_elapsed = (now_ts - last_refresh_ts) >= 5.0

        if app_switched or time_elapsed:
            self._last_table_refresh_ts = now_ts
            self._last_rendered_app = state.current_application
            self._last_rendered_idle = state.is_idle
            self.dashboard_page.refresh(async_mode=True)
            if hasattr(self, "weekly_page") and self.weekly_page.isVisible():
                self.weekly_page.refresh(async_mode=True)
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

    @Slot(bool)
    def _on_pause_state_changed(self, is_paused: bool) -> None:
        """Update top bar status badge when pause status changes without stopping background workers."""
        from services.secure_session import SessionStore
        SessionStore().set_tracking_paused(is_paused)
        if is_paused:
            self.status_badge.setText("Paused")
            self.status_badge.setProperty("tracking", "paused")
        else:
            if hasattr(self, "_tracker") and self._tracker.is_tracking:
                if hasattr(self, "_last_rendered_idle") and self._last_rendered_idle:
                    self.status_badge.setText("Idle")
                    self.status_badge.setProperty("tracking", "idle")
                else:
                    self.status_badge.setText("Online")
                    self.status_badge.setProperty("tracking", "true")
            else:
                self.status_badge.setText("Offline")
                self.status_badge.setProperty("tracking", "false")
        self._refresh_badge_style()

    def _on_status_badge_clicked(self, event=None) -> None:
        """Allow clicking the status badge to start/resume tracking if currently inactive."""
        from services.session_service import SessionService
        session = SessionService().current_user
        if session and not session.tracking_permitted:
            return

        is_tracking = False
        if hasattr(self, "_tracker") and self._tracker.is_tracking:
            is_tracking = True
        elif self.status_badge.property("tracking") in ("true", "idle", "paused"):
            is_tracking = True

        if not is_tracking:
            logger.info("Status badge clicked while inactive; resuming tracking.")
            self.start_tracking()

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

        tracking_prop = self.status_badge.property("tracking")
        if tracking_prop == "true":
            self.status_badge.setToolTip("Tracking is active")
        elif tracking_prop == "paused":
            self.status_badge.setToolTip("Status: Paused")
        elif tracking_prop == "idle":
            self.status_badge.setToolTip("Currently idle")
        else:
            self.status_badge.setToolTip("Click to start tracking")

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
            self.weekly_page.refresh(async_mode=True)
        elif hasattr(self, "dashboard_page") and current_widget == self.dashboard_page:
            self.dashboard_page.refresh(async_mode=True)
        elif hasattr(self, "settings_page") and current_widget == self.settings_page:
            self.settings_page.reload()
            if hasattr(self, "_tracker") and self._tracker:
                self.settings_page.update_capture_status(self._tracker.is_tracking)

    @Slot()
    def logout(self) -> None:
        from services.session_service import SessionService
        session = SessionService().current_user
        if session and not getattr(session, "allow_logout", True):
            logger.warning("Logout requested but blocked by backend permission.")
            return

        logger.info("Logging out user")
        self.stop_tracking(manual=False)
        self._shutdown()

        # Hide main window and return to login screen immediately so UI never hangs
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

        # Flush pending activities and screenshots asynchronously in a background thread so UI never freezes
        def _flush_sync_on_logout():
            try:
                from services.sync_service import SyncService
                logger.info("Flushing pending activity and screenshots for user before logout...")
                SyncService().sync_activity_now()
                SyncService.reset_sync_state()
            except Exception as flush_err:
                logger.warning("Could not flush sync on logout: %s", flush_err)

        threading.Thread(target=_flush_sync_on_logout, name="LogoutFlushWorker", daemon=True).start()

        from services.session_service import SessionService
        SessionService().logout()

        # Clear saved session for auto-login
        try:
            from services.secure_session import SessionStore
            SessionStore().clear_session()
        except Exception:
            logger.warning("Failed to clear saved session", exc_info=True)

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

        self.dashboard_page.refresh(async_mode=True)

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
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.quit()
            return

        event.ignore()
        self.hide()
        if hasattr(self, "tray") and self.tray:
            self.tray.show_message(
                APP_NAME,
                "Still tracking in the background.",
            )

    def nativeEvent(self, eventType, message):
        """Handle native Windows events including system power suspend/resume and shutdown/restart."""
        try:
            if eventType == b"windows_generic_MSG":
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                WM_QUERYENDSESSION = 0x0011
                WM_ENDSESSION = 0x0016
                WM_POWERBROADCAST = 0x0218
                PBT_APMSUSPEND = 0x0004
                PBT_APMRESUMEAUTOMATIC = 0x0012
                PBT_APMRESUMESUSPEND = 0x0007

                if msg.message in (WM_QUERYENDSESSION, WM_ENDSESSION):
                    logger.info("Native Windows Shutdown/Restart received: message=0x%04x. Performing clean shutdown.", msg.message)
                    self._really_quit = True
                    self._shutdown()
                    return True, 1
                elif msg.message == WM_POWERBROADCAST:
                    if msg.wParam == PBT_APMSUSPEND:
                        logger.info("Native WM_POWERBROADCAST: System entering suspend/sleep.")
                        self._request_system_suspend.emit()
                    elif msg.wParam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                        logger.info("Native WM_POWERBROADCAST: System resumed from sleep.")
                        self._request_system_resume.emit()
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(200, self.dashboard_page.refresh)
                        QTimer.singleShot(200, self._apply_rbac_permissions)
        except Exception as power_err:
            logger.debug("Error handling native event: %s", power_err)
        return super().nativeEvent(eventType, message)

    def _shutdown(
        self,
    ) -> None:
        """Stop tracker and cleanly shut down."""

        if getattr(self, "_is_shutting_down", False):
            return
        self._is_shutting_down = True

        logger.info(
            "Shutting down application"
        )

        try:
            if hasattr(self, "_periodic_settings_timer") and self._periodic_settings_timer and self._periodic_settings_timer.isActive():
                self._periodic_settings_timer.stop()
            if hasattr(self, "_periodic_update_timer") and self._periodic_update_timer and self._periodic_update_timer.isActive():
                self._periodic_update_timer.stop()
            if hasattr(self, "_offline_update_retry_timer") and self._offline_update_retry_timer and self._offline_update_retry_timer.isActive():
                self._offline_update_retry_timer.stop()
            if hasattr(self, "_pipeline_worker") and self._pipeline_worker:
                if self._pipeline_worker.isRunning():
                    self._pipeline_worker.cancel()
                    self._pipeline_worker.quit()
                    self._pipeline_worker.wait(2000)
            from services.session_service import SessionService
            SessionService().unregister_permission_listener(self._apply_rbac_permissions)
        except Exception as e:
            logger.debug("Error stopping timers/listeners during shutdown: %s", e)

        # 1. Gracefully stop tracker and timer on worker thread before quitting event loop
        try:
            if hasattr(self, "_worker") and self._worker:
                from PySide6.QtCore import QThread
                if hasattr(self, "_thread") and self._thread and self._thread.isRunning():
                    if QThread.currentThread() == self._thread:
                        self._worker.stop_tracking()
                        self._worker.cleanup()
                    else:
                        QMetaObject.invokeMethod(
                            self._worker,
                            "stop_tracking",
                            Qt.ConnectionType.BlockingQueuedConnection,
                        )
                        QMetaObject.invokeMethod(
                            self._worker,
                            "cleanup",
                            Qt.ConnectionType.BlockingQueuedConnection,
                        )
                else:
                    self._worker.stop_tracking()
            elif hasattr(self, "_tracker") and self._tracker:
                self._tracker.stop()
        except Exception:
            logger.exception(
                "Error stopping tracker during shutdown"
            )

        # 2. Tell QThread to quit event loop and wait for it to exit completely
        if hasattr(self, "_thread") and self._thread:
            if self._thread.isRunning():
                self._thread.quit()
                if not self._thread.wait(3000):
                    logger.warning("Tracker thread did not exit cleanly within timeout, terminating.")
                    self._thread.terminate()
                    self._thread.wait(1000)

    # ==========================================================
    # AUTOMATIC UPDATES
    # ==========================================================

    def _check_for_updates(self, manual: bool = False) -> None:
        """Trigger background version check from update API using unified pipeline."""
        try:
            from config.api_config import ApiConfig
            from services.session_service import SessionService
            from services.update_service import UpdateService
            from services.update_state import UpdateStateManager

            if manual:
                try:
                    UpdateStateManager().reset_cooldown()
                except Exception:
                    pass

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
                    self.dashboard_page.set_update_status("Update Successful")
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
                        f"{APP_NAME} Update",
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
                    self.dashboard_page.set_update_status("Update Error")
                    from config.settings import get_running_app_version
                    from services.update_service import is_newer_version
                    if self._latest_version and is_newer_version(self._latest_version, get_running_app_version()):
                        self.update_button.setText(f"Retry Update v{self._latest_version}")
                        self.update_button.setVisible(True)
                    else:
                        self.update_button.setVisible(False)

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
                logger.info("Pipeline update ready to install received on Main Thread: %s (target_version=%s)", installer_path, self._latest_version)
                self._latest_installer_path = installer_path
                self._really_quit = True
                if getattr(self, "_update_dialog", None) and self._update_dialog.isVisible():
                    try:
                        self._update_dialog.close()
                    except Exception:
                        pass
                from services.update_service import install_update_and_restart
                install_update_and_restart(installer_path, target_version=self._latest_version, exit_process=True)

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

    def _open_hrms_portal(self) -> None:
        """Open the iHRMS web portal in the user's default external browser with auto-login."""
        from services.hrms_portal_service import HrmsPortalService
        HrmsPortalService().open_portal_with_autologin()

