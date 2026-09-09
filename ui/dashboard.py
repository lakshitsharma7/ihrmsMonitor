"""Dashboard page for the Activity Tracker application."""

from __future__ import annotations

from datetime import datetime
import threading
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
from tracker.activity_tracker import TrackerState
from ui.activity_table import (
    ActivityTimelineTable,
    ApplicationUsageTable,
)
from utils.logger import get_logger

logger = get_logger(__name__)


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
        # scrolls instead of clipping the Activity Timeline off the bottom.
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

        root.setContentsMargins(14, 8, 14, 14)

        root.setSpacing(10)

        scroll.setWidget(content)

        page_layout.addWidget(scroll)

        # Top Row containing Current Application and Tracking & Sync Status
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # ==============================================================
        # Current Application
        # ==============================================================

        current_group = QGroupBox(
            "Current Application"
        )

        current_layout = QVBoxLayout(
            current_group
        )

        current_layout.setContentsMargins(
            12,
            10,
            12,
            10,
        )

        current_layout.setSpacing(4)

        self.current_app_label = QLabel(
            "Not tracking"
        )

        self.current_app_label.setObjectName(
            "CurrentAppName"
        )

        self.current_window_label = QLabel(
            ""
        )

        self.current_window_label.setObjectName(
            "CurrentWindowTitle"
        )

        current_layout.addWidget(
            self.current_app_label
        )

        current_layout.addWidget(
            self.current_window_label
        )

        self.current_window_label.setWordWrap(True)

        current_layout.addStretch()

        current_group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )

        top_row.addWidget(
            current_group,
            stretch=1,
        )

        # ==============================================================
        # Tracking & Sync Status
        # ==============================================================

        status_group = QGroupBox(
            "Tracking && Sync Status"
        )

        status_grid = QGridLayout(
            status_group
        )

        status_grid.setContentsMargins(
            12,
            10,
            12,
            10,
        )

        status_grid.setHorizontalSpacing(16)
        status_grid.setVerticalSpacing(4)

        self.tracking_status_label = QLabel(
            "Tracking: Inactive"
        )


        self.last_sync_label = QLabel(
            "Last successful sync: Never"
        )

        self.records_uploaded_label = QLabel(
            "Records Uploaded: 0"
        )

        self.unsynced_records_label = QLabel(
            "Records uploading: 0"
        )

        self.idle_time_label = QLabel(
            "Idle Time: 0 seconds"
        )

        self.version_label = QLabel(
            f"Version: {get_running_app_version()}"
        )

        self.update_status_label = QLabel(
            "Status: Updated"
        )
        self.sync_status_label = self.update_status_label

        # Give them StatusLabel object names
        self.tracking_status_label.setObjectName("StatusLabel")
        self.last_sync_label.setObjectName("StatusLabel")
        self.records_uploaded_label.setObjectName("StatusLabel")
        self.unsynced_records_label.setObjectName("StatusLabel")
        self.idle_time_label.setObjectName("StatusLabel")
        self.version_label.setObjectName("StatusLabel")
        self.update_status_label.setObjectName("StatusLabel")

        # Column 0
        status_grid.addWidget(self.tracking_status_label, 0, 0)
        status_grid.addWidget(self.records_uploaded_label, 1, 0)
        status_grid.addWidget(self.last_sync_label, 2, 0)

        # Column 1
        status_grid.addWidget(self.idle_time_label, 0, 1)
        status_grid.addWidget(self.unsynced_records_label, 1, 1)
        status_grid.addWidget(self.version_label, 2, 1)
        status_grid.addWidget(self.update_status_label, 3, 1)

        status_group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )

        top_row.addWidget(
            status_group,
            stretch=1,
        )

        root.addLayout(top_row)

        # ==============================================================
        # Today's Time + Applications
        # ==============================================================

        middle_row = QHBoxLayout()
        middle_row.setSpacing(10)

        # --------------------------------------------------------------
        # Today's Time
        # --------------------------------------------------------------

        today_group = QGroupBox(
            "Today's Time"
        )

        today_layout = QVBoxLayout(
            today_group
        )

        today_layout.setContentsMargins(
            12,
            10,
            12,
            10,
        )

        today_layout.setSpacing(6)

        self.today_total_label = QLabel(
            ActivityService.format_duration(self._cached_today_total_seconds)
        )

        self.today_total_label.setObjectName(
            "BigTimeLabel"
        )

        self.today_total_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.refresh_button = QPushButton(
            "↻ Refresh"
        )
        self.refresh_button.setObjectName(
            "RefreshButton"
        )
        self.refresh_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.refresh_button.setToolTip(
            "Refresh today's activity sessions and timeline"
        )
        self.refresh_button.clicked.connect(
            lambda: self.refresh(async_mode=True)
        )

        self.weekly_timeline_button = QPushButton(
            "Weekly Timeline →"
        )
        self.weekly_timeline_button.setObjectName(
            "WeeklyTimelineButton"
        )
        self.weekly_timeline_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.weekly_timeline_button.setToolTip(
            "View weekly active usage graph (Monday–Sunday)"
        )
        self.weekly_timeline_button.clicked.connect(
            self.weekly_timeline_requested.emit
        )

        today_layout.addStretch(1)
        today_layout.addWidget(
            self.today_total_label
        )
        today_layout.addSpacing(4)
        today_layout.addWidget(
            self.refresh_button
        )
        today_layout.addSpacing(4)
        today_layout.addWidget(
            self.weekly_timeline_button
        )
        today_layout.addStretch(1)

        today_group.setMinimumWidth(180)
        today_group.setMaximumWidth(210)

        middle_row.addWidget(
            today_group,
        )

        # --------------------------------------------------------------
        # Applications
        # --------------------------------------------------------------

        usage_group = QGroupBox(
            "Applications"
        )

        usage_layout = QVBoxLayout(
            usage_group
        )

        usage_layout.setContentsMargins(
            10,
            8,
            10,
            8,
        )
        usage_layout.setSpacing(0)

        self.usage_table = ApplicationUsageTable()

        usage_layout.addWidget(
            self.usage_table
        )

        middle_row.addWidget(
            usage_group,
            stretch=1,
        )

        root.addLayout(
            middle_row,
            stretch=1,
        )

        # ==============================================================
        # Activity Timeline
        # ==============================================================

        timeline_group = QGroupBox(
            "Activity Timeline"
        )

        timeline_layout = QVBoxLayout(
            timeline_group
        )

        timeline_layout.setContentsMargins(
            10,
            8,
            10,
            8,
        )

        timeline_layout.setSpacing(0)

        # IMPORTANT:
        # This is now a QTableWidget just like Applications.
        self.timeline_table = ActivityTimelineTable()

        timeline_layout.addWidget(
            self.timeline_table
        )

        root.addWidget(
            timeline_group,
            stretch=2,
        )

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
            self.today_total_label.setText(ActivityService.format_duration(0))

        # Continuous accumulation throughout the day:
        # If tracking is active and user is not idle, accumulate active tracked time
        if state.is_tracking and not state.is_idle:
            self._cached_today_total_seconds += 1
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
                data = {
                    "total_seconds": total_seconds,
                    "uploaded_count": uploaded_count,
                    "today_idle": today_idle,
                    "timeline": timeline,
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

                self.today_total_label.setText(ActivityService.format_duration(self._cached_today_total_seconds))
                self._save_persisted_today_seconds(self._cached_today_total_seconds, self._cached_calendar_date)

            uploaded_count = data.get("uploaded_count", 0)
            self._cached_uploaded_count = uploaded_count
            self.set_records_uploaded(uploaded_count)

            today_idle = data.get("today_idle", 0)
            self._cached_today_idle = today_idle
            if self.idle_time_label.text() == "Idle Time: 0 seconds" and today_idle > 0:
                if today_idle < 60:
                    self.idle_time_label.setText(f"Idle Time: {today_idle} seconds")
                else:
                    self.idle_time_label.setText(f"Idle Time: {today_idle // 60} minutes {today_idle % 60} seconds")

            timeline = data.get("timeline", [])
            self.usage_table.set_entries(timeline)
            self.timeline_table.set_entries(timeline)
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
            if len(short_msg) > 35:
                short_msg = short_msg[:32] + "..."

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