"""Dashboard page for the Activity Tracker application."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
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

        root = QVBoxLayout(self)

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

        root.addWidget(
            current_group
        )

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
            middle_row
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
            timeline_group
        )

        # ==============================================================
        # Refresh
        # ==============================================================

        actions_row = QHBoxLayout()

        actions_row.addStretch()

        self.refresh_button = QPushButton(
            "Refresh"
        )

        self.refresh_button.setObjectName(
            "SecondaryButton"
        )

        self.refresh_button.clicked.connect(
            self.refresh
        )

        actions_row.addWidget(
            self.refresh_button
        )

        root.addLayout(
            actions_row
        )

    def update_tracker_state(
        self,
        state: TrackerState,
    ) -> None:
        """Update the Current Application section."""

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