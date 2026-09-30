"""Attendance Page UI for iHRMS Monitor.

Displays a monthly calendar-based attendance view, summary statistics cards,
status pill badges, previous/next month navigation, and Leave Balance modal integration.
"""

from __future__ import annotations

import calendar
import threading
from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
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

from services.attendance_service import AttendanceService
from utils.logger import get_logger

logger = get_logger(__name__)

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class CalendarDayCard(QFrame):
    """Clean, responsive card representing a single calendar day."""

    clicked = Signal(dict)

    def __init__(
        self,
        day_data: dict | None = None,
        is_padding: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._day_data = day_data or {}
        self._is_padding = is_padding
        self.setObjectName("CalendarDayCard")
        self.setMinimumHeight(82)
        self.setMinimumWidth(75)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        if self._is_padding:
            # Faded padding cell outside the current month
            self.setStyleSheet(
                """
                QFrame#CalendarDayCard {
                    background-color: #F8FAFC;
                    border: 1px dashed #E2E8F0;
                    border-radius: 8px;
                }
                """
            )
            lbl = QLabel("")
            layout.addWidget(lbl)
            return

        is_today = self._day_data.get("is_today", False)
        day_num = self._day_data.get("day_num", 0)
        date_str = self._day_data.get("date", "")
        day_name = self._day_data.get("day_name", "")
        status_label = self._day_data.get("status_label") or self._day_data.get("status_code") or "—"
        raw_code = str(self._day_data.get("status_code", "")).strip().upper()
        label_upper = status_label.strip().upper()
        details = self._day_data.get("details")

        # Determine semantic status category & full-card color theme
        if label_upper == "PRESENT" or raw_code in ("P", "PRESENT"):
            card_bg = "#F0FDF4"      # Full light green card
            card_border = "#86EFAC" if not is_today else "#16A34A"
            card_hover = "#DCFCE7"
            badge_bg = "#DCFCE7"
            badge_border = "#86EFAC"
            dow_color = "#166534"
            detail_color = "#0F172A"
            today_badge_bg = "#16A34A"
        elif label_upper == "ABSENT" or raw_code in ("A", "ABSENT"):
            card_bg = "#FEF2F2"      # Full light red card
            card_border = "#FECACA" if not is_today else "#DC2626"
            card_hover = "#FEE2E2"
            badge_bg = "#FEE2E2"
            badge_border = "#F87171"
            dow_color = "#991B1B"
            detail_color = "#0F172A"
            today_badge_bg = "#DC2626"
        elif "WEEK OFF" in label_upper or "WEEK OFF" in raw_code or raw_code in ("WO", "W/O"):
            card_bg = "#EFF6FF"      # Full light blue card
            card_border = "#BFDBFE" if not is_today else "#2563EB"
            card_hover = "#DBEAFE"
            badge_bg = "#DBEAFE"
            badge_border = "#93C5FD"
            dow_color = "#2563EB"
            detail_color = "#0F172A"
            today_badge_bg = "#2563EB"
        elif "HOLIDAY" in label_upper or "HOLIDAY" in raw_code or raw_code == "H":
            card_bg = "#FAF5FF"      # Full light purple card
            card_border = "#E9D5FF" if not is_today else "#9333EA"
            card_hover = "#F3E8FF"
            badge_bg = "#F3E8FF"
            badge_border = "#D8B4FE"
            dow_color = "#7E22CE"
            detail_color = "#0F172A"
            today_badge_bg = "#9333EA"
        elif "LEAVE" in label_upper or raw_code in ("EL", "CL", "SL", "PL", "ML", "LEAVE") or "LEAVE" in raw_code:
            card_bg = "#FFFBEB"      # Full light amber card
            card_border = "#FDE68A" if not is_today else "#D97706"
            card_hover = "#FEF3C7"
            badge_bg = "#FEF3C7"
            badge_border = "#FCD34D"
            dow_color = "#B45309"
            detail_color = "#0F172A"
            today_badge_bg = "#D97706"
        elif "COMP" in label_upper or "COMP" in raw_code:
            card_bg = "#ECFEFF"      # Full light cyan card
            card_border = "#A5F3FC" if not is_today else "#0891B2"
            card_hover = "#CFFAFE"
            badge_bg = "#CFFAFE"
            badge_border = "#67E8F9"
            dow_color = "#0E7490"
            detail_color = "#0F172A"
            today_badge_bg = "#0891B2"
        elif "HALF DAY" in label_upper or raw_code in ("HD", "HALF DAY"):
            card_bg = "#FEFCE8"      # Full light yellow card
            card_border = "#FEF08A" if not is_today else "#CA8A04"
            card_hover = "#FEF9C3"
            badge_bg = "#FEF9C3"
            badge_border = "#FDE047"
            dow_color = "#A16207"
            detail_color = "#0F172A"
            today_badge_bg = "#CA8A04"
        elif "LATE" in label_upper or raw_code == "LATE":
            card_bg = "#FFFBEB"      # Full light amber card
            card_border = "#FDE68A" if not is_today else "#B45309"
            card_hover = "#FEF3C7"
            badge_bg = "#FEF3C7"
            badge_border = "#FCD34D"
            dow_color = "#B45309"
            detail_color = "#0F172A"
            today_badge_bg = "#B45309"
        else:
            card_bg = "#FFFFFF"      # Neutral white card for future / unrecorded
            card_border = "#E2E8F0" if not is_today else "#3B82F6"
            card_hover = "#F8FAFC"
            badge_bg = "#F1F5F9"
            badge_border = "#CBD5E1"
            dow_color = "#64748B" if day_name not in ("Sat", "Sun") else "#2563EB"
            detail_color = "#0F172A"
            today_badge_bg = "#2563EB"

        # Apply Card Base Style
        border_width = "2px" if is_today else "1px"
        self.setStyleSheet(
            f"""
            QFrame#CalendarDayCard {{
                border: {border_width} solid {card_border};
                background-color: {card_bg};
                border-radius: 8px;
            }}
            QFrame#CalendarDayCard:hover {{
                border-color: {card_border};
                background-color: {card_hover};
            }}
            """
        )

        # --------------------------------------------------------------
        # Top Row: Day Number & Today Pill / Day Name
        # --------------------------------------------------------------
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        day_num_str = f"{day_num:02d}" if day_num > 0 else "—"
        self.num_label = QLabel(day_num_str)
        self.num_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #0F172A; border: none; background: transparent;"
        )
        top_row.addWidget(self.num_label)

        if day_name:
            dow_label = QLabel(day_name)
            dow_label.setStyleSheet(
                f"font-size: 11px; font-weight: 600; color: {dow_color}; border: none; background: transparent;"
            )
            top_row.addWidget(dow_label)

        top_row.addStretch(1)

        if is_today:
            today_badge = QLabel("Today")
            today_badge.setStyleSheet(
                f"background-color: {today_badge_bg}; color: white; font-size: 9px; font-weight: 700; "
                "border-radius: 4px; padding: 1px 4px; border: none;"
            )
            top_row.addWidget(today_badge)

        layout.addLayout(top_row)

        # --------------------------------------------------------------
        # Center: Status Pill Badge (Dark text and dot on light badge)
        # --------------------------------------------------------------
        status_container = QHBoxLayout()
        status_container.setContentsMargins(0, 2, 0, 2)
        status_container.setSpacing(0)

        badge_text = f"● {status_label}" if status_label != "—" else "—"
        self.status_badge = QLabel(badge_text)
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.status_badge.setMinimumHeight(24)

        badge_css = (
            f"QLabel {{ background-color: {badge_bg}; color: #000000; font-size: 11px; font-weight: 700; "
            f"border-radius: 5px; padding: 2px 4px; border: 1px solid {badge_border}; }}"
        )
        self.status_badge.setStyleSheet(badge_css)
        status_container.addWidget(self.status_badge)
        layout.addLayout(status_container)

        # --------------------------------------------------------------
        # Bottom: Secondary Details (Punch In/Out etc.)
        # --------------------------------------------------------------
        if details:
            detail_label = QLabel(str(details))
            detail_label.setStyleSheet(
                f"color: {detail_color}; font-size: 9px; font-weight: 600; border: none; background: transparent;"
            )
            detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)

        layout.addStretch(1)

        # Tooltip
        tooltip_lines = [f"Date: {date_str} ({day_name})", f"Status: {status_label}"]
        if details:
            tooltip_lines.append(f"Details: {details}")
        self.setToolTip("\n".join(tooltip_lines))

    def mousePressEvent(self, event) -> None:
        """Handle click on day card to open detail view."""
        if not self._is_padding and self._day_data:
            self.clicked.emit(self._day_data)
        super().mousePressEvent(event)


class AttendancePage(QWidget):
    """Monthly calendar-based attendance page."""

    back_requested = Signal()
    attendance_data_refreshed = Signal(dict)

    def __init__(self, service: AttendanceService | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AttendancePage")
        self._service = service or AttendanceService()
        self._is_refreshing = False
        self._day_cards: list[CalendarDayCard] = []

        self.attendance_data_refreshed.connect(self._apply_attendance_data)
        self._setup_ui()

    def _setup_ui(self) -> None:
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # Main Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("AttendanceContent")
        self.root_layout = QVBoxLayout(content)
        self.root_layout.setContentsMargins(16, 14, 16, 16)
        self.root_layout.setSpacing(14)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        # ==============================================================
        # 1. Navigation & Header Bar
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
        header_title_layout.setSpacing(2)
        self.title_label = QLabel("Attendance Records")
        self.title_label.setObjectName("AttendanceTitle")
        self.title_label.setStyleSheet("font-size: 19px; font-weight: 700; color: #0F172A;")

        self.subtitle_label = QLabel("Monthly Attendance Calendar & Status Breakdown")
        self.subtitle_label.setStyleSheet("font-size: 12px; color: #64748B;")

        header_title_layout.addWidget(self.title_label)
        header_title_layout.addWidget(self.subtitle_label)
        header_bar.addLayout(header_title_layout)

        header_bar.addStretch(1)

        # Leave Balance Button (Modal Popup Opener)
        self.leave_balance_button = QPushButton("Leave Balance")
        self.leave_balance_button.setObjectName("SecondaryButton")
        self.leave_balance_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.leave_balance_button.setMinimumHeight(34)
        self.leave_balance_button.setToolTip("View employee leave balance and quotas")
        self.leave_balance_button.clicked.connect(self._open_leave_balance_modal)
        header_bar.addWidget(self.leave_balance_button)

        self.root_layout.addLayout(header_bar)

        # Error Banner
        self.error_banner = QLabel("Unable to load attendance. Please try again.")
        self.error_banner.setObjectName("ErrorBanner")
        self.error_banner.setStyleSheet(
            "QLabel { background-color: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; border-radius: 6px; padding: 10px 14px; font-size: 13px; font-weight: 500; }"
        )
        self.error_banner.setVisible(False)
        self.root_layout.addWidget(self.error_banner)

        # ==============================================================
        # 2. Summary Statistics Cards
        # ==============================================================
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)

        # Present Card
        present_card = QGroupBox("Present Days")
        present_layout = QVBoxLayout(present_card)
        present_layout.setContentsMargins(12, 8, 12, 10)
        self.present_val_label = QLabel("0 Days")
        self.present_val_label.setObjectName("AttendanceStatPresent")
        self.present_val_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #16A34A;")
        present_layout.addWidget(self.present_val_label)
        stats_row.addWidget(present_card)

        # Absent Card
        absent_card = QGroupBox("Absent Days")
        absent_layout = QVBoxLayout(absent_card)
        absent_layout.setContentsMargins(12, 8, 12, 10)
        self.absent_val_label = QLabel("0 Days")
        self.absent_val_label.setObjectName("AttendanceStatAbsent")
        self.absent_val_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #DC2626;")
        absent_layout.addWidget(self.absent_val_label)
        stats_row.addWidget(absent_card)

        # Week Off Card
        weekoff_card = QGroupBox("Week Offs")
        weekoff_layout = QVBoxLayout(weekoff_card)
        weekoff_layout.setContentsMargins(12, 8, 12, 10)
        self.weekoff_val_label = QLabel("0 Days")
        self.weekoff_val_label.setObjectName("AttendanceStatWeekOff")
        self.weekoff_val_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #2563EB;")
        weekoff_layout.addWidget(self.weekoff_val_label)
        stats_row.addWidget(weekoff_card)

        # Leave / Holiday Card
        leave_card = QGroupBox("Leaves / Holidays")
        leave_layout = QVBoxLayout(leave_card)
        leave_layout.setContentsMargins(12, 8, 12, 10)
        self.leave_val_label = QLabel("0 Days")
        self.leave_val_label.setObjectName("AttendanceStatLeave")
        self.leave_val_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #D97706;")
        leave_layout.addWidget(self.leave_val_label)
        stats_row.addWidget(leave_card)

        # Total Days Card
        total_card = QGroupBox("Total Month Days")
        total_layout = QVBoxLayout(total_card)
        total_layout.setContentsMargins(12, 8, 12, 10)
        self.total_days_val_label = QLabel("0 Days")
        self.total_days_val_label.setObjectName("AttendanceStatTotal")
        self.total_days_val_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #475569;")
        total_layout.addWidget(self.total_days_val_label)
        stats_row.addWidget(total_card)

        self.root_layout.addLayout(stats_row)

        # ==============================================================
        # 3. Monthly Attendance Calendar Section
        # ==============================================================
        self.calendar_group = QGroupBox("Monthly Attendance Calendar")
        calendar_layout = QVBoxLayout(self.calendar_group)
        calendar_layout.setContentsMargins(12, 14, 12, 14)
        calendar_layout.setSpacing(10)

        # --- Month Navigation Toolbar ---
        nav_toolbar = QHBoxLayout()
        nav_toolbar.setSpacing(10)

        self.prev_month_btn = QPushButton("◀ Previous Month")
        self.prev_month_btn.setObjectName("SecondaryButton")
        self.prev_month_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_month_btn.setMinimumHeight(32)
        self.prev_month_btn.clicked.connect(self._on_prev_month)
        nav_toolbar.addWidget(self.prev_month_btn)

        self.today_btn = QPushButton("Today")
        self.today_btn.setObjectName("SecondaryButton")
        self.today_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.today_btn.setMinimumHeight(32)
        self.today_btn.clicked.connect(self._on_today)
        nav_toolbar.addWidget(self.today_btn)

        nav_toolbar.addStretch(1)

        now = datetime.now()
        # Month & Year Display Title
        self.month_year_display = QLabel(f"{MONTH_NAMES[now.month - 1]} {now.year}")
        self.month_year_display.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A;")
        nav_toolbar.addWidget(self.month_year_display)

        # Month Selector Combo
        self.month_combo = QComboBox()
        self.month_combo.setMinimumHeight(32)
        self.month_combo.setStyleSheet(
            "QComboBox { padding: 3px 8px; font-size: 13px; font-weight: 600; border: 1px solid #CBD5E1; border-radius: 6px; background: white; min-width: 105px; }"
        )
        nav_toolbar.addWidget(self.month_combo)

        # Year Selector Combo
        self.year_combo = QComboBox()
        self.year_combo.setMinimumHeight(32)
        self.year_combo.setStyleSheet(
            "QComboBox { padding: 3px 8px; font-size: 13px; font-weight: 600; border: 1px solid #CBD5E1; border-radius: 6px; background: white; min-width: 75px; }"
        )
        nav_toolbar.addWidget(self.year_combo)

        # Populate year and month combos dynamically (only past and current)
        self._populate_year_combo()
        self._populate_month_combo()

        self.month_combo.currentIndexChanged.connect(self._on_month_year_changed)
        self.year_combo.currentIndexChanged.connect(self._on_year_changed)

        calendar_layout.addLayout(nav_toolbar)

        # --- Weekday Headers ---
        weekdays_row = QHBoxLayout()
        weekdays_row.setSpacing(6)
        for dow in WEEKDAY_NAMES:
            hdr_lbl = QLabel(dow)
            hdr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr_lbl.setFixedHeight(30)
            dow_color = "#2563EB" if dow in ("Sat", "Sun") else "#475569"
            hdr_lbl.setStyleSheet(
                f"QLabel {{ background-color: #F8FAFC; color: {dow_color}; font-size: 12px; font-weight: 700; "
                f"border: 1px solid #E2E8F0; border-radius: 6px; }}"
            )
            weekdays_row.addWidget(hdr_lbl, 1)
        calendar_layout.addLayout(weekdays_row)

        # --- Calendar Days Grid Container ---
        self.calendar_grid_container = QWidget()
        self.calendar_grid_container.setMinimumWidth(560)
        self.calendar_grid = QGridLayout(self.calendar_grid_container)
        self.calendar_grid.setContentsMargins(0, 4, 0, 4)
        self.calendar_grid.setSpacing(6)
        for col_idx in range(7):
            self.calendar_grid.setColumnStretch(col_idx, 1)
        calendar_layout.addWidget(self.calendar_grid_container)

        # Empty State Widget
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(20, 40, 20, 40)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label = QLabel("No attendance records found.")
        self.empty_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #64748B;")
        empty_layout.addWidget(self.empty_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setVisible(False)
        calendar_layout.addWidget(self.empty_state)

        self.root_layout.addWidget(self.calendar_group)

        # Initial Load
        self.refresh()

    def _populate_year_combo(self) -> None:
        """Populate year selector with past years and current year only (no future years)."""
        now = datetime.now()
        current_year = now.year
        self.year_combo.blockSignals(True)
        self.year_combo.clear()
        for yr in range(current_year - 4, current_year + 1):
            self.year_combo.addItem(str(yr))
        self.year_combo.setCurrentText(str(current_year))
        self.year_combo.blockSignals(False)

    def _populate_month_combo(self, target_year: int | None = None, desired_month: str | None = None) -> None:
        """Populate month selector based on selected year:
        - Current year: only months up to current month (no future months).
        - Past year: all 12 months.
        - Future year: none.
        """
        now = datetime.now()
        if target_year is None:
            try:
                target_year = int(self.year_combo.currentText())
            except ValueError:
                target_year = now.year

        current_selection = desired_month or self.month_combo.currentText()
        if not current_selection and 1 <= now.month <= len(MONTH_NAMES):
            current_selection = MONTH_NAMES[now.month - 1]

        if target_year > now.year:
            available_months: list[str] = []
        elif target_year == now.year:
            available_months = MONTH_NAMES[:now.month]
        else:
            available_months = list(MONTH_NAMES)

        self.month_combo.blockSignals(True)
        self.month_combo.clear()
        for m in available_months:
            self.month_combo.addItem(m)

        if current_selection in available_months:
            self.month_combo.setCurrentText(current_selection)
        elif available_months:
            self.month_combo.setCurrentIndex(len(available_months) - 1)
        self.month_combo.blockSignals(False)

    def _on_year_changed(self) -> None:
        """Handle year selection change and update available months."""
        try:
            target_year = int(self.year_combo.currentText())
        except ValueError:
            target_year = datetime.now().year
        self._populate_month_combo(target_year=target_year)
        self._on_month_year_changed()

    def _on_month_year_changed(self) -> None:
        """Trigger refresh when user selects different month or year."""
        m_text = self.month_combo.currentText()
        y_text = self.year_combo.currentText()
        self.month_year_display.setText(f"{m_text} {y_text}")
        self.refresh()

    def _on_prev_month(self) -> None:
        """Navigate to previous month."""
        sel_month_name = self.month_combo.currentText()
        sel_month_num = MONTH_NAMES.index(sel_month_name) + 1 if sel_month_name in MONTH_NAMES else 1
        try:
            cur_y = int(self.year_combo.currentText())
        except ValueError:
            cur_y = datetime.now().year

        if sel_month_num == 1:
            new_m_name = MONTH_NAMES[11]
            new_y = cur_y - 1
            if self.year_combo.findText(str(new_y)) == -1:
                self.year_combo.insertItem(0, str(new_y))
            self.year_combo.blockSignals(True)
            self.year_combo.setCurrentText(str(new_y))
            self.year_combo.blockSignals(False)
            self._populate_month_combo(target_year=new_y, desired_month=new_m_name)
            self._on_month_year_changed()
        else:
            new_m_name = MONTH_NAMES[sel_month_num - 2]
            self.month_combo.setCurrentText(new_m_name)

    def _on_today(self) -> None:
        """Jump to current month and year."""
        now = datetime.now()
        self.year_combo.blockSignals(True)
        if self.year_combo.findText(str(now.year)) == -1:
            self.year_combo.addItem(str(now.year))
        self.year_combo.setCurrentText(str(now.year))
        self.year_combo.blockSignals(False)
        self._populate_month_combo(target_year=now.year, desired_month=MONTH_NAMES[now.month - 1])
        self._on_month_year_changed()

    def refresh(self, async_mode: bool | None = None, force: bool = False) -> None:
        """Reload monthly attendance data dynamically from backend API."""
        if async_mode is None:
            import sys
            async_mode = not any("test" in arg.lower() or "unittest" in arg.lower() for arg in sys.argv)

        selected_month = self.month_combo.currentText()
        selected_year = self.year_combo.currentText()
        self.month_year_display.setText(f"{selected_month} {selected_year}")

        if not async_mode:
            try:
                data = self._service.get_monthly_attendance_record(
                    month=selected_month,
                    year=selected_year,
                    force=force,
                )
                self._apply_attendance_data(data)
            except Exception as err:
                logger.warning("Synchronous attendance fetch failed: %s", err)
                self._show_error("Unable to load attendance. Please try again.")
            return

        if self._is_refreshing:
            return
        self._is_refreshing = True
        self.error_banner.setVisible(False)

        def _bg_fetch():
            try:
                data = self._service.get_monthly_attendance_record(
                    month=selected_month,
                    year=selected_year,
                    force=force,
                )
                self.attendance_data_refreshed.emit(data)
            except Exception as err:
                logger.warning("Background attendance fetch error: %s", err)
                self.attendance_data_refreshed.emit({"error": str(err), "days": []})
            finally:
                self._is_refreshing = False

        thread = threading.Thread(target=_bg_fetch, daemon=True, name="AttendanceFetchThread")
        thread.start()

    def _apply_attendance_data(self, data: dict) -> None:
        """Update UI with parsed attendance records."""
        if not isinstance(data, dict):
            self._show_error("Unable to load attendance. Please try again.")
            return

        err = data.get("error")
        if err:
            self._show_error("Unable to load attendance. Please try again.")
            self.empty_state.setVisible(True)
            self.calendar_grid_container.setVisible(False)
            return

        self.error_banner.setVisible(False)

        summary = data.get("summary", {})
        present_cnt = summary.get("present", 0)
        absent_cnt = summary.get("absent", 0)
        weekoff_cnt = summary.get("week_off", 0)
        leave_cnt = summary.get("leave", 0) + summary.get("holiday", 0)
        total_days = summary.get("total_days", 0)

        self.present_val_label.setText(f"{present_cnt} Days")
        self.absent_val_label.setText(f"{absent_cnt} Days")
        self.weekoff_val_label.setText(f"{weekoff_cnt} Days")
        self.leave_val_label.setText(f"{leave_cnt} Days")
        self.total_days_val_label.setText(f"{total_days} Days")

        days = data.get("days", [])
        if not days:
            self.empty_state.setVisible(True)
            self.calendar_grid_container.setVisible(False)
            return

        self.empty_state.setVisible(False)
        self.calendar_grid_container.setVisible(True)

        # Resolve month number & year for grid alignment
        month_name = data.get("month") or self.month_combo.currentText()
        try:
            month_num = MONTH_NAMES.index(month_name) + 1
        except ValueError:
            month_num = self.month_combo.currentIndex() + 1

        year_val = data.get("year") or self.year_combo.currentText()
        try:
            year_num = int(year_val)
        except ValueError:
            year_num = datetime.now().year

        self._populate_calendar(days, month_num, year_num)

    def _populate_calendar(self, days: list[dict], month_num: int, year_num: int) -> None:
        """Populate the 7-column calendar grid with CalendarDayCard widgets."""
        # Clear existing day cards from grid
        while self.calendar_grid.count():
            item = self.calendar_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._day_cards.clear()

        # Map day number -> day dict
        days_map: dict[int, dict] = {}
        for d in days:
            if isinstance(d, dict) and "day_num" in d:
                days_map[d["day_num"]] = d

        first_weekday, num_days_in_month = calendar.monthrange(year_num, month_num)
        # first_weekday is 0 (Monday) to 6 (Sunday)

        # 1. Leading Padding Cells (Preceding Days)
        for pad_col in range(first_weekday):
            pad_card = CalendarDayCard(is_padding=True)
            self.calendar_grid.addWidget(pad_card, 0, pad_col)

        # 2. Month Days (1..num_days_in_month)
        for day_idx in range(1, num_days_in_month + 1):
            slot_idx = first_weekday + (day_idx - 1)
            row_idx = slot_idx // 7
            col_idx = slot_idx % 7

            day_info = days_map.get(day_idx, {
                "day_num": day_idx,
                "date": f"{year_num}-{month_num:02d}-{day_idx:02d}",
                "day_name": WEEKDAY_NAMES[col_idx],
                "status_code": "—",
                "status_label": "—",
                "color": "#94A3B8",
                "bg_color": "#F1F5F9",
                "is_today": False,
            })

            day_card = CalendarDayCard(day_data=day_info)
            day_card.clicked.connect(self._show_day_detail)
            self.calendar_grid.addWidget(day_card, row_idx, col_idx)
            self._day_cards.append(day_card)

        # 3. Trailing Padding Cells to complete last row
        total_slots = first_weekday + num_days_in_month
        remaining_slots = (7 - (total_slots % 7)) % 7
        for pad_idx in range(remaining_slots):
            slot_idx = total_slots + pad_idx
            row_idx = slot_idx // 7
            col_idx = slot_idx % 7
            pad_card = CalendarDayCard(is_padding=True)
            self.calendar_grid.addWidget(pad_card, row_idx, col_idx)

    def _show_day_detail(self, day_info: dict) -> None:
        """Display details popup when user clicks on a calendar day."""
        details = day_info.get("details")
        date_str = day_info.get("date", "")
        day_name = day_info.get("day_name", "")
        status_label = day_info.get("status_label") or "—"
        status_color = day_info.get("color") or "#475569"
        status_bg = day_info.get("bg_color") or "#F1F5F9"

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Attendance Details - {date_str}")
        dlg.resize(380, 220)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(18, 16, 18, 16)
        dlg_layout.setSpacing(12)

        # Title
        title_lbl = QLabel(f"Attendance: {date_str} ({day_name})")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #0F172A;")
        dlg_layout.addWidget(title_lbl)

        # Status badge
        badge_lbl = QLabel(f" Status:  ● {status_label} ")
        badge_lbl.setStyleSheet(
            f"background-color: {status_bg}; color: {status_color}; "
            f"font-size: 13px; font-weight: 700; border-radius: 6px; padding: 6px 12px; border: 1px solid {status_color}33;"
        )
        dlg_layout.addWidget(badge_lbl)

        # Detailed breakdown
        if details:
            dtl_box = QGroupBox("Activity & Punch Records")
            dtl_l = QVBoxLayout(dtl_box)
            dtl_l.setContentsMargins(10, 8, 10, 8)
            dtl_lbl = QLabel(str(details))
            dtl_lbl.setStyleSheet("font-size: 12px; color: #334155; line-height: 1.4;")
            dtl_lbl.setWordWrap(True)
            dtl_l.addWidget(dtl_lbl)
            dlg_layout.addWidget(dtl_box)

        dlg_layout.addStretch(1)

        # Close button
        btn_close = QPushButton("Close")
        btn_close.setObjectName("SecondaryButton")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(dlg.accept)
        dlg_layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)

        dlg.exec()

    def _show_error(self, message: str) -> None:
        """Display a clean error banner."""
        self.error_banner.setText(message)
        self.error_banner.setVisible(True)

    def _open_leave_balance_modal(self) -> None:
        """Open modal dialog showing employee leave quota & balances."""
        try:
            from ui.leave_balance_dialog import LeaveBalanceDialog
            dialog = LeaveBalanceDialog(service=self._service, parent=self)
            dialog.exec()
        except Exception as err:
            logger.error("Failed to open leave balance dialog: %s", err)
