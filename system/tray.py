"""System tray (Windows) / menu bar (macOS) integration.

``QSystemTrayIcon`` is a single Qt abstraction that maps to the native tray
on Windows and the native menu bar on macOS, so this module needs no
platform branching at all - it satisfies the "same abstraction where
possible" requirement from the spec.
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QStyle, QSystemTrayIcon, QWidget

from config.settings import APP_NAME
from utils.logger import get_logger

logger = get_logger(__name__)


class TrayController:
    """Builds and owns the tray icon and its menu.

    The menu matches the spec:
        Activity Tracker
        ----------------
        Show Dashboard
        Start WorkPulse
        Stop WorkPulse
        Today's Activity
        Settings
        Exit
    """

    def __init__(
        self,
        parent: QWidget,
        on_show_dashboard,
        on_start_workpulse,
        on_stop_workpulse,
        on_show_today_activity,
        on_show_settings,
        on_exit=None,
        on_check_updates=None,
        show_exit: bool = False,
    ) -> None:
        self._parent = parent
        import os
        import sys
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base, "assets", "ihrms-logo-icon.ico")
        if os.path.isfile(icon_path):
            icon = QIcon(icon_path)
        else:
            style = parent.style()
            icon = style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

        self.tray_icon = QSystemTrayIcon(icon, parent)
        self.tray_icon.setToolTip(APP_NAME)

        menu = QMenu(parent)

        title_action = QAction(APP_NAME, parent)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()

        self.show_action = QAction("Show Dashboard", parent)
        self.show_action.triggered.connect(on_show_dashboard)
        menu.addAction(self.show_action)

        self.start_action = QAction("Start WorkPulse", parent)
        self.start_action.triggered.connect(on_start_workpulse)
        self.start_action.setVisible(False)
        menu.addAction(self.start_action)

        self.stop_action = QAction("Stop WorkPulse", parent)
        self.stop_action.triggered.connect(on_stop_workpulse)
        self.stop_action.setVisible(False)
        menu.addAction(self.stop_action)

        self.today_action = QAction("Today's Activity", parent)
        self.today_action.triggered.connect(on_show_today_activity)
        menu.addAction(self.today_action)

        self.settings_action = QAction("Settings", parent)
        self.settings_action.triggered.connect(on_show_settings)
        menu.addAction(self.settings_action)

        if on_check_updates:
            self.update_action = QAction("Check for Updates", parent)
            self.update_action.triggered.connect(on_check_updates)
            menu.addAction(self.update_action)

        # Exit option removed from tray menu to prevent exiting from background
        self.exit_action: QAction | None = None
        if show_exit and on_exit:
            menu.addSeparator()
            self.exit_action = QAction("Exit", parent)
            self.exit_action.triggered.connect(on_exit)
            menu.addAction(self.exit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_activated)
        self._on_show_dashboard = on_show_dashboard

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left-click (Trigger) on Windows and macOS opens the dashboard,
        # matching the common convention on both platforms.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_show_dashboard()

    def show(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available on this system")
            return
        self.tray_icon.show()

    def set_workpulse_state(self, is_workpulse: bool) -> None:
        if hasattr(self, "start_action") and self.start_action:
            self.start_action.setEnabled(not is_workpulse)
            self.start_action.setVisible(False)
        if hasattr(self, "stop_action") and self.stop_action:
            self.stop_action.setEnabled(False)
            self.stop_action.setVisible(False)

    def show_message(self, title: str, message: str) -> None:
        self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)
