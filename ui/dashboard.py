"""Dashboard page for the Activity Tracker application."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Any
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.settings import get_running_app_version
from services.activity_service import ActivityService
from services.attendance_service import AttendanceService
from services.task_service import TaskService
from tracker.activity_tracker import TrackerState
from ui.activity_table import (
    ActivityTimelineTable,
    ApplicationUsageTable,
)
from ui.task_table import AssignedTasksTable
from utils.logger import get_logger

logger = get_logger(__name__)


def _format_time_ampm(time_val: Any) -> str | None:
    """Convert datetime or time string to user-friendly HH:MM AM/PM format."""
    if not time_val:
        return None
    try:
        val_str = str(time_val).strip()
        if not val_str or val_str.lower() in ("null", "none", "", "-", "--", "--:--", "--:-- --", "not punched"):
            return None
        if "T" in val_str:
            dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            return dt.strftime("%I:%M %p")
        if "-" in val_str and " " in val_str:
            dt = datetime.strptime(val_str[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%I:%M %p")
        if ":" in val_str:
            parts = val_str.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            period = "PM" if h >= 12 else "AM"
            h_12 = h % 12 or 12
            return f"{h_12:02d}:{m:02d} {period}"
        return val_str
    except Exception:
        return str(time_val)


def format_hh_mm_ss(total_seconds: int | float) -> str:
    """Format seconds into HH:MM:SS format."""
    total_seconds = max(0, int(total_seconds))
    h, rem = divmod(total_seconds, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


class DashboardPage(QWidget):
    """Main Activity Tracker dashboard."""

    attendance_requested = Signal()
    weekly_timeline_requested = attendance_requested
    data_refreshed = Signal(dict)
    error_reported = Signal(str, str)
    tracking_start_requested = Signal()
    tracking_stop_requested = Signal()
    tracking_toggle_requested = Signal()
    pause_state_changed = Signal(bool)

    def __init__(
        self,
        activity_service: ActivityService,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._service = activity_service
        self._is_refreshing = False
        self._cached_today_idle = 0
        self._cached_uploaded_count = 0
        self._cached_calendar_date = datetime.now().astimezone().date()

        self._is_tracking = False
        self._is_paused = False
        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            self._is_tracking = store.is_tracking_active() and not store.is_tracking_manually_stopped()
            self._is_paused = store.is_tracking_paused()
        except Exception:
            pass

        self.data_refreshed.connect(self._apply_dashboard_data)
        self.error_reported.connect(self._on_error_reported)

        try:
            from services.error_report_service import ErrorReportService
            ErrorReportService().register_listener(self._handle_global_error)
        except Exception:
            pass

        persisted = self._load_persisted_today_seconds(self._cached_calendar_date)
        db_seconds = 0
        try:
            val = self._service.get_today_total_seconds()
            if isinstance(val, (int, float)):
                db_seconds = max(0, int(val))
        except Exception:
            pass

        self._cached_today_total_seconds = max(persisted, db_seconds)

        self._build_ui()

        # Autonomous timer to detect midnight/calendar date rollover even if tracking is stopped
        self._date_timer = QTimer(self)
        self._date_timer.setInterval(10000)
        self._date_timer.timeout.connect(self._check_date_rollover)
        self._date_timer.start()

        # Dynamic network connectivity detector
        self._is_network_online = True
        self._network_timer = QTimer(self)
        self._network_timer.setInterval(3000)
        self._network_timer.timeout.connect(self._check_network_connectivity)
        self._network_timer.start()

        try:
            from services.network_monitor import NetworkReachabilityMonitor
            NetworkReachabilityMonitor().register_listener(self._on_reachability_changed)
            NetworkReachabilityMonitor().start_monitoring(interval=3.0)
        except Exception:
            pass

        try:
            att = AttendanceService().get_daily_attendance(self._cached_calendar_date.strftime("%Y-%m-%d"))
            self._update_attendance_ui(att)
        except Exception:
            pass

    def _update_attendance_ui(self, attendance: dict) -> None:
        """Update Start Time and Punch Time labels based on daily attendance."""
        if not isinstance(attendance, dict):
            return

        start_val = attendance.get("tracking_started_at") or attendance.get("system_started_at")
        start_formatted = _format_time_ampm(start_val)
        if start_formatted:
            self.start_time_label.setText(f"Start Time: {start_formatted}")
        else:
            self.start_time_label.setText("Start Time: --:-- --")

        punch_val = attendance.get("punch_in")
        punch_formatted = _format_time_ampm(punch_val)
        if punch_formatted:
            self.punch_time_label.setText(f"Punch Time: {punch_formatted}")
        else:
            self.punch_time_label.setText("Punch Time: Not Punched")

    def _save_persisted_today_seconds(self, seconds: int, cal_date) -> None:
        """Persist accumulated active seconds using ActivityService and SessionStore."""
        try:
            if hasattr(self._service, "save_daily_active_seconds"):
                self._service.save_daily_active_seconds(cal_date, seconds)
            else:
                from services.secure_session import SessionStore
                store = SessionStore()
                date_str = str(cal_date)
                store.settings.setValue(f"dashboard/daily_active_seconds/{date_str}", int(seconds))
                store.settings.setValue("dashboard/today_total_seconds", int(seconds))
                store.settings.setValue("dashboard/today_date", date_str)
        except Exception as err:
            logger.debug("_save_persisted_today_seconds failed: %s", err)

    def _load_persisted_today_seconds(self, cal_date) -> int:
        """Retrieve persisted active seconds for a given calendar date."""
        try:
            if hasattr(self._service, "get_persisted_daily_active_seconds"):
                val = self._service.get_persisted_daily_active_seconds(cal_date)
                if isinstance(val, (int, float)):
                    return max(0, int(val))
            from services.secure_session import SessionStore
            store = SessionStore()
            date_str = str(cal_date)
            val = store.settings.value(f"dashboard/daily_active_seconds/{date_str}")
            if val is not None:
                return max(0, int(val))
            saved_date = store.settings.value("dashboard/today_date")
            if saved_date and str(saved_date) == date_str:
                val = store.settings.value("dashboard/today_total_seconds")
                return max(0, int(val)) if val is not None else 0
            return 0
        except Exception as err:
            logger.debug("_load_persisted_today_seconds failed: %s", err)
            return 0

    def _check_date_rollover(self) -> None:
        """Verify calendar date and perform clean rollover when a new day begins."""
        current_date = datetime.now().astimezone().date()
        if current_date != self._cached_calendar_date:
            logger.info(
                "Calendar date rolled over from %s to %s. Finalizing previous day and resetting Active Time.",
                self._cached_calendar_date,
                current_date,
            )
            # Finalize and preserve previous day's accumulated active time
            prev_date = self._cached_calendar_date
            prev_seconds = self._cached_today_total_seconds
            self._save_persisted_today_seconds(prev_seconds, prev_date)

            # Advance to new calendar date
            self._cached_calendar_date = current_date
            new_day_seconds = self._load_persisted_today_seconds(current_date)
            self._cached_today_total_seconds = new_day_seconds
            self._cached_today_idle = 0
            self._save_persisted_today_seconds(new_day_seconds, current_date)

            self.active_time_val_label.setText(format_hh_mm_ss(new_day_seconds))
            self.today_idle_val_label.setText("00:00:00")
            self.today_total_label.setText(ActivityService.format_duration(new_day_seconds))
            try:
                att = AttendanceService().get_daily_attendance(current_date.strftime("%Y-%m-%d"))
                self._update_attendance_ui(att)
            except Exception:
                pass

    def is_paused(self) -> bool:
        """Return True if tracking status is currently Paused."""
        return self._is_paused

    def set_paused(self, paused: bool) -> None:
        """Update paused status without stopping background workers."""
        self._is_paused = bool(paused)
        try:
            from services.secure_session import SessionStore
            SessionStore().set_tracking_paused(self._is_paused)
        except Exception:
            pass
        self._apply_toggle_button_style(self._is_tracking)
        if self._is_paused:
            self.tracking_status_label.setText("Online: Paused")
        elif self._is_tracking:
            self.tracking_status_label.setText("Online: Active")
        else:
            self.tracking_status_label.setText("Online: Inactive")
        self.pause_state_changed.emit(self._is_paused)

    def _on_tracking_toggle_clicked(self) -> None:
        """Handle user clicking Paused / Resume button on Dashboard.

        Clicking Paused does NOT stop tracking, log collection, screenshots,
        or backend sync. It only changes the displayed tracking status to Paused
        and toggles the button text to Resume.
        """
        self.tracking_toggle_requested.emit()
        self.set_paused(not self._is_paused)

    def _build_ui(self) -> None:
        """Build the dashboard interface."""

        # The dashboard lives inside a scroll area so that a short window
        # scrolls cleanly without clipping content off the bottom.
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(12)

        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        # ==============================================================
        # 1. Top Row: [ Today's Time ] [ Attendance ] [ Tracking & Sync Status ]
        # ==============================================================
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        # --------------------------------------------------------------
        # 1. Today's Time
        # Shows Active Time (HH:MM:SS) and Weekly Timeline button
        # --------------------------------------------------------------
        today_group = QGroupBox("Today's Time")
        today_layout = QVBoxLayout(today_group)
        today_layout.setContentsMargins(14, 12, 14, 12)
        today_layout.setSpacing(4)

        active_title = QLabel("Active Time")
        active_title.setObjectName("StatusLabel")
        active_title.setStyleSheet("color: #64748b; font-size: 12px; font-weight: 500;")
        self.active_time_val_label = QLabel(
            format_hh_mm_ss(self._cached_today_total_seconds)
        )
        self.active_time_val_label.setObjectName("TimeValueLabel")
        self.active_time_val_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #0F172A;")

        # Retain today_idle_val_label internally for background tracking and test compatibility
        self.today_idle_val_label = QLabel(
            format_hh_mm_ss(self._cached_today_idle)
        )
        self.today_idle_val_label.setVisible(False)

        # Retain aliases for backward and test compatibility
        self.active_time_label = self.active_time_val_label
        self.today_idle_label = self.today_idle_val_label

        # Retain hidden widgets for test suite and backward compatibility
        self.today_total_label = QLabel(
            ActivityService.format_duration(self._cached_today_total_seconds)
        )
        self.today_total_label.setVisible(False)

        self.refresh_button = QPushButton("↻ Refresh")
        self.refresh_button.setVisible(False)
        self.refresh_button.clicked.connect(lambda: self.refresh(async_mode=True))

        self.attendance_button = QPushButton("Attendance →")
        self.attendance_button.setObjectName("AttendanceButton")
        self.attendance_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.attendance_button.setToolTip("View monthly attendance records and status")
        self.attendance_button.clicked.connect(self.attendance_requested.emit)
        self.weekly_timeline_button = self.attendance_button

        today_layout.addStretch(1)
        today_layout.addWidget(active_title)
        today_layout.addWidget(self.active_time_val_label)
        today_layout.addSpacing(6)
        today_layout.addWidget(self.attendance_button)
        today_layout.addStretch(1)

        today_group.setMinimumHeight(135)
        today_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        top_row.addWidget(today_group, stretch=1)

        # --------------------------------------------------------------
        # 2. Attendance (Start Time & Punch Time)
        # --------------------------------------------------------------
        attendance_group = QGroupBox("Attendance")
        attendance_layout = QVBoxLayout(attendance_group)
        attendance_layout.setContentsMargins(14, 12, 14, 12)
        attendance_layout.setSpacing(8)

        self.start_time_label = QLabel("Start Time: --:-- --")
        self.start_time_label.setObjectName("StatusLabel")

        self.punch_time_label = QLabel("Punch Time: Not Punched")
        self.punch_time_label.setObjectName("StatusLabel")

        attendance_layout.addStretch(1)
        attendance_layout.addWidget(self.start_time_label)
        attendance_layout.addSpacing(8)
        attendance_layout.addWidget(self.punch_time_label)
        attendance_layout.addStretch(1)

        attendance_group.setMinimumHeight(135)
        attendance_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        top_row.addWidget(attendance_group, stretch=1)

        # --------------------------------------------------------------
        # 3. Online & Sync Status
        # Contains: Online Status, Idle Time, Version, Records Uploaded,
        # Status, Last Successful Sync, and Start/Stop Tracking button
        # --------------------------------------------------------------
        status_group = QGroupBox("Online && Sync Status")
        status_grid = QGridLayout(status_group)
        status_grid.setContentsMargins(14, 12, 14, 12)
        status_grid.setHorizontalSpacing(18)
        status_grid.setVerticalSpacing(8)

        is_initially_active = getattr(self, "_is_tracking", False)

        # Network status indicator (Row 0, Col 0): ● Online or ● Offline
        self.network_status_label = QLabel("● Online")
        self.network_status_label.setObjectName("NetworkStatusLabel")
        self.network_status_label.setStyleSheet("color: #10b981; font-weight: 600; font-size: 13px;")

        # Retain tracking_status_label for error reporting and backward compatibility
        self.tracking_status_label = QLabel(f"Online: {'Active' if is_initially_active else 'Inactive'}")
        self.tracking_status_label.setObjectName("TrackingStatusLabel")
        self.tracking_status_label.setVisible(False)

        self.idle_time_label = QLabel("Idle Time: 0 seconds")
        self.idle_time_label.setObjectName("StatusLabel")

        self.unsynced_records_label = QLabel("Records uploading: 0")
        self.unsynced_records_label.setObjectName("StatusLabel")
        self.unsynced_records_label.setVisible(False)  # hidden from UI

        self.version_label = QLabel(f"Version: {get_running_app_version()}")
        self.version_label.setObjectName("StatusLabel")

        self.records_uploaded_label = QLabel("Records Uploaded: 0")
        self.records_uploaded_label.setObjectName("StatusLabel")

        self.update_status_label = QLabel("Status: Online")
        self.update_status_label.setObjectName("StatusLabel")
        self.update_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
        self.update_status_label.setVisible(False)  # Hidden to avoid duplicate network status line
        self.sync_status_label = self.update_status_label

        # Initial last successful sync timestamp
        from services.sync_service import SyncService
        init_sync_time = (
            SyncService.get_last_successful_sync_time()
            if hasattr(SyncService, "get_last_successful_sync_time")
            else SyncService.last_successful_sync_time
        )
        self.last_sync_label = QLabel(f"Last Successful Sync: {init_sync_time}")
        self.last_sync_label.setObjectName("StatusLabel")

        self.current_app_label = QLabel("Not tracking")
        self.current_app_label.setVisible(False)
        self.current_window_label = QLabel("")
        self.current_window_label.setVisible(False)

        # Single tracking button on Dashboard: [ Paused ] when running, [ Resume ] when paused
        initial_btn_text = "Paused" if is_initially_active else "Resume"
        self.tracking_toggle_button = QPushButton(initial_btn_text)
        self.tracking_toggle_button.setObjectName("TrackingToggleButton")
        self.tracking_toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tracking_toggle_button.clicked.connect(self._on_tracking_toggle_clicked)
        self.start_tracking_button = self.tracking_toggle_button
        self.stop_tracking_button = self.tracking_toggle_button
        self._apply_toggle_button_style(is_initially_active)

        # Layout: Row 0 – Network Status | Idle Time
        #         Row 1 – Version        | Records Uploaded
        #         Row 2 – Last Sync      (full width)
        #         Row 3 – Single Tracking Button (full width)
        status_grid.addWidget(self.network_status_label, 0, 0)
        status_grid.addWidget(self.idle_time_label, 0, 1)

        status_grid.addWidget(self.version_label, 1, 0)
        status_grid.addWidget(self.records_uploaded_label, 1, 1)

        status_grid.addWidget(self.last_sync_label, 2, 0, 1, 2)

        status_grid.addWidget(self.tracking_toggle_button, 3, 0, 1, 2)

        status_group.setMinimumHeight(140)
        status_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        top_row.addWidget(status_group, stretch=1)

        root.addLayout(top_row)

        # ==============================================================
        # 2. Below Top Row: Assigned Tasks (Full Width)
        # ==============================================================
        tasks_group = QGroupBox("Assigned Tasks")
        tasks_layout = QVBoxLayout(tasks_group)
        tasks_layout.setContentsMargins(12, 14, 12, 12)
        tasks_layout.setSpacing(0)

        self.task_table = AssignedTasksTable()
        tasks_layout.addWidget(self.task_table)

        root.addWidget(tasks_group)
        root.addStretch(1)

        # Retain table instances (hidden) for seamless data/test compatibility without rendering on Dashboard
        self.usage_table = ApplicationUsageTable()
        self.usage_table.setVisible(False)
        self.timeline_table = ActivityTimelineTable()
        self.timeline_table.setVisible(False)

    def _apply_toggle_button_style(self, is_active: bool) -> None:
        """Apply dynamic color and styling to single Paused/Resume tracking button."""
        if self._is_paused:
            self.tracking_toggle_button.setText("Resume")
            self.tracking_toggle_button.setStyleSheet(
                "QPushButton#TrackingToggleButton {"
                "    font-size: 12px; font-weight: 600; padding: 6px 14px; border-radius: 6px;"
                "    background-color: #0284c7; color: #ffffff; border: none;"
                "}"
                "QPushButton#TrackingToggleButton:hover {"
                "    background-color: #0369a1;"
                "}"
            )
        elif is_active:
            self.tracking_toggle_button.setText("Paused")
            self.tracking_toggle_button.setStyleSheet(
                "QPushButton#TrackingToggleButton {"
                "    font-size: 12px; font-weight: 600; padding: 6px 14px; border-radius: 6px;"
                "    background-color: #ef4444; color: #ffffff; border: none;"
                "}"
                "QPushButton#TrackingToggleButton:hover {"
                "    background-color: #dc2626;"
                "}"
            )
        else:
            self.tracking_toggle_button.setText("Resume")
            self.tracking_toggle_button.setStyleSheet(
                "QPushButton#TrackingToggleButton {"
                "    font-size: 12px; font-weight: 600; padding: 6px 14px; border-radius: 6px;"
                "    background-color: #0284c7; color: #ffffff; border: none;"
                "}"
                "QPushButton#TrackingToggleButton:hover {"
                "    background-color: #0369a1;"
                "}"
            )

    def set_network_status(self, is_online: bool) -> None:
        """Update the displayed network connectivity status."""
        self._is_network_online = bool(is_online)
        if is_online:
            self.network_status_label.setText("● Online")
            self.network_status_label.setStyleSheet("color: #10b981; font-weight: 600; font-size: 13px;")
            self.update_status_label.setText("Status: Online")
            self.update_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self.network_status_label.setText("● Offline")
            self.network_status_label.setStyleSheet("color: #ef4444; font-weight: 600; font-size: 13px;")
            self.update_status_label.setText("Status: Offline")
            self.update_status_label.setStyleSheet("color: #ef4444; font-weight: bold;")

    def _on_reachability_changed(self, is_online: bool) -> None:
        """Handle async network reachability changes from NetworkReachabilityMonitor."""
        try:
            QTimer.singleShot(0, lambda: self.set_network_status(is_online))
        except Exception:
            pass

    def _check_network_connectivity(self) -> None:
        """Dynamically check internet / network connectivity in a background thread."""
        import sys
        if "unittest" in sys.modules or "pytest" in sys.modules:
            return

        import threading
        from services.network_monitor import NetworkReachabilityMonitor

        def _worker():
            try:
                is_online = NetworkReachabilityMonitor().check_reachability(timeout=1.5)
                QTimer.singleShot(0, lambda: self.set_network_status(is_online))
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _shutdown(self) -> None:
        """Clean up background timers and persist active state on widget disposal."""
        try:
            from services.network_monitor import NetworkReachabilityMonitor
            NetworkReachabilityMonitor().unregister_listener(self._on_reachability_changed)
        except Exception:
            pass
        try:
            if hasattr(self, "_date_timer") and self._date_timer:
                self._date_timer.stop()
            if hasattr(self, "_network_timer") and self._network_timer:
                self._network_timer.stop()
            self._save_persisted_today_seconds(self._cached_today_total_seconds, self._cached_calendar_date)
        except Exception:
            pass

    def update_tracker_state(
        self,
        state: TrackerState,
    ) -> None:
        """Update the Current Application section, Online status, and Active Time."""

        if not state.is_tracking:
            self.current_app_label.setText(
                "Not tracking"
            )

            self.current_window_label.setText(
                ""
            )

        elif state.is_idle:
            self.current_app_label.setText(
                state.current_application or "Idle"
            )

            self.current_window_label.setText(
                state.current_window_title or ""
            )

        elif state.current_application:
            self.current_app_label.setText(
                state.current_application
            )

            self.current_window_label.setText(
                state.current_window_title or ""
            )

        else:
            self.current_app_label.setText(
                "Detecting..."
            )

            self.current_window_label.setText(
                ""
            )

        # Update Online status and dynamic toggle button
        self._is_tracking = bool(state.is_tracking)
        if self._is_paused:
            self.tracking_status_label.setText("Online: Paused")
        else:
            tracking_text = "Active" if state.is_tracking else "Inactive"
            self.tracking_status_label.setText(f"Online: {tracking_text}")
        self._apply_toggle_button_style(state.is_tracking)

        # Update idle time label in real time second by second
        idle_s = max(0, int(getattr(state, "idle_seconds", 0) or 0))
        if idle_s == 0 and self._cached_today_idle > 0:
            idle_s = self._cached_today_idle

        if idle_s < 60:
            self.idle_time_label.setText(f"Idle Time: {idle_s} seconds")
        else:
            self.idle_time_label.setText(f"Idle Time: {idle_s // 60} minutes {idle_s % 60} seconds")

        # Update sync info from SyncService
        from services.sync_service import SyncService
        # (Records uploading count is intentionally not displayed — see unsynced_records_label)
        sync_time_str = (
            SyncService.get_last_successful_sync_time()
            if hasattr(SyncService, "get_last_successful_sync_time")
            else SyncService.last_successful_sync_time
        )
        self.last_sync_label.setText(f"Last Successful Sync: {sync_time_str}")

        self.set_records_uploaded(self._cached_uploaded_count)

        # Check calendar date rollover: reset ONLY when a new calendar day begins
        self._check_date_rollover()

        # Continuous accumulation throughout the day:
        # If tracking is active and user is not idle, accumulate active tracked time
        if state.is_tracking and not state.is_idle:
            self._cached_today_total_seconds += 1
            self.active_time_val_label.setText(format_hh_mm_ss(self._cached_today_total_seconds))
            self.today_total_label.setText(ActivityService.format_duration(self._cached_today_total_seconds))
            # On every active tracking interval, update the saved value
            self._save_persisted_today_seconds(self._cached_today_total_seconds, self._cached_calendar_date)

    def set_records_uploaded(self, count: int) -> None:
        """Update the dynamic Records Uploaded count on the dashboard."""
        self.records_uploaded_label.setText(f"Records Uploaded: {count}")

    def set_tracking_active(self, active: bool) -> None:
        """Explicitly update the online tracking status label, button, and app indicators."""
        self._is_tracking = bool(active)
        if not active:
            self._is_paused = False
            try:
                from services.secure_session import SessionStore
                SessionStore().set_tracking_paused(False)
            except Exception:
                pass
        if self._is_paused:
            self.tracking_status_label.setText("Online: Paused")
        else:
            self.tracking_status_label.setText(f"Online: {'Active' if active else 'Inactive'}")
        self._apply_toggle_button_style(active)
        if not active:
            self.current_app_label.setText("Not tracking")
            self.current_window_label.setText("")
            # Save accumulated active time immediately upon stopping
            self._save_persisted_today_seconds(self._cached_today_total_seconds, self._cached_calendar_date)

    def refresh(self, async_mode: bool | None = None) -> None:
        """Reload today's total, applications, timeline, and uploaded records count."""
        if async_mode is None:
            import sys
            async_mode = not any("test" in arg.lower() or "unittest" in arg.lower() for arg in sys.argv)

        if not async_mode:
            try:
                self._check_date_rollover()
                total_seconds = self._service.get_today_total_seconds()
                if isinstance(total_seconds, (int, float)):
                    total_seconds = int(total_seconds)
                    self._cached_today_total_seconds = max(self._cached_today_total_seconds, total_seconds)
                    self.active_time_val_label.setText(format_hh_mm_ss(self._cached_today_total_seconds))
                    self.today_total_label.setText(ActivityService.format_duration(self._cached_today_total_seconds))
                    self._save_persisted_today_seconds(self._cached_today_total_seconds, self._cached_calendar_date)
            except Exception as err:
                logger.debug("Sync refresh total_seconds error: %s", err)

            try:
                uploaded_count = self._service.get_uploaded_records_count()
                self._cached_uploaded_count = uploaded_count
                self.set_records_uploaded(uploaded_count)
            except Exception as err:
                logger.debug("Sync refresh uploaded_count error: %s", err)

            try:
                today_idle = self._service.get_today_total_idle_seconds()
                self._cached_today_idle = today_idle
                self.today_idle_val_label.setText(format_hh_mm_ss(today_idle))
                if self.idle_time_label.text() == "Idle Time: 0 seconds" and today_idle > 0:
                    if today_idle < 60:
                        self.idle_time_label.setText(f"Idle Time: {today_idle} seconds")
                    else:
                        self.idle_time_label.setText(f"Idle Time: {today_idle // 60} minutes {today_idle % 60} seconds")
            except Exception as err:
                logger.debug("Sync refresh today_idle error: %s", err)

            try:
                timeline = self._service.get_today_timeline()
                self.usage_table.set_entries(timeline)
                self.timeline_table.set_entries(timeline)
            except Exception as err:
                logger.debug("Sync refresh timeline error: %s", err)

            try:
                tasks = TaskService().fetch_assigned_tasks(force=True)
                self.task_table.set_tasks(tasks)
            except Exception as err:
                logger.debug("Sync refresh tasks error: %s", err)

            try:
                AttendanceService().fetch_punch_time(force=True)
                att = AttendanceService().get_daily_attendance(self._cached_calendar_date.strftime("%Y-%m-%d"))
                self._update_attendance_ui(att)
            except Exception as err:
                logger.debug("Sync refresh attendance error: %s", err)

            try:
                from services.sync_service import SyncService
                sync_time_str = (
                    SyncService.get_last_successful_sync_time()
                    if hasattr(SyncService, "get_last_successful_sync_time")
                    else SyncService.last_successful_sync_time
                )
                self.last_sync_label.setText(f"Last Successful Sync: {sync_time_str}")
            except Exception as err:
                logger.debug("Sync refresh last_sync_label error: %s", err)
            return

        if getattr(self, "_is_refreshing", False):
            return
        self._is_refreshing = True

        def _bg_fetch():
            try:
                # Record the calendar date at the start of this fetch so that
                # _apply_dashboard_data can discard stale cross-midnight results.
                fetch_date = datetime.now().astimezone().date()
                total_seconds = self._service.get_today_total_seconds()
                uploaded_count = self._service.get_uploaded_records_count()
                today_idle = self._service.get_today_total_idle_seconds()
                timeline = self._service.get_today_timeline()
                try:
                    tasks = TaskService().fetch_assigned_tasks()
                except Exception as task_err:
                    logger.debug("Async fetch tasks error: %s", task_err)
                    tasks = []

                try:
                    AttendanceService().fetch_punch_time()
                    attendance = AttendanceService().get_daily_attendance()
                except Exception as att_err:
                    logger.debug("Async fetch attendance error: %s", att_err)
                    try:
                        attendance = AttendanceService().get_daily_attendance()
                    except Exception:
                        attendance = {}

                data = {
                    "total_seconds": total_seconds,
                    "uploaded_count": uploaded_count,
                    "today_idle": today_idle,
                    "timeline": timeline,
                    "tasks": tasks,
                    "task_error": TaskService().last_error,
                    "attendance": attendance,
                    # Tag with fetch date so _apply_dashboard_data can discard
                    # cross-midnight stale results that would carry yesterday's
                    # active time into today.
                    "fetch_date": fetch_date,
                }
                self.data_refreshed.emit(data)
            except Exception as err:
                logger.debug("Background dashboard refresh error: %s", err)
            finally:
                self._is_refreshing = False

        threading.Thread(target=_bg_fetch, name="DashboardRefreshWorker", daemon=True).start()

    def _apply_dashboard_data(self, data: dict) -> None:
        """Apply refreshed database statistics to dashboard widgets on the UI thread."""
        try:
            self._check_date_rollover()
            total_seconds = data.get("total_seconds", 0)
            if isinstance(total_seconds, (int, float)):
                total_seconds = int(total_seconds)
                # Guard: discard total_seconds from a background fetch that was
                # started on a different calendar day (cross-midnight race).
                # Without this, yesterday's accumulated time would flow into
                # today's counter via the max() comparison below.
                fetch_date = data.get("fetch_date")
                date_mismatch = (
                    fetch_date is not None
                    and fetch_date != self._cached_calendar_date
                )
                if date_mismatch:
                    logger.info(
                        "Discarding stale cross-midnight refresh data "
                        "(fetch_date=%s, current_date=%s, total_seconds=%d)",
                        fetch_date,
                        self._cached_calendar_date,
                        total_seconds,
                    )
                else:
                    self._cached_today_total_seconds = max(self._cached_today_total_seconds, total_seconds)
                    self.active_time_val_label.setText(format_hh_mm_ss(self._cached_today_total_seconds))
                    self.today_total_label.setText(ActivityService.format_duration(self._cached_today_total_seconds))
                    self._save_persisted_today_seconds(self._cached_today_total_seconds, self._cached_calendar_date)

            uploaded_count = data.get("uploaded_count", 0)
            self._cached_uploaded_count = uploaded_count
            self.set_records_uploaded(uploaded_count)

            today_idle = data.get("today_idle", 0)
            self._cached_today_idle = today_idle
            self.today_idle_val_label.setText(format_hh_mm_ss(today_idle))
            if self.idle_time_label.text() == "Idle Time: 0 seconds" and today_idle > 0:
                if today_idle < 60:
                    self.idle_time_label.setText(f"Idle Time: {today_idle} seconds")
                else:
                    self.idle_time_label.setText(f"Idle Time: {today_idle // 60} minutes {today_idle % 60} seconds")

            timeline = data.get("timeline", [])
            self.usage_table.set_entries(timeline)
            self.timeline_table.set_entries(timeline)

            tasks = data.get("tasks")
            if tasks is not None:
                self.task_table.set_tasks(tasks)
            elif data.get("task_error"):
                self.task_table.show_error(data.get("task_error"))

            attendance = data.get("attendance")
            if attendance:
                self._update_attendance_ui(attendance)

            from services.sync_service import SyncService
            sync_time_str = (
                SyncService.get_last_successful_sync_time()
                if hasattr(SyncService, "get_last_successful_sync_time")
                else SyncService.last_successful_sync_time
            )
            self.last_sync_label.setText(f"Last Successful Sync: {sync_time_str}")
        except Exception as err:
            logger.debug("Failed to apply refreshed dashboard data: %s", err)

    def set_version(self, version: str) -> None:
        """Dynamically update the displayed application version."""
        if version:
            v_str = str(version).strip()
            if not v_str.lower().startswith("version"):
                v_str = f"Version: {v_str}"
            self.version_label.setText(v_str)

    @staticmethod
    def _clean_status_text(raw_text: str) -> str:
        """Format raw technical errors/statuses into concise, user-friendly labels."""
        if not raw_text:
            return "Sync Successful"
        t = str(raw_text).strip()
        if t.startswith("Status:"):
            t = t[len("Status:"):].strip()

        t_lower = t.lower()
        # Check for raw Python / network exception patterns
        if any(exc in t_lower for exc in (
            "httpsconnectionpool", "httpconnectionpool", "connectionerror", "max retries",
            "failed to establish a new connection", "name resolution", "getaddrinfo",
            "network is unreachable", "connection refused", "connection reset", "socket",
            "urllib3", "requests.exceptions", "traceback", "winerror", "timeout", "timed out",
            "offline", "unreachable"
        )):
            return "Sync Pending"

        # Check for 5xx server errors
        if any(srv in t_lower for srv in ("500", "502", "503", "504", "bad gateway", "server busy")):
            return "Sync Pending"

        # Check for auth/permission patterns
        if any(auth in t_lower for auth in ("401", "unauthorized", "invalid key", "invalid token", "forbidden", "403", "auth failed", "device not recognized", "revoked")):
            return "Sync Error (Auth Failed)"

        # Strip prefixes
        for prefix in (
            "Activity upload batch failed: ",
            "Activity sync batch failed: ",
            "Activity sync failed: ",
            "Sync API fetch settings failed: ",
            "Pre-update flush failed: ",
        ):
            if t.startswith(prefix):
                t = t[len(prefix):].strip()
                break

        if len(t) > 30:
            return t[:27] + "..."
        return t

    def set_sync_status(self, status: str) -> None:
        """Update sync status if relevant, preserving dynamic network online/offline display."""
        if not status or status in ("Sync Successful", "Status: Sync Successful", "Sent", "Successful"):
            self.set_network_status(self._is_network_online)
            return

    def set_update_status(self, status: str) -> None:
        """Dynamically update the displayed device update verification status."""
        if not status:
            self.set_network_status(self._is_network_online)
            return
        s = str(status).strip()
        if not s.startswith("Status:"):
            display_text = f"Status: {s}"
        else:
            display_text = s

        self.update_status_label.setText(display_text)
        if "Successful" in s or "Updated" in s:
            self.update_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
        elif "Pending" in s:
            self.update_status_label.setStyleSheet("color: #f59e0b; font-weight: bold;")
        elif "Failed" in s or "Error" in s:
            self.update_status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
        else:
            self.update_status_label.setStyleSheet("")

    def _handle_global_error(self, error_type: str, error_message: str, context: dict) -> None:
        """Receive notification from ErrorReportService and queue GUI update via Qt signal."""
        try:
            self.error_reported.emit(str(error_type), str(error_message))
        except Exception:
            pass

    @Slot(str, str)
    def _on_error_reported(self, error_type: str, error_message: str) -> None:
        """Display short user-friendly error message in the existing dashboard status area."""
        try:
            err_upper = str(error_type).upper()
            msg_lower = str(error_message).lower()

            if any(k in err_upper for k in ("UPDATE", "INSTALL", "DOWNLOAD")):
                if any(net in msg_lower for net in ("connect", "timeout", "offline", "unreachable", "name resolution", "httpsconnectionpool")):
                    self.set_update_status("Update Pending (Offline)")
                else:
                    clean_msg = self._clean_status_text(error_message)
                    self.set_update_status(f"Update Error ({clean_msg})" if clean_msg else "Update Error")
            elif any(k in err_upper for k in ("TRACK", "IDLE", "PROVIDER", "PROCESS", "WINDOW")):
                clean_msg = self._clean_status_text(error_message)
                self.tracking_status_label.setText(f"Tracking: Error ({clean_msg})")
                self.tracking_status_label.setStyleSheet("color: #ef4444; font-weight: 500;")
        except Exception:
            pass