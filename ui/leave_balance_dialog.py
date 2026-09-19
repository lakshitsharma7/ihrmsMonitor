"""Leave Balance Modal Dialog for iHRMS Monitor.

Displays employee leave quota and current balance breakdown with
summary cards, status badges, dynamic API loading, and error handling.
"""

from __future__ import annotations

import threading
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
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


class LeaveSummaryCard(QFrame):
    """Modern, card-based summary widget representing a single leave quota type."""

    def __init__(self, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item = item or {}
        self.setObjectName("LeaveSummaryCard")
        self.setMinimumWidth(150)
        self.setMinimumHeight(155)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(6)

        # Card Base Style
        self.setStyleSheet(
            """
            QFrame#LeaveSummaryCard {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QFrame#LeaveSummaryCard:hover {
                border-color: #3B82F6;
                background-color: #FAFAFC;
            }
            """
        )

        # --------------------------------------------------------------
        # 1. Short Code Badge (e.g. "EC", "CL", "SL", "CO", "LT1")
        # --------------------------------------------------------------
        short_code = self._item.get("short_name")
        leave_name = self._item.get("leave_type") or "Unknown Leave Type"

        if not short_code or short_code == "—":
            # Derive dynamically if missing
            words = [w for w in leave_name.replace("/", " ").replace("-", " ").replace("(", " ").replace(")", " ").split() if w]
            if len(words) >= 3 and words[0].lower() == "leave" and words[1].lower() == "type":
                id_part = words[-1]
                short_code = f"LT{id_part}" if id_part.isdigit() else "".join(w[0].upper() for w in words if w[0].isalnum())[:4]
            elif len(words) > 1:
                short_code = "".join(w[0].upper() for w in words if w[0].isalnum())[:4]
            else:
                short_code = leave_name[:3].upper()

        code_container = QHBoxLayout()
        code_container.setContentsMargins(0, 0, 0, 0)
        code_container.setAlignment(Qt.AlignmentFlag.AlignCenter)

        code_badge = QLabel(short_code)
        code_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_badge.setStyleSheet(
            """
            QLabel {
                background-color: #EFF6FF;
                color: #2563EB;
                font-size: 13px;
                font-weight: 800;
                border: 1px solid #BFDBFE;
                border-radius: 6px;
                padding: 3px 12px;
            }
            """
        )
        code_container.addWidget(code_badge)
        layout.addLayout(code_container)

        # --------------------------------------------------------------
        # 2. Full Leave Type Name (Handles long names on 2 lines cleanly)
        # --------------------------------------------------------------
        self.name_label = QLabel(leave_name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMinimumHeight(34)
        self.name_label.setStyleSheet(
            "QLabel { font-size: 12px; font-weight: 700; color: #1E293B; border: none; background: transparent; }"
        )
        layout.addWidget(self.name_label)

        # --------------------------------------------------------------
        # 3. Horizontal Usage / Progress Indicator
        # --------------------------------------------------------------
        self.usage_bar = QProgressBar()
        self.usage_bar.setFixedHeight(4)
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #F1F5F9;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 2px;
            }
            """
        )
        try:
            total_num = float(self._item.get("total_quota") or 0.0)
            used_num = float(self._item.get("used") or 0.0)
            if total_num > 0:
                pct = int(min(100.0, max(0.0, (used_num / total_num) * 100.0)))
                self.usage_bar.setValue(pct)
            else:
                self.usage_bar.setValue(0)
        except (ValueError, TypeError, ZeroDivisionError):
            self.usage_bar.setValue(0)

        layout.addWidget(self.usage_bar)

        # --------------------------------------------------------------
        # 4. Divider Line
        # --------------------------------------------------------------
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #E2E8F0; border: none;")
        layout.addWidget(divider)

        # --------------------------------------------------------------
        # 5. Three-Column Stats: TOTAL (Blue) | USED (Red) | LEFT (Green)
        # --------------------------------------------------------------
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 4, 0, 2)
        stats_row.setSpacing(2)

        tot_val = self._item.get("total_quota_str") or (
            str(self._item.get("total_quota")) if self._item.get("total_quota") is not None else "—"
        )
        used_val = self._item.get("used_str") or (
            str(self._item.get("used")) if self._item.get("used") is not None else "—"
        )
        left_val = self._item.get("available_str") or (
            str(self._item.get("available")) if self._item.get("available") is not None else "—"
        )

        def _make_stat_col(value_str: str, label_str: str, color_hex: str) -> QVBoxLayout:
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setAlignment(Qt.AlignmentFlag.AlignCenter)

            val_lbl = QLabel(value_str)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(
                f"QLabel {{ font-size: 13px; font-weight: 800; color: {color_hex}; border: none; background: transparent; }}"
            )

            title_lbl = QLabel(label_str)
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_lbl.setStyleSheet(
                "QLabel { font-size: 10px; font-weight: 700; color: #64748B; text-transform: uppercase; border: none; background: transparent; }"
            )

            col.addWidget(val_lbl)
            col.addWidget(title_lbl)
            return col

        # Target Color Scheme: Total = Blue (#2563EB), Used = Red (#DC2626), Left = Green (#16A34A)
        stats_row.addLayout(_make_stat_col(tot_val, "Total", "#2563EB"), 1)
        stats_row.addLayout(_make_stat_col(used_val, "Used", "#DC2626"), 1)
        stats_row.addLayout(_make_stat_col(left_val, "Left", "#16A34A"), 1)

        layout.addLayout(stats_row)
        layout.addStretch(1)


class LeaveBalanceDialog(QDialog):
    """Modal dialog displaying leave quotas and balances in a modern card-based layout."""

    data_loaded = Signal(dict)

    def __init__(
        self,
        service: AttendanceService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LeaveBalanceDialog")
        self.setWindowTitle("Leave Balance")
        self.setModal(True)
        self.resize(880, 580)
        self.setMinimumSize(640, 440)

        self._service = service or AttendanceService()
        self._is_loading = False
        self._cards: list[LeaveSummaryCard] = []

        self.data_loaded.connect(self._apply_leave_data)
        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(14)

        # --------------------------------------------------------------
        # 1. Header with Title, Subtitle, Refresh, and Close (X)
        # --------------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_label = QLabel("Leave Balance")
        self.title_label.setObjectName("LeaveBalanceTitle")
        self.title_label.setStyleSheet("font-size: 19px; font-weight: 700; color: #0F172A;")

        self.subtitle_label = QLabel("Employee Leave Quotas & Remaining Entitlements")
        self.subtitle_label.setStyleSheet("font-size: 12px; color: #64748B;")

        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        header_layout.addLayout(title_col)

        header_layout.addStretch(1)

        # Refresh button in header
        self.refresh_btn = QPushButton("↻ Refresh")
        self.refresh_btn.setObjectName("SecondaryButton")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setFixedHeight(32)
        self.refresh_btn.clicked.connect(lambda: self.refresh(force=True))
        header_layout.addWidget(self.refresh_btn)

        # Close 'X' button
        self.close_x_btn = QPushButton("✕")
        self.close_x_btn.setObjectName("CloseXButton")
        self.close_x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_x_btn.setFixedSize(32, 32)
        self.close_x_btn.setStyleSheet(
            """
            QPushButton#CloseXButton {
                background-color: #F1F5F9;
                color: #475569;
                border: 1px solid #CBD5E1;
                border-radius: 16px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#CloseXButton:hover {
                background-color: #E2E8F0;
                color: #0F172A;
            }
            """
        )
        self.close_x_btn.clicked.connect(self.accept)
        header_layout.addWidget(self.close_x_btn)

        main_layout.addLayout(header_layout)

        # Loading Progress Bar & Label
        self.loading_container = QWidget()
        loading_layout = QVBoxLayout(self.loading_container)
        loading_layout.setContentsMargins(0, 0, 0, 0)
        loading_layout.setSpacing(4)

        self.loading_label = QLabel("Loading leave balance...")
        self.loading_label.setStyleSheet("color: #2563EB; font-size: 12px; font-weight: 600;")
        loading_layout.addWidget(self.loading_label)

        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setFixedHeight(3)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setStyleSheet("QProgressBar::chunk { background-color: #2563EB; }")
        loading_layout.addWidget(self.loading_bar)
        self.loading_container.setVisible(False)
        main_layout.addWidget(self.loading_container)

        # Error Banner
        self.error_container = QWidget()
        err_layout = QHBoxLayout(self.error_container)
        err_layout.setContentsMargins(12, 10, 12, 10)
        err_layout.setSpacing(10)
        self.error_container.setStyleSheet(
            "QWidget { background-color: #FEF2F2; border: 1px solid #FECACA; border-radius: 8px; }"
        )
        self.error_label = QLabel("Unable to load leave balance. Please try again.")
        self.error_label.setStyleSheet("color: #DC2626; font-size: 12px; font-weight: 500; border: none; background: transparent;")
        err_layout.addWidget(self.error_label, 1)

        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.setStyleSheet(
            "QPushButton { background: #DC2626; color: white; border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: 600; border: none; }"
            "QPushButton:hover { background: #B91C1C; }"
        )
        self.retry_btn.clicked.connect(lambda: self.refresh(force=True))
        err_layout.addWidget(self.retry_btn)
        self.error_container.setVisible(False)
        main_layout.addWidget(self.error_container)

        # --------------------------------------------------------------
        # 2. Summary Metric Cards
        # --------------------------------------------------------------
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        # Total Quota Card
        quota_card = QGroupBox("Total Allotted")
        quota_layout = QVBoxLayout(quota_card)
        quota_layout.setContentsMargins(14, 8, 14, 10)
        self.total_quota_val = QLabel("0 Days")
        self.total_quota_val.setStyleSheet("font-size: 19px; font-weight: 700; color: #2563EB;")
        quota_layout.addWidget(self.total_quota_val)
        stats_row.addWidget(quota_card)

        # Total Used Card
        used_card = QGroupBox("Total Availed / Used")
        used_layout = QVBoxLayout(used_card)
        used_layout.setContentsMargins(14, 8, 14, 10)
        self.total_used_val = QLabel("0 Days")
        self.total_used_val.setStyleSheet("font-size: 19px; font-weight: 700; color: #DC2626;")
        used_layout.addWidget(self.total_used_val)
        stats_row.addWidget(used_card)

        # Total Available Card
        avail_card = QGroupBox("Available Balance")
        avail_layout = QVBoxLayout(avail_card)
        avail_layout.setContentsMargins(14, 8, 14, 10)
        self.total_avail_val = QLabel("0 Days")
        self.total_avail_val.setStyleSheet("font-size: 19px; font-weight: 700; color: #16A34A;")
        avail_layout.addWidget(self.total_avail_val)
        stats_row.addWidget(avail_card)

        main_layout.addLayout(stats_row)

        # --------------------------------------------------------------
        # 3. Card-Based Leave Summary Section (Scrollable Grid)
        # --------------------------------------------------------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.cards_container = QWidget()
        self.cards_container.setObjectName("LeaveCardsContainer")
        self.cards_grid = QGridLayout(self.cards_container)
        self.cards_grid.setContentsMargins(2, 4, 2, 8)
        self.cards_grid.setSpacing(12)
        for col_i in range(4):
            self.cards_grid.setColumnStretch(col_i, 1)

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, 1)

        # Empty State
        self.empty_state = QWidget()
        empty_l = QVBoxLayout(self.empty_state)
        empty_l.setContentsMargins(10, 30, 10, 30)
        empty_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label = QLabel("No leave balance data available.")
        self.empty_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #64748B;")
        empty_l.addWidget(self.empty_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setVisible(False)
        main_layout.addWidget(self.empty_state)

        # --------------------------------------------------------------
        # 4. Footer Bar
        # --------------------------------------------------------------
        footer = QHBoxLayout()
        self.status_hint = QLabel("Data synchronized from HRMS Leave API")
        self.status_hint.setStyleSheet("font-size: 11px; color: #94A3B8;")
        footer.addWidget(self.status_hint)

        footer.addStretch(1)

        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("SecondaryButton")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFixedSize(84, 32)
        self.close_btn.clicked.connect(self.accept)
        footer.addWidget(self.close_btn)

        main_layout.addLayout(footer)

    def refresh(self, async_mode: bool | None = None, force: bool = False) -> None:
        """Fetch leave quota dynamically."""
        if async_mode is None:
            import sys
            async_mode = not any("test" in arg.lower() or "unittest" in arg.lower() for arg in sys.argv)

        if not async_mode:
            try:
                data = self._service.get_leave_quota(force=force)
                self._apply_leave_data(data)
            except Exception as err:
                logger.warning("Synchronous leave quota fetch failed: %s", err)
                self._apply_leave_data({"error": str(err), "items": []})
            return

        if self._is_loading:
            return
        self._is_loading = True
        self.loading_container.setVisible(True)
        self.error_container.setVisible(False)

        def _bg_worker():
            try:
                res = self._service.get_leave_quota(force=force)
                self.data_loaded.emit(res)
            except Exception as ex:
                logger.warning("Background leave quota fetch failed: %s", ex)
                self.data_loaded.emit({"error": str(ex), "items": []})
            finally:
                self._is_loading = False

        t = threading.Thread(target=_bg_worker, daemon=True, name="LeaveQuotaFetchThread")
        t.start()

    def _apply_leave_data(self, data: dict) -> None:
        """Render fetched leave data dynamically into summary cards."""
        self.loading_container.setVisible(False)

        if not isinstance(data, dict):
            self._show_error("Unable to load leave balance. Please try again.")
            return

        err = data.get("error")
        if err:
            self._show_error("Unable to load leave balance. Please try again.")
            self.scroll_area.setVisible(False)
            self.empty_state.setVisible(True)
            return

        self.error_container.setVisible(False)

        summary = data.get("summary", {})
        tot_q = summary.get("total_quota_str", str(summary.get("total_quota", 0)))
        tot_u = summary.get("total_used_str", str(summary.get("total_used", 0)))
        tot_a = summary.get("total_available_str", str(summary.get("total_available", 0)))

        self.total_quota_val.setText(f"{tot_q} Days")
        self.total_used_val.setText(f"{tot_u} Days")
        self.total_avail_val.setText(f"{tot_a} Days")

        items = data.get("items", [])
        if not items:
            self.scroll_area.setVisible(False)
            self.empty_state.setVisible(True)
            return

        self.empty_state.setVisible(False)
        self.scroll_area.setVisible(True)

        # Clear existing cards
        while self.cards_grid.count():
            child = self.cards_grid.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        self._cards.clear()

        # Responsive column layout (4 columns per row on desktop)
        cols_per_row = 4
        for idx, item in enumerate(items):
            row_idx = idx // cols_per_row
            col_idx = idx % cols_per_row
            card = LeaveSummaryCard(item=item)
            self.cards_grid.addWidget(card, row_idx, col_idx)
            self._cards.append(card)

    def _show_error(self, message: str) -> None:
        """Display error banner with message."""
        self.error_label.setText(message)
        self.error_container.setVisible(True)
        self.loading_container.setVisible(False)


