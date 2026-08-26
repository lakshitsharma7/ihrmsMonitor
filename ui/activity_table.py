"""Table widgets for the Activity Tracker dashboard."""

from __future__ import annotations

from datetime import timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QApplication,
    QStyle,
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


def create_shield_pulse_icon(is_active: bool, size: int = 16) -> QPixmap:
    """Draw a professional Shield + Pulse tracking state icon next to/in table entries."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    # Color active (green) vs inactive/neutral (gray)
    if is_active:
        color = QColor("#137333")  # Positive green
    else:
        color = QColor("#5f6368")  # Neutral gray
        
    scale = size / 24.0
    
    # Shield Path
    path = QPainterPath()
    path.moveTo(4 * scale, 5 * scale)
    path.quadTo(12 * scale, 3 * scale, 20 * scale, 5 * scale)
    path.quadTo(20 * scale, 14 * scale, 12 * scale, 21 * scale)
    path.quadTo(4 * scale, 14 * scale, 4 * scale, 5 * scale)
    
    painter.setPen(QPen(color, 2 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    
    # Pulse Path
    pulse_path = QPainterPath()
    pulse_path.moveTo(7 * scale, 12 * scale)
    pulse_path.lineTo(9 * scale, 12 * scale)
    pulse_path.lineTo(11 * scale, 8 * scale)
    pulse_path.lineTo(13 * scale, 16 * scale)
    pulse_path.lineTo(15 * scale, 12 * scale)
    pulse_path.lineTo(17 * scale, 12 * scale)
    
    painter.setPen(QPen(color, 1.5 * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(pulse_path)
    
    painter.end()
    return pixmap


# Every dashboard row is a single line of this height. Window titles can be
# hundreds of characters long, so they are elided rather than wrapped: wrapped
# titles made rows grow to several lines, which pushed the rest of the
# dashboard out of view.
ROW_HEIGHT = 32


def configure_activity_table(
    table: QTableWidget,
    *,
    stretch_column: int,
    minimum_height: int,
) -> None:
    """Apply the shared look and behaviour of the dashboard tables."""

    header = table.horizontalHeader()

    for column in range(table.columnCount()):
        header.setSectionResizeMode(
            column,
            QHeaderView.ResizeMode.Stretch
            if column == stretch_column
            else QHeaderView.ResizeMode.ResizeToContents,
        )

    header.setHighlightSections(False)

    table.setWordWrap(False)

    table.setTextElideMode(
        Qt.TextElideMode.ElideRight
    )

    # Fixed row heights keep every row aligned with the header and make
    # repainting cheap on tables that are refreshed every few seconds.
    vertical_header = table.verticalHeader()

    vertical_header.setVisible(False)

    vertical_header.setSectionResizeMode(
        QHeaderView.ResizeMode.Fixed
    )

    vertical_header.setDefaultSectionSize(ROW_HEIGHT)

    table.setEditTriggers(
        QAbstractItemView.EditTrigger.NoEditTriggers
    )

    table.setSelectionMode(
        QAbstractItemView.SelectionMode.NoSelection
    )

    table.setFocusPolicy(
        Qt.FocusPolicy.NoFocus
    )

    table.setAlternatingRowColors(True)

    table.setCornerButtonEnabled(False)

    table.setVerticalScrollMode(
        QAbstractItemView.ScrollMode.ScrollPerPixel
    )

    table.setHorizontalScrollMode(
        QAbstractItemView.ScrollMode.ScrollPerPixel
    )

    table.verticalScrollBar().setSingleStep(ROW_HEIGHT // 2)
    table.horizontalScrollBar().setSingleStep(ROW_HEIGHT // 2)

    table.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )

    table.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )

    # No maximum height: the table grows with the window instead of clipping
    # its last row halfway.
    table.setMinimumHeight(minimum_height)

    table.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Expanding,
    )


class ApplicationUsageTable(QTableWidget):
    """
    Applications summary table.

    Each application appears only once.

    Columns:
        Time
        App
        Monitor
        Duration
        Subprocess
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setColumnCount(5)

        self.setHorizontalHeaderLabels(
            [
                "Time",
                "App",
                "Monitor",
                "Duration",
                "Subprocess",
            ]
        )

        configure_activity_table(
            self,
            stretch_column=4,
            minimum_height=150,
        )

    def set_entries(
        self,
        entries: list[TimelineEntry],
    ) -> None:
        """Aggregate sessions and display one row per application."""

        self.setRowCount(0)

        # Respect RBAC permissions: hide Monitor column if tracking is not permitted
        from services.session_service import SessionService
        session = SessionService().current_user
        if session and not session.tracking_permitted:
            self.setColumnHidden(2, True)
        else:
            self.setColumnHidden(2, False)

        if not entries:
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

        # Retrieve main window state to check if tracking is active
        main_win = None
        for widget in QApplication.topLevelWidgets():
            if widget.inherits("QMainWindow"):
                main_win = widget
                break
        tracking_is_active = main_win and hasattr(main_win, "_tracker") and main_win._tracker and main_win._tracker.is_tracking

        for row, (app_name, data) in enumerate(grouped):
            self.insertRow(row)

            time_item = QTableWidgetItem(
                format_local_time(
                    data["started_at"]
                )
            )

            # Keep existing application icons (e.g. Desktop/Monitor and Python) unchanged
            app_item = QTableWidgetItem(app_name)
            style = self.style()
            if "python" in app_name.lower():
                app_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            else:
                app_icon = style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            app_item.setIcon(app_icon)

            # Track/Monitor state icon (Active for first row if tracking is running, otherwise Inactive)
            is_active = (row == 0) and tracking_is_active
            monitor_item = QTableWidgetItem()
            monitor_item.setIcon(QIcon(create_shield_pulse_icon(is_active, 16)))

            duration_item = QTableWidgetItem(
                ActivityService.format_duration(
                    data["duration_seconds"]
                )
            )

            subprocess_item = QTableWidgetItem(
                data["window_title"] or "-"
            )

            subprocess_item.setToolTip(
                data["window_title"] or ""
            )

            app_item.setToolTip(app_name)

            time_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            monitor_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            duration_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            self.setItem(row, 0, time_item)
            self.setItem(row, 1, app_item)
            self.setItem(row, 2, monitor_item)
            self.setItem(row, 3, duration_item)
            self.setItem(row, 4, subprocess_item)


class ActivityTimelineTable(QTableWidget):
    """
    Individual activity timeline.

    Every activity session gets one row.

    Columns:
        Time
        App
        Monitor
        Duration
        Subprocess
        PID
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setColumnCount(6)

        self.setHorizontalHeaderLabels(
            [
                "Time",
                "App",
                "Monitor",
                "Duration",
                "Subprocess",
                "PID",
            ]
        )

        configure_activity_table(
            self,
            stretch_column=4,
            minimum_height=180,
        )

    def set_entries(
        self,
        entries: list[TimelineEntry],
    ) -> None:
        """Display every activity session, newest first."""

        self.setRowCount(0)

        # Respect RBAC permissions: hide Monitor column if tracking is not permitted
        from services.session_service import SessionService
        session = SessionService().current_user
        if session and not session.tracking_permitted:
            self.setColumnHidden(2, True)
        else:
            self.setColumnHidden(2, False)

        if not entries:
            return

        # Latest activity first.
        entries = sorted(
            entries,
            key=lambda entry: entry.started_at,
            reverse=True,
        )

        # Retrieve main window state to check if tracking is active
        main_win = None
        for widget in QApplication.topLevelWidgets():
            if widget.inherits("QMainWindow"):
                main_win = widget
                break
        tracking_is_active = main_win and hasattr(main_win, "_tracker") and main_win._tracker and main_win._tracker.is_tracking

        for row, entry in enumerate(entries):
            self.insertRow(row)

            time_item = QTableWidgetItem(
                format_local_time(
                    entry.started_at
                )
            )

            # Keep existing application icons (e.g. Desktop/Monitor and Python) unchanged
            app_item = QTableWidgetItem(entry.application_name)
            style = self.style()
            if "python" in entry.application_name.lower():
                app_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            else:
                app_icon = style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            app_item.setIcon(app_icon)

            # Track/Monitor state icon (Active for first row if tracking is running, otherwise Inactive)
            is_active = (row == 0) and tracking_is_active
            monitor_item = QTableWidgetItem()
            monitor_item.setIcon(QIcon(create_shield_pulse_icon(is_active, 16)))

            duration_item = QTableWidgetItem(
                ActivityService.format_duration(
                    entry.duration_seconds
                )
            )

            subprocess_item = QTableWidgetItem(
                entry.window_title or "-"
            )

            subprocess_item.setToolTip(
                entry.window_title or ""
            )

            app_item.setToolTip(entry.application_name)

            pid_item = QTableWidgetItem(
                str(entry.process_id)
                if entry.process_id is not None
                else "-"
            )

            time_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

            monitor_item.setTextAlignment(
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

            self.setItem(row, 0, time_item)
            self.setItem(row, 1, app_item)
            self.setItem(row, 2, monitor_item)
            self.setItem(row, 3, duration_item)
            self.setItem(row, 4, subprocess_item)
            self.setItem(row, 5, pid_item)