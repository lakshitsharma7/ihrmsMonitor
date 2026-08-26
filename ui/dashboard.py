"""Dashboard page for the Activity Tracker application."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.activity_service import ActivityService
from tracker.activity_tracker import TrackerState
from ui.activity_table import (
    ActivityTimelineTable,
    ApplicationUsageTable,
)


class DashboardPage(QWidget):
    """Main Activity Tracker dashboard."""

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

        root.setContentsMargins(12, 4, 12, 12)

        root.setSpacing(12)

        scroll.setWidget(content)

        page_layout.addWidget(scroll)

        # Top Row containing Current Application and Tracking & Sync Status
        top_row = QHBoxLayout()

        # ==============================================================
        # Current Application
        # ==============================================================

        current_group = QGroupBox(
            "Current Application"
        )

        current_layout = QVBoxLayout(
            current_group
        )

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

        # These cards only hold a few labels, so they should claim the height
        # they need and leave the rest of the window to the tables.
        current_group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
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

        status_layout = QVBoxLayout(
            status_group
        )

        self.tracking_status_label = QLabel(
            "Tracking: Inactive"
        )

        self.sync_status_label = QLabel(
            "API Sync: Sent"
        )

        self.last_sync_label = QLabel(
            "Last successful API sync: Never"
        )

        self.unsynced_records_label = QLabel(
            "Records uploading: 0"
        )

        self.idle_time_label = QLabel(
            "Idle Time: 0 seconds"
        )

        self.version_label = QLabel(
            "Version: 1.0.0"
        )

        # Give them StatusLabel object names
        self.tracking_status_label.setObjectName("StatusLabel")
        self.sync_status_label.setObjectName("StatusLabel")
        self.last_sync_label.setObjectName("StatusLabel")
        self.unsynced_records_label.setObjectName("StatusLabel")
        self.idle_time_label.setObjectName("StatusLabel")
        self.version_label.setObjectName("StatusLabel")

        status_layout.addWidget(self.tracking_status_label)
        status_layout.addWidget(self.sync_status_label)
        status_layout.addWidget(self.last_sync_label)
        status_layout.addWidget(self.unsynced_records_label)
        status_layout.addWidget(self.idle_time_label)
        status_layout.addWidget(self.version_label)

        status_group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
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

        # --------------------------------------------------------------
        # Today's Time
        # --------------------------------------------------------------

        today_group = QGroupBox(
            "Today's Time"
        )

        today_layout = QVBoxLayout(
            today_group
        )

        self.today_total_label = QLabel(
            "0m"
        )

        self.today_total_label.setObjectName(
            "BigTimeLabel"
        )

        self.today_total_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        today_layout.addWidget(
            self.today_total_label
        )

        middle_row.addWidget(
            today_group,
            stretch=1,
        )

        today_group.setMinimumWidth(220)

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

        self.usage_table = ApplicationUsageTable()

        usage_layout.addWidget(
            self.usage_table
        )

        middle_row.addWidget(
            usage_group,
            stretch=2,
        )

        root.addLayout(
            middle_row,
            stretch=2,
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
            stretch=3,
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

    def refresh(self) -> None:
        """Reload today's total, applications, and timeline."""

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