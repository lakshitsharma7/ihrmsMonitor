"""Table widgets for the Activity Tracker dashboard."""

from __future__ import annotations

from datetime import timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from services.activity_service import ActivityService, TimelineEntry


def format_local_time(dt) -> str:
    """Convert stored UTC datetime to local computer time."""

    if dt is None:
        return "-"

    # SQLite may return a naive datetime.
    # Treat naive timestamps as UTC because the application
    # stores activity timestamps in UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone().strftime("%H:%M")


class ApplicationUsageTable(QTableWidget):
    """
    Applications summary table.

    Each application appears only once.

    Columns:
        Time
        App
        Duration
        Subprocess
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setColumnCount(4)

        self.setHorizontalHeaderLabels(
            [
                "Time",
                "App",
                "Duration",
                "Subprocess",
            ]
        )

        header = self.horizontalHeader()

        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Stretch,
        )

        self.verticalHeader().setVisible(False)

        self.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )

        self.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )

        self.setAlternatingRowColors(True)

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.verticalHeader().setDefaultSectionSize(32)

        self.setMinimumHeight(165)

    def set_entries(
        self,
        entries: list[TimelineEntry],
    ) -> None:
        """Aggregate sessions and display one row per application."""
        self.setUpdatesEnabled(False)
        self.setRowCount(0)

        if not entries:
            self.setUpdatesEnabled(True)
            return

        applications: dict[str, dict] = {}

        for entry in entries:
            app_name = entry.application_name

            if app_name not in applications:
                applications[app_name] = {
                    "started_at": entry.started_at,
                    "duration_seconds": 0,
                    "window_title": entry.window_title,
                }

            app = applications[app_name]

            # Add every session duration.
            app["duration_seconds"] += (
                entry.duration_seconds
            )

            # Keep earliest time that application was used.
            if entry.started_at < app["started_at"]:
                app["started_at"] = entry.started_at

            # Keep a window title.
            if (
                not app["window_title"]
                and entry.window_title
            ):
                app["window_title"] = entry.window_title

        # Newest application first.
        grouped = sorted(
            applications.items(),
            key=lambda item: item[1]["started_at"],
            reverse=True,
        )

        for row, (app_name, data) in enumerate(grouped):
            self.insertRow(row)

            time_item = QTableWidgetItem(
                format_local_time(
                    data["started_at"]
                )
            )

            app_item = QTableWidgetItem(
                app_name
            )

            duration_item = QTableWidgetItem(
                ActivityService.format_duration(
                    data["duration_seconds"]
                )
            )

            subprocess_item = QTableWidgetItem(
                data["window_title"] or "-"
            )

            time_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            duration_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            self.setItem(
                row,
                0,
                time_item,
            )

            self.setItem(
                row,
                1,
                app_item,
            )

            self.setItem(
                row,
                2,
                duration_item,
            )

            self.setItem(
                row,
                3,
                subprocess_item,
            )

        self.resizeRowsToContents()
        self.setUpdatesEnabled(True)


class ActivityTimelineTable(QTableWidget):
    """
    Individual activity timeline.

    Every activity session gets one row.

    Columns:
        Time
        App
        Duration
        Subprocess
        PID
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setColumnCount(5)

        self.setHorizontalHeaderLabels(
            [
                "Time",
                "App",
                "Duration",
                "Subprocess",
                "PID",
            ]
        )

        header = self.horizontalHeader()

        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Stretch,
        )

        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        self.verticalHeader().setVisible(False)

        self.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )

        self.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )

        self.setAlternatingRowColors(True)

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.verticalHeader().setDefaultSectionSize(32)

        self.setMinimumHeight(180)

    def set_entries(
        self,
        entries: list[TimelineEntry],
    ) -> None:
        """Display every activity session, newest first."""
        self.setUpdatesEnabled(False)
        self.setRowCount(0)

        if not entries:
            self.setUpdatesEnabled(True)
            return

        # Latest activity first.
        entries = sorted(
            entries,
            key=lambda entry: entry.started_at,
            reverse=True,
        )

        for row, entry in enumerate(entries):
            self.insertRow(row)

            # ------------------------------------------------------
            # Time
            # ------------------------------------------------------

            time_item = QTableWidgetItem(
                format_local_time(
                    entry.started_at
                )
            )

            # ------------------------------------------------------
            # Application
            # ------------------------------------------------------

            app_item = QTableWidgetItem(
                entry.application_name
            )

            # ------------------------------------------------------
            # Duration
            # ------------------------------------------------------

            formatted_duration = ActivityService.format_duration(
                entry.duration_seconds
            )
            if getattr(entry, "idle_seconds", 0) > 0:
                idle_str = ActivityService.format_duration(entry.idle_seconds)
                dur_text = f"{formatted_duration} ({idle_str} idle)"
            else:
                dur_text = formatted_duration

            duration_item = QTableWidgetItem(
                dur_text
            )

            # ------------------------------------------------------
            # Subprocess / Window title
            # ------------------------------------------------------

            subprocess_item = QTableWidgetItem(
                entry.window_title or "-"
            )

            # ------------------------------------------------------
            # PID
            # ------------------------------------------------------

            pid_item = QTableWidgetItem(
                str(entry.process_id)
                if entry.process_id is not None
                else "-"
            )

            # ------------------------------------------------------
            # Alignment
            # ------------------------------------------------------

            time_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            duration_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            pid_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            # ------------------------------------------------------
            # Add cells
            # ------------------------------------------------------

            self.setItem(
                row,
                0,
                time_item,
            )

            self.setItem(
                row,
                1,
                app_item,
            )

            self.setItem(
                row,
                2,
                duration_item,
            )

            self.setItem(
                row,
                3,
                subprocess_item,
            )

            self.setItem(
                row,
                4,
                pid_item,
            )

        self.resizeRowsToContents()
        self.setUpdatesEnabled(True)