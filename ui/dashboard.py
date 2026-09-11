"""Dashboard page for the Activity Tracker application."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Any
from PySide6.QtCore import Qt, Signal, Slot
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
    s = str(time_val).strip()
    if not s or s.lower() in ("none", "null", "-", "00:00:00"):
        return None

    # Already contains AM/PM
    if "am" in s.lower() or "pm" in s.lower():
        return s

    # Full datetime string "YYYY-MM-DD HH:MM:SS"
    if len(s) >= 19 and s[4] == "-" and s[7] == "-":
        try:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%I:%M %p")
        except Exception:
            pass

    # Time string "HH:MM:SS" or "HH:MM"
    if ":" in s:
        parts = s.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
            dt = datetime(2000, 1, 1, hour, minute)
            return dt.strftime("%I:%M %p")
        except Exception:
            pass

    return s


def format_hh_mm_ss(total_seconds: Any) -> str:
    """Format total seconds strictly as HH:MM:SS format."""
    try:
        s = max(0, int(total_seconds or 0))
    except Exception:
        s = 0
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


class DashboardPage(QWidget):
    """Main Activity Tracker dashboard."""

    weekly_timeline_requested = Signal()
    data_refreshed = Signal(dict)
    error_reported = Signal(str, str)

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
        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            store.settings.setValue("dashboard/today_total_seconds", int(seconds))
            store.settings.setValue("dashboard/today_date", str(cal_date))
        except Exception:
            pass

    def _load_persisted_today_seconds(self, cal_date) -> int:
        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            saved_date = store.settings.value("dashboard/today_date")
            if saved_date and str(saved_date) == str(cal_date):
                val = store.settings.value("dashboard/today_total_seconds")
                return max(0, int(val)) if val is not None else 0
            return 0
        except Exception:
            return 0

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
        # Two equal side-by-side sections: Active Time and Idle Time (HH:MM:SS)
        # --------------------------------------------------------------
        today_group = QGroupBox("Today's Time")
        today_layout = QVBoxLayout(today_group)
        today_layout.setContentsMargins(14, 12, 14, 12)
        today_layout.setSpacing(6)

        times_row = QHBoxLayout()
        times_row.setSpacing(16)

        # Active Time Section (Left)
        active_layout = QVBoxLayout()
        active_layout.setSpacing(4)
        active_title = QLabel("Active Time")
        active_title.setObjectName("StatusLabel")
        active_title.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 500;")
        self.active_time_val_label = QLabel(
            format_hh_mm_ss(self._cached_today_total_seconds)
        )
        self.active_time_val_label.setObjectName("TimeValueLabel")
        self.active_time_val_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        active_layout.addWidget(active_title)
        active_layout.addWidget(self.active_time_val_label)
        times_row.addLayout(active_layout, stretch=1)

        # Idle Time Section (Right)
        idle_layout = QVBoxLayout()
        idle_layout.setSpacing(4)
        idle_title = QLabel("Idle Time")
        idle_title.setObjectName("StatusLabel")
        idle_title.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 500;")
        self.today_idle_val_label = QLabel(
            format_hh_mm_ss(self._cached_today_idle)
        )
        self.today_idle_val_label.setObjectName("TimeValueLabel")
        self.today_idle_val_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        idle_layout.addWidget(idle_title)
        idle_layout.addWidget(self.today_idle_val_label)
        times_row.addLayout(idle_layout, stretch=1)

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

        self.weekly_timeline_button = QPushButton("Weekly Timeline →")
        self.weekly_timeline_button.setObjectName("WeeklyTimelineButton")
        self.weekly_timeline_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.weekly_timeline_button.setToolTip("View weekly active usage graph (Monday–Sunday)")
        self.weekly_timeline_button.clicked.connect(self.weekly_timeline_requested.emit)

        today_layout.addStretch(1)
        today_layout.addLayout(times_row)
        today_layout.addSpacing(6)
        today_layout.addWidget(self.weekly_timeline_button)
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
        # 3. Tracking & Sync Status
        # Contains ONLY: Tracking, Idle Time, Records uploading,
        # Records Uploaded, Version, Status
        # --------------------------------------------------------------
        status_group = QGroupBox("Tracking && Sync Status")
        status_grid = QGridLayout(status_group)
        status_grid.setContentsMargins(14, 12, 14, 12)
        status_grid.setHorizontalSpacing(18)
        status_grid.setVerticalSpacing(8)

        self.tracking_status_label = QLabel("Tracking: Inactive")
        self.tracking_status_label.setObjectName("StatusLabel")

        self.idle_time_label = QLabel("Idle Time: 0 seconds")
        self.idle_time_label.setObjectName("StatusLabel")

        self.unsynced_records_label = QLabel("Records uploading: 0")
        self.unsynced_records_label.setObjectName("StatusLabel")

        self.version_label = QLabel(f"Version: {get_running_app_version()}")
        self.version_label.setObjectName("StatusLabel")

        self.records_uploaded_label = QLabel("Records Uploaded: 0")
        self.records_uploaded_label.setObjectName("StatusLabel")

        self.update_status_label = QLabel("Status: Updated")
        self.update_status_label.setObjectName("StatusLabel")
        self.sync_status_label = self.update_status_label

        # Retained internally for seamless background updates and test compatibility
        self.last_sync_label = QLabel("Last successful sync: Never")
        self.last_sync_label.setVisible(False)
        self.current_app_label = QLabel("Not tracking")
        self.current_app_label.setVisible(False)
        self.current_window_label = QLabel("")
        self.current_window_label.setVisible(False)

        # 6-item symmetrical grid (3 rows x 2 cols)
        status_grid.addWidget(self.tracking_status_label, 0, 0)
        status_grid.addWidget(self.idle_time_label, 0, 1)

        status_grid.addWidget(self.unsynced_records_label, 1, 0)
        status_grid.addWidget(self.version_label, 1, 1)

        status_grid.addWidget(self.records_uploaded_label, 2, 0)
        status_grid.addWidget(self.update_status_label, 2, 1)

        status_group.setMinimumHeight(135)
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
        tasks_layout.setContentsMargins(14, 12, 14, 12)
        tasks_layout.setSpacing(6)

        self.task_table = AssignedTasksTable()
        tasks_layout.addWidget(self.task_table)

        root.addWidget(tasks_group)
        root.addStretch(1)

        # Retain table instances (hidden) for seamless data/test compatibility without rendering on Dashboard
        self.usage_table = ApplicationUsageTable()
        self.usage_table.setVisible(False)
        self.timeline_table = ActivityTimelineTable()
        self.timeline_table.setVisible(False)

    def update_tracker_state(
        self,
        state: TrackerState,
    ) -> None:
        """Update the Current Application section and the Tracking & Sync Status."""

        if not state.is_tracking:
            self.current_app_label.setText(
                "Not tracking"
            )

            self.current_window_label.setText(
                ""
            )

        elif state.is_idle:
            self.current_app_label.setText(
                "Idle"
            )

            self.current_window_label.setText(
                ""
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

        # Update tracking status
        tracking_text = "Active" if state.is_tracking else "Inactive"
        self.tracking_status_label.setText(f"Tracking: {tracking_text}")

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
        self.unsynced_records_label.setText(f"Records uploading: {SyncService.records_currently_sending}")
        self.last_sync_label.setText(f"Last successful sync: {SyncService.last_successful_sync_time}")

        self.set_records_uploaded(self._cached_uploaded_count)

        # Check calendar date rollover: reset ONLY when a new calendar day begins
        current_date = datetime.now().astimezone().date()
        if current_date != self._cached_calendar_date:
            logger.info(
                "Calendar date rolled over from %s to %s. Resetting Today's Time counter.",
                self._cached_calendar_date,
                current_date,
            )
            self._cached_calendar_date = current_date
            self._cached_today_total_seconds = 0
            self._cached_today_idle = 0
            self._save_persisted_today_seconds(0, current_date)
            self.active_time_val_label.setText("00:00:00")
            self.today_idle_val_label.setText("00:00:00")
            self.today_total_label.setText(ActivityService.format_duration(0))
            try:
                att = AttendanceService().get_daily_attendance(current_date.strftime("%Y-%m-%d"))
                self._update_attendance_ui(att)
            except Exception:
                pass

        # Continuous accumulation throughout the day:
        # If tracking is active and user is not idle, accumulate active tracked time
        if state.is_tracking and not state.is_idle:
            self._cached_today_total_seconds += 1
            self.active_time_val_label.setText(format_hh_mm_ss(self._cached_today_total_seconds))
            self.today_total_label.setText(ActivityService.format_duration(self._cached_today_total_seconds))
            if self._cached_today_total_seconds % 5 == 0:
                self._save_persisted_today_seconds(self._cached_today_total_seconds, self._cached_calendar_date)

    def set_records_uploaded(self, count: int) -> None:
        """Update the dynamic Records Uploaded count on the dashboard."""
        self.records_uploaded_label.setText(f"Records Uploaded: {count}")

    def set_tracking_active(self, active: bool) -> None:
        """Explicitly update the tracking status label and app indicators."""
        self.tracking_status_label.setText(f"Tracking: {'Active' if active else 'Inactive'}")
        if not active:
            self.current_app_label.setText("Not tracking")
            self.current_window_label.setText("")

    def refresh(self, async_mode: bool | None = None) -> None:
        """Reload today's total, applications, timeline, and uploaded records count."""
        if async_mode is None:
            import sys
            async_mode = not any("test" in arg.lower() or "unittest" in arg.lower() for arg in sys.argv)

        if not async_mode:
            try:
                total_seconds = self._service.get_today_total_seconds()
                current_date = datetime.now().astimezone().date()
                if isinstance(total_seconds, (int, float)):
                    total_seconds = int(total_seconds)
                    if current_date != self._cached_calendar_date:
                        self._cached_calendar_date = current_date
                        self._cached_today_total_seconds = total_seconds
                    else:
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
            return

        if getattr(self, "_is_refreshing", False):
            return
        self._is_refreshing = True

        def _bg_fetch():
            try:
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
            total_seconds = data.get("total_seconds", 0)
            current_date = datetime.now().astimezone().date()
            if isinstance(total_seconds, (int, float)):
                total_seconds = int(total_seconds)
                if current_date != self._cached_calendar_date:
                    self._cached_calendar_date = current_date
                    self._cached_today_total_seconds = total_seconds
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
        except Exception as err:
            logger.debug("Failed to apply refreshed dashboard data: %s", err)

    def set_version(self, version: str) -> None:
        """Dynamically update the displayed application version."""
        if version:
            v_str = str(version).strip()
            if not v_str.lower().startswith("version"):
                v_str = f"Version: {v_str}"
            self.version_label.setText(v_str)

    def set_update_status(self, status: str) -> None:
        """Dynamically update the displayed device update verification status."""
        if status:
            self.update_status_label.setText(f"Status: {status}")
            if "Updated" in status:
                self.update_status_label.setStyleSheet("color: #10b981; font-weight: bold;")
            elif "Pending" in status:
                self.update_status_label.setStyleSheet("color: #f59e0b; font-weight: bold;")
            elif "Failed" in status:
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
            short_msg = str(error_message).strip()
            if "\n" in short_msg:
                short_msg = short_msg.split("\n")[0].strip()

            # Clean redundant prefixes so the actual root reason/HTTP code is visible
            for prefix in (
                "Activity upload batch failed: ",
                "Activity sync batch failed: ",
                "Activity sync failed: ",
                "Sync API fetch settings failed: ",
                "Pre-update flush failed: ",
            ):
                if short_msg.startswith(prefix):
                    short_msg = short_msg[len(prefix):].strip()
                    break

            if len(short_msg) > 60:
                short_msg = short_msg[:57] + "..."

            err_upper = str(error_type).upper()
            if any(k in err_upper for k in ("SYNC", "UPLOAD", "API", "NETWORK", "HTTP")):
                self.update_status_label.setText(f"Status: Sync Error ({short_msg})")
                self.update_status_label.setStyleSheet("color: #ef4444; font-weight: 500;")
            elif any(k in err_upper for k in ("UPDATE", "INSTALL", "DOWNLOAD")):
                self.update_status_label.setText(f"Status: Update Error ({short_msg})")
                self.update_status_label.setStyleSheet("color: #ef4444; font-weight: bold;")
            elif any(k in err_upper for k in ("TRACK", "IDLE", "PROVIDER", "PROCESS", "WINDOW")):
                self.tracking_status_label.setText(f"Tracking: Error ({short_msg})")
                self.tracking_status_label.setStyleSheet("color: #ef4444; font-weight: 500;")
            else:
                self.update_status_label.setText(f"Status: Issue ({short_msg})")
                self.update_status_label.setStyleSheet("color: #ef4444; font-weight: 500;")
        except Exception:
            pass