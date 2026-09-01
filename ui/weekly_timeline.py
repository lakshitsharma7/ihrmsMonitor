"""Weekly timeline view with Monday–Sunday bar chart and daily totals."""

from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.activity_service import ActivityService


class WeeklyBarChart(QWidget):
    """Custom vector-rendered bar chart displaying Monday through Sunday active time."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self._week_data: list[dict] = []
        self._hover_idx: int | None = None
        self.setMouseTracking(True)

    def set_data(self, week_data: list[dict]) -> None:
        """Update chart data and trigger repaint."""
        self._week_data = week_data
        self.update()

    def mouseMoveEvent(self, event) -> None:
        """Track hover over bars for interactive feedback."""
        pos = event.position()
        w = self.width()
        h = self.height()
        chart_top = 40.0
        chart_bottom = h - 55.0

        if not self._week_data or pos.y() < chart_top or pos.y() > chart_bottom:
            if self._hover_idx is not None:
                self._hover_idx = None
                self.update()
            return

        col_w = (w - 70.0) / len(self._week_data)
        col_idx = int((pos.x() - 50.0) / col_w)
        if 0 <= col_idx < len(self._week_data):
            if self._hover_idx != col_idx:
                self._hover_idx = col_idx
                self.update()
        elif self._hover_idx is not None:
            self._hover_idx = None
            self.update()

    def leaveEvent(self, event) -> None:
        if self._hover_idx is not None:
            self._hover_idx = None
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())

        # Background fill
        painter.fillRect(QRectF(0, 0, w, h), QColor("#ffffff"))

        if not self._week_data:
            painter.setPen(QColor("#70757a"))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "No weekly activity recorded yet.")
            return

        # Margins and boundaries
        margin_left = 55.0
        margin_right = 25.0
        margin_top = 42.0
        margin_bottom = 58.0

        chart_x = margin_left
        chart_y = margin_top
        chart_w = w - margin_left - margin_right
        chart_h = h - margin_top - margin_bottom

        # Determine scale: maximum hours (minimum 8 hours ceiling for standard work day)
        max_sec = max((d.get("total_seconds", 0) for d in self._week_data), default=0)
        max_hrs = max(8.0, (max_sec / 3600.0) * 1.25)
        # Round up max_hrs to nice multiple of 2
        max_hrs = max(8.0, float(int((max_hrs + 1.99) / 2) * 2))

        # Y-axis guide lines (e.g. 0h, 2h, 4h, 6h, 8h...)
        num_steps = 4
        guide_font = QFont("-apple-system, Segoe UI, sans-serif", 9)
        painter.setFont(guide_font)

        for i in range(num_steps + 1):
            step_val = (max_hrs / num_steps) * i
            y_pos = chart_y + chart_h - (chart_h * (step_val / max_hrs))

            # Draw dotted line
            grid_pen = QPen(QColor("#eceff1" if i > 0 else "#cfd8dc"))
            grid_pen.setStyle(Qt.PenStyle.DashLine if i > 0 else Qt.PenStyle.SolidLine)
            grid_pen.setWidthF(1.0)
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(chart_x, y_pos), QPointF(chart_x + chart_w, y_pos))

            # Y-axis label
            painter.setPen(QColor("#78909c"))
            lbl = f"{int(step_val)}h" if step_val == int(step_val) else f"{step_val:.1f}h"
            painter.drawText(
                QRectF(5.0, y_pos - 9.0, margin_left - 12.0, 18.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                lbl,
            )

        # Draw 7 day bars (Monday to Sunday)
        num_bars = len(self._week_data)
        col_w = chart_w / float(num_bars)
        bar_w = min(46.0, col_w * 0.55)

        for idx, day in enumerate(self._week_data):
            bx = chart_x + idx * col_w + (col_w - bar_w) / 2.0
            sec = day.get("total_seconds", 0)
            hrs = sec / 3600.0
            is_today = day.get("is_today", False)
            is_hover = (self._hover_idx == idx)

            bar_ratio = min(1.0, hrs / max_hrs) if max_hrs > 0 else 0.0
            bar_height = max(4.0, chart_h * bar_ratio) if sec > 0 else 3.0
            by = chart_y + chart_h - bar_height

            bar_rect = QRectF(bx, by, bar_w, bar_height)

            # Gradient and styling
            gradient = QLinearGradient(bx, by, bx, chart_y + chart_h)
            if is_today:
                if sec > 0:
                    gradient.setColorAt(0.0, QColor("#00a0c6"))
                    gradient.setColorAt(1.0, QColor("#007799"))
                else:
                    gradient.setColorAt(0.0, QColor("#80d8ea"))
                    gradient.setColorAt(1.0, QColor("#4dd0e1"))
            elif sec > 0:
                gradient.setColorAt(0.0, QColor("#1a73e8"))
                gradient.setColorAt(1.0, QColor("#1557b0"))
            else:
                gradient.setColorAt(0.0, QColor("#e0e0e0"))
                gradient.setColorAt(1.0, QColor("#eeeeee"))

            # Draw rounded bar (rounded at top)
            path = QPainterPath()
            corner_r = min(6.0, bar_w / 2.0)
            path.addRoundedRect(bar_rect, corner_r, corner_r)
            painter.fillPath(path, QBrush(gradient))

            # Hover outline or Today border
            if is_today:
                today_pen = QPen(QColor("#005b7f" if sec > 0 else "#00a0c6"), 2.0)
                painter.setPen(today_pen)
                painter.drawPath(path)
            elif is_hover:
                hover_pen = QPen(QColor("#174ea6"), 1.8)
                painter.setPen(hover_pen)
                painter.drawPath(path)

            # Value label on top of bar
            painter.setFont(QFont("-apple-system, Segoe UI, sans-serif", 9, QFont.Weight.Bold))
            val_text = day.get("formatted_time", "0m")
            # If bar is short, place label slightly above bar
            text_rect = QRectF(bx - 20.0, by - 24.0, bar_w + 40.0, 20.0)
            painter.setPen(QColor("#1a73e8" if not is_today else "#00838f") if sec > 0 else QColor("#9e9e9e"))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, val_text)

            # X-axis Day Name & Date labels
            name_y = chart_y + chart_h + 10.0
            painter.setFont(QFont("-apple-system, Segoe UI, sans-serif", 9, QFont.Weight.DemiBold if is_today else QFont.Weight.Normal))
            painter.setPen(QColor("#1a73e8" if is_today else "#202124"))
            day_text = day.get("short_day", "")
            painter.drawText(
                QRectF(chart_x + idx * col_w, name_y, col_w, 16.0),
                Qt.AlignmentFlag.AlignCenter,
                day_text,
            )

            # Date string (e.g. 01 Sep)
            date_y = name_y + 16.0
            painter.setFont(QFont("-apple-system, Segoe UI, sans-serif", 8))
            painter.setPen(QColor("#00a0c6" if is_today else "#5f6368"))
            painter.drawText(
                QRectF(chart_x + idx * col_w, date_y, col_w, 15.0),
                Qt.AlignmentFlag.AlignCenter,
                day.get("date_str", ""),
            )

            # "TODAY" marker badge under today's date
            if is_today:
                badge_w = 42.0
                badge_h = 13.0
                badge_x = chart_x + idx * col_w + (col_w - badge_w) / 2.0
                badge_y = date_y + 15.0
                badge_rect = QRectF(badge_x, badge_y, badge_w, badge_h)
                painter.setBrush(QBrush(QColor("#e0f7fa")))
                painter.setPen(QPen(QColor("#00838f"), 0.8))
                painter.drawRoundedRect(badge_rect, 6.5, 6.5)

                painter.setFont(QFont("-apple-system, Segoe UI, sans-serif", 7, QFont.Weight.Bold))
                painter.setPen(QColor("#006064"))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "TODAY")


class WeeklyTimelinePage(QWidget):
    """Full-page view dedicated to weekly tracking timeline and day-by-day analysis."""

    back_requested = Signal()

    def __init__(self, activity_service: ActivityService, parent=None) -> None:
        super().__init__(parent)
        self._service = activity_service
        self._build_ui()

    def _build_ui(self) -> None:
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # Scroll area for clean display across all desktop screen sizes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(14, 12, 14, 16)
        root.setSpacing(12)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        # ==============================================================
        # Navigation & Header Bar
        # ==============================================================
        header_bar = QHBoxLayout()
        header_bar.setSpacing(12)

        self.back_button = QPushButton("← Back to Dashboard")
        self.back_button.setObjectName("SecondaryButton")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.setMinimumHeight(34)
        self.back_button.clicked.connect(self.back_requested.emit)
        header_bar.addWidget(self.back_button)

        header_title_layout = QVBoxLayout()
        self.title_label = QLabel("Weekly Timeline")
        self.title_label.setObjectName("WeeklyTimelineTitle")
        self.title_label.setStyleSheet("font-size: 19px; font-weight: 700; color: #1a1a1a;")

        self.week_range_label = QLabel("Current Week (Monday – Sunday)")
        self.week_range_label.setStyleSheet("font-size: 12px; color: #5f6368;")

        header_title_layout.addWidget(self.title_label)
        header_title_layout.addWidget(self.week_range_label)
        header_bar.addLayout(header_title_layout)

        header_bar.addStretch(1)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("SecondaryButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.setMinimumHeight(34)
        self.refresh_button.clicked.connect(self.refresh)
        header_bar.addWidget(self.refresh_button)

        root.addLayout(header_bar)

        # ==============================================================
        # Summary Statistics Cards
        # ==============================================================
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)

        # Total Week Time Card
        total_card = QGroupBox("Total Week Active Time")
        total_layout = QVBoxLayout(total_card)
        total_layout.setContentsMargins(12, 8, 12, 10)
        self.total_week_label = QLabel("0h 0m")
        self.total_week_label.setObjectName("WeeklyStatBig")
        self.total_week_label.setStyleSheet("font-size: 22px; font-weight: 700; color: #1a73e8;")
        total_layout.addWidget(self.total_week_label)
        stats_row.addWidget(total_card)

        # Daily Average Card
        avg_card = QGroupBox("Daily Average")
        avg_layout = QVBoxLayout(avg_card)
        avg_layout.setContentsMargins(12, 8, 12, 10)
        self.daily_avg_label = QLabel("0h 0m")
        self.daily_avg_label.setObjectName("WeeklyStatBig")
        self.daily_avg_label.setStyleSheet("font-size: 22px; font-weight: 700; color: #00a0c6;")
        avg_layout.addWidget(self.daily_avg_label)
        stats_row.addWidget(avg_card)

        # Active Days Card
        active_days_card = QGroupBox("Active Days")
        active_days_layout = QVBoxLayout(active_days_card)
        active_days_layout.setContentsMargins(12, 8, 12, 10)
        self.active_days_label = QLabel("0 / 7 Days")
        self.active_days_label.setObjectName("WeeklyStatBig")
        self.active_days_label.setStyleSheet("font-size: 22px; font-weight: 700; color: #34a853;")
        active_days_layout.addWidget(self.active_days_label)
        stats_row.addWidget(active_days_card)

        root.addLayout(stats_row)

        # ==============================================================
        # Weekly Bar Chart Card
        # ==============================================================
        chart_group = QGroupBox("Weekly Activity Overview (Monday – Sunday)")
        chart_layout = QVBoxLayout(chart_group)
        chart_layout.setContentsMargins(10, 10, 10, 10)

        self.chart = WeeklyBarChart()
        chart_layout.addWidget(self.chart)

        root.addWidget(chart_group)

        # ==============================================================
        # Day-by-Day Breakdown
        # ==============================================================
        breakdown_group = QGroupBox("Daily Active Hours Breakdown")
        self.breakdown_layout = QVBoxLayout(breakdown_group)
        self.breakdown_layout.setContentsMargins(12, 12, 12, 12)
        self.breakdown_layout.setSpacing(8)

        self._day_rows: list[QWidget] = []
        root.addWidget(breakdown_group)

        # Initial data load
        self.refresh()

    def refresh(self) -> None:
        """Reload weekly data from the activity service and update graph."""
        week_data = self._service.get_weekly_timeline_data()
        self.chart.set_data(week_data)

        # Update week range header text
        if week_data:
            first_day = week_data[0]
            last_day = week_data[-1]
            first_date = first_day["date_obj"]
            last_date = last_day["date_obj"]
            self.week_range_label.setText(
                f"Week of {first_day['day_name']}, {first_date.strftime('%d %b')} – "
                f"{last_day['day_name']}, {last_date.strftime('%d %b %Y')}"
            )

        # Compute totals & stats
        total_sec = sum(d["total_seconds"] for d in week_data)
        active_count = sum(1 for d in week_data if d["total_seconds"] > 0)
        avg_sec = total_sec // max(1, active_count) if active_count > 0 else 0

        self.total_week_label.setText(ActivityService.format_hours_minutes(total_sec))
        self.daily_avg_label.setText(ActivityService.format_hours_minutes(avg_sec))
        self.active_days_label.setText(f"{active_count} / 7 Days")

        # Clear existing daily breakdown rows
        for row in self._day_rows:
            row.deleteLater()
        self._day_rows.clear()

        # Re-populate day list rows in requested format:
        # "Example: Monday — 01 Sep — 7h 25m"
        for d in week_data:
            row_widget = QFrame()
            row_widget.setObjectName("WeeklyDayRow")
            is_today = d.get("is_today", False)
            sec = d.get("total_seconds", 0)

            # Styling for each row
            if is_today:
                row_widget.setStyleSheet(
                    "#WeeklyDayRow { background-color: #f0fbfc; border: 1.5px solid #80deea; border-radius: 6px; padding: 6px 12px; }"
                )
            else:
                row_widget.setStyleSheet(
                    "#WeeklyDayRow { background-color: #ffffff; border: 1px solid #e8eaed; border-radius: 6px; padding: 6px 12px; }"
                )

            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(8, 4, 8, 4)
            row_layout.setSpacing(12)

            # Formatted display line: e.g. "Monday — 01 Sep — 7h 25m"
            display_text = d.get("display_line", "")
            label = QLabel(display_text)
            label.setFont(QFont("-apple-system, Segoe UI, sans-serif", 10, QFont.Weight.DemiBold if is_today else QFont.Weight.Normal))
            label.setStyleSheet("color: #007c91;" if is_today else "color: #202124;")
            row_layout.addWidget(label, stretch=2)

            # Visual progress indicator of 8h standard target
            progress = QProgressBar()
            progress.setRange(0, 8 * 3600)
            progress.setValue(min(8 * 3600, sec))
            progress.setTextVisible(False)
            progress.setFixedHeight(8)
            progress.setMinimumWidth(100)
            if is_today:
                progress.setStyleSheet(
                    "QProgressBar { background-color: #e0f7fa; border: none; border-radius: 4px; } "
                    "QProgressBar::chunk { background-color: #00a0c6; border-radius: 4px; }"
                )
            elif sec > 0:
                progress.setStyleSheet(
                    "QProgressBar { background-color: #e8eaed; border: none; border-radius: 4px; } "
                    "QProgressBar::chunk { background-color: #1a73e8; border-radius: 4px; }"
                )
            else:
                progress.setStyleSheet(
                    "QProgressBar { background-color: #f1f3f4; border: none; border-radius: 4px; } "
                    "QProgressBar::chunk { background-color: #dadce0; border-radius: 4px; }"
                )
            row_layout.addWidget(progress, stretch=1)

            if is_today:
                today_badge = QLabel("TODAY")
                today_badge.setStyleSheet(
                    "background-color: #00a0c6; color: #ffffff; font-weight: 700; font-size: 10px; "
                    "padding: 2px 8px; border-radius: 9px;"
                )
                row_layout.addWidget(today_badge)

            self.breakdown_layout.addWidget(row_widget)
            self._day_rows.append(row_widget)
