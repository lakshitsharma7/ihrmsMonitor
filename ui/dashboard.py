"""Dashboard page for the Activity Tracker application."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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


class DashboardPage(QWidget):
    """Main Activity Tracker dashboard."""

    weekly_timeline_requested = Signal()

    def __init__(
        self,
        activity_service: ActivityService,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._service = activity_service

        self._build_ui()

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

        self.sync_status_label = QLabel(
            "API Sync: Sent"
        )

        self.last_sync_label = QLabel(
            "Last successful API sync: Never"
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

        # Give them StatusLabel object names
        self.tracking_status_label.setObjectName("StatusLabel")
        self.sync_status_label.setObjectName("StatusLabel")
        self.last_sync_label.setObjectName("StatusLabel")
        self.records_uploaded_label.setObjectName("StatusLabel")
        self.unsynced_records_label.setObjectName("StatusLabel")
        self.idle_time_label.setObjectName("StatusLabel")
        self.version_label.setObjectName("StatusLabel")
        self.update_status_label.setObjectName("StatusLabel")

        # Column 0
        status_grid.addWidget(self.tracking_status_label, 0, 0)
        status_grid.addWidget(self.sync_status_label, 1, 0)
        status_grid.addWidget(self.last_sync_label, 2, 0)
        status_grid.addWidget(self.records_uploaded_label, 3, 0)

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
            "0m"
        )

        self.today_total_label.setObjectName(
            "BigTimeLabel"
        )

        self.today_total_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
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

        # Update idle time label (dynamic updates when idle resumes or resets)
        idle_s = int(state.idle_seconds)
        if idle_s < 60:
            self.idle_time_label.setText(f"Idle Time: {idle_s} seconds")
        else:
            self.idle_time_label.setText(f"Idle Time: {idle_s // 60} minutes {idle_s % 60} seconds")

        # Update sync info from SyncService
        from services.sync_service import SyncService
        self.sync_status_label.setText(f"API Sync: {SyncService.last_sync_status}")
        self.last_sync_label.setText(f"Last successful API sync: {SyncService.last_successful_sync_time}")
        self.unsynced_records_label.setText(f"Records uploading: {SyncService.records_currently_sending}")

        try:
            uploaded_count = self._service.get_uploaded_records_count()
            self.set_records_uploaded(uploaded_count)
        except Exception:
            pass

    def set_records_uploaded(self, count: int) -> None:
        """Update the dynamic Records Uploaded count on the dashboard."""
        self.records_uploaded_label.setText(f"Records Uploaded: {count}")

    def refresh(self) -> None:
        """Reload today's total, applications, timeline, and uploaded records count."""

        # ==============================================================
        # Today's total
        # ==============================================================

        total_seconds = (
            self._service.get_today_total_seconds()
        )

        self.today_total_label.setText(
            ActivityService.format_duration(
                total_seconds
            )
        )

        try:
            uploaded_count = self._service.get_uploaded_records_count()
            self.set_records_uploaded(uploaded_count)
        except Exception:
            pass

        # ==============================================================
        # Get today's activity sessions once
        # ==============================================================

        timeline = (
            self._service.get_today_timeline()
        )

        # ==============================================================
        # Applications
        #
        # One row per unique application.
        # Duration = total duration for that application.
        # ==============================================================

        self.usage_table.set_entries(
            timeline
        )

        # ==============================================================
        # Activity Timeline
        #
        # One row per individual activity session.
        # ==============================================================

        self.timeline_table.set_entries(
            timeline
        )

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