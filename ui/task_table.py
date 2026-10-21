"""Assigned Tasks and KRA / Timesheet table widget for the iHRMS Monitor Dashboard."""

from __future__ import annotations

from datetime import date, datetime
import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetrics, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from utils.logger import get_logger
from ui.additional_task_widget import (
    AdditionalTaskWidget,
    CenteredFlowLayout,
    LinedTaskTextEdit,
)

logger = get_logger(__name__)

TABLE_STYLESHEET = """
QTableWidget#AssignedTasksTable {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    gridline-color: #e2e8f0;
    font-size: 12px;
    color: #1e293b;
    outline: none;
}

QTableWidget#AssignedTasksTable::item {
    padding: 5px 6px;
    color: #1e293b;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
}

QTableWidget#AssignedTasksTable::item:last-child {
    border-right: none;
}

QTableWidget#AssignedTasksTable::item:alternate {
    background-color: #f8fafc;
}

QTableWidget#AssignedTasksTable::item:selected {
    background-color: #f1f5f9;
    color: #0f172a;
}

QTableWidget#AssignedTasksTable::item:hover {
    background-color: #f8fafc;
}

QHeaderView {
    background-color: #f8fafc;
    border: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

QHeaderView::section {
    background-color: #f8fafc;
    color: #334155;
    font-weight: 700;
    font-size: 11.5px;
    padding: 6px 4px;
    border-top: none;
    border-left: none;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1.5px solid #cbd5e1;
}

QHeaderView::section:last {
    border-right: none;
}

QTableCornerButton::section {
    background-color: #f8fafc;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1.5px solid #cbd5e1;
}

QTableWidget#AssignedTasksTable QScrollBar:horizontal {
    height: 0px;
    width: 0px;
    border: none;
    background: transparent;
}

QTableWidget#AssignedTasksTable QScrollBar::handle:horizontal {
    min-width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}

QTableWidget#AssignedTasksTable QScrollBar::add-line:horizontal,
QTableWidget#AssignedTasksTable QScrollBar::sub-line:horizontal {
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    width: 8px;
    background: #f1f5f9;
    border-radius: 4px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 24px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
"""



_LE_NORMAL = (
    "QLineEdit {"
    "  background-color: #ffffff;"
    "  border: 1px solid #cbd5e1;"
    "  border-radius: 6px;"
    "  padding: 3px 5px;"
    "  font-size: 12px;"
    "  font-weight: 500;"
    "  color: #1e293b;"
    "}"
    "QLineEdit:hover {"
    "  border: 1px solid #94a3b8;"
    "}"
    "QLineEdit:focus {"
    "  border: 1.5px solid #1a73e8;"
    "  background-color: #ffffff;"
    "}"
)

_LE_ERROR = (
    "QLineEdit {"
    "  background-color: #fef2f2;"
    "  border: 1.5px solid #ef4444;"
    "  border-radius: 6px;"
    "  padding: 3px 5px;"
    "  font-size: 12px;"
    "  color: #991b1b;"
    "}"
)

_LE_READONLY = (
    "QLineEdit {"
    "  background-color: transparent;"
    "  border: none;"
    "  border-radius: 0px;"
    "  padding: 4px 6px;"
    "  font-size: 12px;"
    "  font-weight: 500;"
    "  color: #1e293b;"
    "  selection-background-color: #cbd5e1;"
    "  selection-color: #0f172a;"
    "}"
    "QLineEdit:focus {"
    "  border: none;"
    "  background-color: transparent;"
    "}"
)


class StableLineEdit(QLineEdit):
    """QLineEdit that guarantees parent table horizontal scroll remains stable during typing/focus."""

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        table: Optional[QTableWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self._table = table

    def focusInEvent(self, event) -> None:
        prev_h = (
            self._table.horizontalScrollBar().value()
            if self._table
            else None
        )
        super().focusInEvent(event)
        if self._table and hasattr(self._table, "_handle_line_edit_focused"):
            self._table._handle_line_edit_focused(self)
        if prev_h is not None and self._table.horizontalScrollBar().value() != prev_h:
            self._table.horizontalScrollBar().setValue(prev_h)

    def keyPressEvent(self, event) -> None:
        prev_h = (
            self._table.horizontalScrollBar().value()
            if self._table
            else None
        )
        super().keyPressEvent(event)
        if prev_h is not None and self._table.horizontalScrollBar().value() != prev_h:
            self._table.horizontalScrollBar().setValue(prev_h)


def format_task_date(raw_date: Any) -> str:
    """Format raw date into 'DD Month YYYY' format (e.g. '01 October 2026')."""
    if raw_date is None:
        return ""
    cleaned = str(raw_date).strip()
    if not cleaned or cleaned.lower() in ("none", "null", "n/a", "undefined", "-"):
        return ""

    if isinstance(raw_date, datetime):
        return raw_date.strftime("%d %B %Y")
    if hasattr(raw_date, "strftime"):
        return raw_date.strftime("%d %B %Y")

    cleaned = str(raw_date).strip()
    try:
        dt = datetime.strptime(cleaned, "%d %B %Y")
        return dt.strftime("%d %B %Y")
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%d-%b-%Y",
        "%d %b %Y",
    ):
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%d %B %Y")
        except ValueError:
            pass

    if len(cleaned) >= 10:
        try:
            dt = datetime.strptime(cleaned[:10], "%Y-%m-%d")
            return dt.strftime("%d %B %Y")
        except ValueError:
            pass

    return cleaned


def _extract_task_done(task: Optional[Dict[str, Any]]) -> str:
    """
    Safely extract task done / progress value from task dict.
    Preserves valid numeric values including 0, 0.00, decimals, and numeric strings.
    Returns '-' only when no usable value is present.
    """
    if not isinstance(task, dict):
        return "-"
    for key in (
        "task_done",
        "task_done_till_now",
        "taskDoneTillNow",
        "taskDone",
        "done_till_now",
        "task_progress",
        "progress",
        "hours_done",
        "total_done",
        "_initial_done_str",
    ):
        val = task.get(key)
        if val is not None:
            s = str(val).strip()
            if s and s not in ("None", "null", "-"):
                return s
    return "-"


class TaskTableSignals(QObject):
    """Qt signals for asynchronous timesheet submit/save operations."""

    submit_success = Signal(int, str, dict)  # row_idx, message, payload_data
    submit_error = Signal(int, str)  # row_idx, error_message
    batch_success = Signal(bool, str, dict)  # is_draft, message, payload_data
    batch_error = Signal(bool, str)  # is_draft, error_message


class AssignedTasksTable(QTableWidget):
    """
    Dynamic KRA / Assigned Tasks and Timesheet Entry Table.

    Columns:
        0. S.No.
        1. Name
        2. Description
        3. Category
        4. Target
        5. Measurement Criteria
        6. Weightage
        7. Task Done Till Now
        8. Task Completed (Editable numeric QLineEdit)
        9. Comment (Editable text QLineEdit)
    """

    # Column config: (header_label, initial_width_px, header_alignment)
    COLUMN_CONFIG = [
        ("S.No.",                  42, Qt.AlignmentFlag.AlignCenter),
        ("Name",                 100, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Description",          135, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Category",              90, Qt.AlignmentFlag.AlignCenter),
        ("Target",                55, Qt.AlignmentFlag.AlignCenter),
        ("Measurement Criteria", 140, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Weightage",             74, Qt.AlignmentFlag.AlignCenter),
        ("Task Done Till Now",   122, Qt.AlignmentFlag.AlignCenter),
        ("Task Completed",       105, Qt.AlignmentFlag.AlignCenter),
        ("Comment",              135, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
    ]

    task_saved = Signal(dict)  # Emitted when a timesheet is saved successfully

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._tasks: List[Dict[str, Any]] = []
        self._is_submitting: bool = False
        self._is_submitted: bool = False
        self._edited_rows: set[int] = set()
        self._user_drafts: Dict[str, Dict[str, str]] = {}

        self._signals = TaskTableSignals()
        self._signals.submit_success.connect(self._handle_submit_success)
        self._signals.submit_error.connect(self._handle_submit_error)
        self._signals.batch_success.connect(self._handle_batch_success)
        self._signals.batch_error.connect(self._handle_batch_error)

        self.setObjectName("AssignedTasksTable")
        self.setStyleSheet(TABLE_STYLESHEET)

        self.setColumnCount(len(self.COLUMN_CONFIG))
        self.setShowGrid(True)
        self.setWordWrap(True)

        # ── Top Title Heading ────────────────────────────────────────────────
        self.title_label = QLabel()
        self.title_label.setObjectName("TaskTableTitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(
            "QLabel#TaskTableTitleLabel {"
            "    color: #1e293b;"
            "    font-size: 15px;"
            "    font-weight: 700;"
            "    padding: 2px 0px 6px 0px;"
            "}"
        )
        self._current_date: str = ""
        self._page_date: str = ""
        self._selected_task_index: Optional[int] = None
        self.update_title()

        # ── Bottom Action Controls ──────────────────────────────────────────
        self.actions_widget = QWidget()
        self.actions_widget.setObjectName("TaskTableActionsWidget")
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(4, 6, 4, 4)
        actions_layout.setSpacing(6)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_msg_label = QLabel("", self.actions_widget)
        self.status_msg_label.setStyleSheet("font-size: 12px; font-weight: 500;")
        self.status_msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_msg_label.setVisible(False)
        actions_layout.addWidget(self.status_msg_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.buttons_container = QWidget(self.actions_widget)
        self.buttons_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        buttons_layout = CenteredFlowLayout(self.buttons_container, margin=0, h_spacing=16, v_spacing=8)

        self.save_draft_btn = QPushButton("Save as Draft", self.buttons_container)
        self.save_draft_btn.setObjectName("SaveDraftButton")
        self.save_draft_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
        self.save_draft_btn.clicked.connect(lambda: self.submit_all_tasks(is_draft=True))
        buttons_layout.addWidget(self.save_draft_btn)

        self.submit_btn = QPushButton("Submit", self.buttons_container)
        self.submit_btn.setObjectName("SubmitTasksButton")
        self.submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_btn.setStyleSheet(self._submit_btn_style_default())
        self.submit_btn.clicked.connect(lambda: self.submit_all_tasks(is_draft=False))
        buttons_layout.addWidget(self.submit_btn)

        actions_layout.addWidget(self.buttons_container)

        self.additional_task_widget: Optional[Any] = None

        self.cellClicked.connect(self._on_cell_clicked)
        self.currentCellChanged.connect(self._on_current_cell_changed)

        # ── Header ────────────────────────────────────────────────────────────
        header = self.horizontalHeader()
        header.setFixedHeight(40)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(36)
        header.setStretchLastSection(False)

        for col_idx, (col_name, col_width, _col_align) in enumerate(self.COLUMN_CONFIG):
            header_item = QTableWidgetItem(col_name)
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            header_font = QFont()
            header_font.setBold(True)
            header_font.setPointSize(9)
            header_item.setFont(header_font)
            header_item.setToolTip(col_name)
            self.setHorizontalHeaderItem(col_idx, header_item)
            header.setSectionResizeMode(col_idx, QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(col_idx, col_width)

        # ── Row config ────────────────────────────────────────────────────────
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(52)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAlternatingRowColors(True)

        # ── Scroll behaviour ──────────────────────────────────────────────────
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.setAutoScroll(False)
        self.setTabKeyNavigation(False)

        self.setMinimumWidth(250)
        self.setMinimumHeight(120)

        # Hide Category (col 3) and Measurement Criteria (col 5) on Timesheet page
        self.setColumnHidden(3, True)
        self.setColumnHidden(5, True)

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible) -> None:
        """
        Preserve horizontal scroll position so item navigation/updates do not jump horizontally.
        Allows vertical scrolling to work normally.
        """
        prev_h = self.horizontalScrollBar().value()
        super().scrollTo(index, hint)
        if self.horizontalScrollBar().value() != prev_h:
            self.horizontalScrollBar().setValue(prev_h)

    def showEvent(self, event) -> None:
        """Ensure column widths are fitted to actual viewport width upon display."""
        super().showEvent(event)
        self._adjust_column_widths()

    def resizeEvent(self, event) -> None:
        """Dynamically adjust column widths when the table container resizes."""
        super().resizeEvent(event)
        self._adjust_column_widths()

    def _adjust_column_widths(self) -> None:
        """Responsively adjust column widths to fit within container width without horizontal scrolling."""
        if self.columnCount() != len(self.COLUMN_CONFIG):
            return

        visible_cols = [c for c in range(len(self.COLUMN_CONFIG)) if not self.isColumnHidden(c)]
        if not visible_cols:
            return

        # Available width inside the table viewport (excludes frame and vertical scrollbar if present)
        v_width = self.viewport().width() if self.viewport() else 0
        w_width = self.width() - (self.frameWidth() * 2)
        if self.verticalScrollBar() and self.verticalScrollBar().isVisible():
            w_width -= self.verticalScrollBar().width()

        target_width = v_width if (self.isVisible() and v_width > 0) else max(v_width, w_width)
        if target_width <= 0:
            target_width = 750

        # Non-clipping minimum header widths based on actual header font metrics
        header = self.horizontalHeader()
        header_font = header.font()

        header_min = {}
        for c in visible_cols:
            item = self.horizontalHeaderItem(c)
            f = item.font() if item else header_font
            col_name = self.COLUMN_CONFIG[c][0]
            header_min[c] = QFontMetrics(f).horizontalAdvance(col_name) + 12

        # Base preferred widths for columns
        default_base_widths = {
            0: 42,   # S.No.
            1: 100,  # Name
            2: 135,  # Description
            3: 75,   # Category
            4: 55,   # Target
            5: 125,  # Measurement Criteria
            6: 74,   # Weightage
            7: 122,  # Task Done Till Now
            8: 105,  # Task Completed
            9: 135,  # Comment
        }
        base_widths = {
            c: max(default_base_widths.get(c, self.COLUMN_CONFIG[c][1]), header_min[c])
            for c in visible_cols
        }

        min_total = sum(header_min.values())
        base_total = sum(base_widths.values())

        # Stretchable text columns: Name (1), Description (2), Comment (9)
        stretchable = [c for c in [1, 2, 9] if c in visible_cols]
        weights = {1: 1, 2: 2, 9: 2}
        tot_wt = sum(weights[c] for c in stretchable) if stretchable else 1

        widths = {}
        if target_width >= base_total:
            extra = target_width - base_total
            added_sum = 0
            for c in visible_cols:
                if c in stretchable:
                    add = int(extra * weights[c] / tot_wt)
                    widths[c] = base_widths[c] + add
                    added_sum += add
                else:
                    widths[c] = base_widths[c]
            # Remainder pixels assigned to the last stretchable column
            rem = extra - added_sum
            last_stretch = stretchable[-1] if stretchable else visible_cols[-1]
            widths[last_stretch] += rem
        elif target_width >= min_total:
            range_tot = max(1, base_total - min_total)
            deficit = base_total - target_width
            ratio = deficit / range_tot
            for c in visible_cols:
                col_range = base_widths[c] - header_min[c]
                reduction = int(col_range * ratio)
                widths[c] = base_widths[c] - reduction
            rem = target_width - sum(widths.values())
            last_stretch = stretchable[-1] if stretchable else visible_cols[-1]
            widths[last_stretch] += rem
        else:
            # Extreme narrow width (< 573px): preserve non-clipping header minimums
            widths = dict(header_min)

        for col_idx in range(len(self.COLUMN_CONFIG)):
            if self.isColumnHidden(col_idx):
                self.setColumnWidth(col_idx, 0)
            else:
                self.setColumnWidth(col_idx, widths.get(col_idx, header_min.get(col_idx, 40)))

        prev_h = self.horizontalScrollBar().value()
        if prev_h != 0:
            self.horizontalScrollBar().setValue(0)

    @property
    def is_submitted(self) -> bool:
        """Return whether the currently displayed Timesheet is in a submitted state."""
        return self._is_submitted

    def _task_key(self, task: Dict[str, Any], fallback_idx: int = -1) -> str:
        """Compute stable unique key for a task dictionary to preserve in-progress user drafts."""
        d = str(task.get("date") or self._page_date or self._current_date or "").strip()
        timesheet_id = str(task.get("timesheet_id") or "").strip()
        kra_id = str(task.get("kra_id") or task.get("id") or "").strip()
        name = str(task.get("name") or task.get("title") or "").strip()
        if timesheet_id and kra_id:
            key = f"{timesheet_id}_{kra_id}"
        elif kra_id:
            key = f"kra_{kra_id}"
        elif timesheet_id:
            key = f"ts_{timesheet_id}"
        elif name:
            key = f"name_{name}"
        else:
            key = f"row_{fallback_idx}"
        return f"{d}::{key}" if d else key

    def _init_task_base_progress(self, task: Dict[str, Any]) -> None:
        """Initialize base progress baseline from server data."""
        raw_done = _extract_task_done(task)
        raw_comp = str(task.get("task_completed") if task.get("task_completed") is not None else "").strip()
        task["_initial_done_str"] = raw_done
        task["_initial_comp_val"] = raw_comp

    def _compute_done_till_now(self, task: Dict[str, Any], completed_text: str = "") -> str:
        """
        Return the API-provided Task Done Till Now value.
        Task Done Till Now is an API-provided value and must not be altered dynamically by Task Completed edits.
        """
        return _extract_task_done(task)

    def set_submitted(self, submitted: bool) -> None:
        """Update submission state, widget read-only mode, and button visibility."""
        self._is_submitted = bool(submitted)

        for r in range(self.rowCount()):
            for c in (8, 9):
                le = self._get_line_edit(r, c)
                if le:
                    le.setReadOnly(self._is_submitted)
                    le.setStyleSheet(_LE_READONLY if self._is_submitted else _LE_NORMAL)

        if self._is_submitted:
            self.save_draft_btn.hide()
            self.submit_btn.hide()
            if hasattr(self, "buttons_container"):
                self.buttons_container.hide()
            self.submit_btn.setText("Submit")
            self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            self.save_draft_btn.setText("Save as Draft")
            self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
        else:
            if not self._tasks:
                self.save_draft_btn.hide()
                self.submit_btn.hide()
                if hasattr(self, "buttons_container"):
                    self.buttons_container.hide()
            else:
                if hasattr(self, "buttons_container"):
                    self.buttons_container.show()
                self.save_draft_btn.show()
                self.submit_btn.show()
                self.save_draft_btn.setEnabled(True)
                self.submit_btn.setEnabled(True)
                if not self._is_submitting:
                    if not self.submit_btn.text().startswith("Retry"):
                        self.submit_btn.setText("Submit")
                        self.submit_btn.setStyleSheet(self._submit_btn_style_default())
                    if not self.save_draft_btn.text().startswith("Draft Saved") and not self.save_draft_btn.text().startswith("Retry"):
                        self.save_draft_btn.setText("Save as Draft")
                        self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())

    def _is_submitted_data(self, tasks: Optional[List[Dict[str, Any]]] = None) -> bool:
        """
        Determine whether tasks authoritatively indicate that the Timesheet is submitted.
        Checks:
          - TaskService tracked submitted state for current date
          - task["submit_status"] in ("1", "2", "true", "True")
          - raw["submit_status"] in ("1", "2", "true", "True")
          - task["status"].lower() in ("submitted", "completed")
          - raw["status"] in ("2", 2)
          - raw["status"].lower() in ("submitted", "completed")
          - raw["is_already_submitted"] is True
          - "already submitted" in message
        """
        task_list = tasks if tasks is not None else self._tasks
        if not task_list:
            return False

        for t in task_list:
            if not isinstance(t, dict):
                continue
            if bool(t.get("is_additional")):
                continue
            for k in ("submit_status", "submitStatus", "is_submitted", "isSubmitted", "timesheet_status"):
                v = str(t.get(k) or "").strip()
                if v in ("1", "2", "true", "True"):
                    return True
            raw = t.get("raw")
            if isinstance(raw, dict):
                for k in ("submit_status", "submitStatus", "is_submitted", "isSubmitted", "timesheet_status"):
                    v = str(raw.get(k) or "").strip()
                    if v in ("1", "2", "true", "True"):
                        return True
                if str(raw.get("status") or "").strip() in ("2",):
                    return True
                if bool(raw.get("is_already_submitted")):
                    return True
                if "already submitted" in str(raw.get("message") or "").lower() or "already submitted" in str(raw.get("response") or "").lower():
                    return True
                if str(raw.get("status") or "").strip().lower() in ("submitted", "completed"):
                    return True
            if str(t.get("status") or "").strip().lower() in ("submitted", "completed"):
                return True
        return False

    @property
    def tasks(self) -> List[Dict[str, Any]]:
        """Return the current list of tasks displayed in the table."""
        return list(self._tasks)

    def _get_line_edit(self, row: int, col: int) -> Optional[QLineEdit]:
        """Retrieve QLineEdit widget directly or from container widget."""
        widget = self.cellWidget(row, col)
        if isinstance(widget, QLineEdit):
            return widget
        if isinstance(widget, QWidget):
            return widget.findChild(QLineEdit)
        return None

    def update_row_numbers(self) -> None:
        """Dynamically refresh S.No. column based on current row display order."""
        for r in range(self.rowCount()):
            item = self.item(r, 0)
            if item is not None:
                item.setText(str(r + 1))

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Handle cell click to dynamically update heading for selected task."""
        if 0 <= row < len(self._tasks):
            self.select_task_by_index(row)

    def _on_current_cell_changed(self, current_row: int, current_col: int, prev_row: int, prev_col: int) -> None:
        """Handle keyboard or focus navigation across cells to keep heading synchronized."""
        if 0 <= current_row < len(self._tasks):
            self.select_task_by_index(current_row)

    def _handle_line_edit_focused(self, edit_widget: QWidget) -> None:
        """Handle focus on editable cell controls to synchronize selected task heading."""
        for r in range(self.rowCount()):
            for c in (8, 9):
                if self._get_line_edit(r, c) == edit_widget:
                    self.select_task_by_index(r)
                    return

    def select_task_by_index(self, row_idx: int, force: bool = False) -> None:
        """Select a task by row index and dynamically update heading and controls."""
        if not (0 <= row_idx < len(self._tasks)):
            return
        if not force and self._selected_task_index == row_idx:
            return
        self._selected_task_index = row_idx
        selected_task = self._tasks[row_idx]
        self.update_title(task=selected_task)
        if getattr(self, "additional_task_widget", None):
            task_d = str(selected_task.get("date") or "").strip()
            if task_d:
                self.additional_task_widget.set_date(task_d)

    def current_task(self) -> Optional[Dict[str, Any]]:
        """Return the currently selected task dictionary, or None."""
        if not self._tasks:
            return None
        idx = self._selected_task_index if self._selected_task_index is not None else 0
        if 0 <= idx < len(self._tasks):
            return self._tasks[idx]
        return self._tasks[0]

    def _resolve_employee_info(
        self,
        task: Optional[Dict[str, Any]] = None,
        tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[str, str]:
        """
        Dynamically resolve (employee_name, employee_code) from:
          1. Selected task
          2. Tasks list
          3. SessionService / current_user
          4. SessionStore
          5. QSettings
        """
        emp_name = ""
        emp_code = ""

        # 1. Check selected task first
        target_task = task if task is not None else self.current_task()
        if target_task and isinstance(target_task, dict):
            emp_name = str(
                target_task.get("employee_name")
                or target_task.get("emp_name")
                or target_task.get("user_name")
                or target_task.get("full_name")
                or ""
            ).strip()
            emp_code = str(
                target_task.get("indo_code")
                or target_task.get("employee_code")
                or target_task.get("emp_code")
                or target_task.get("employee_id")
                or ""
            ).strip()

            raw = target_task.get("raw")
            if isinstance(raw, dict):
                if not emp_name:
                    emp_name = str(
                        raw.get("employee_name")
                        or raw.get("emp_name")
                        or raw.get("user_name")
                        or raw.get("full_name")
                        or ""
                    ).strip()
                if not emp_code:
                    emp_code = str(
                        raw.get("indo_code")
                        or raw.get("employee_code")
                        or raw.get("emp_code")
                        or raw.get("employee_id")
                        or ""
                    ).strip()

        # 2. Check tasks list if not fully resolved
        if not emp_name or not emp_code:
            task_list = tasks if tasks is not None else self._tasks
            for t in task_list:
                if not emp_name:
                    emp_name = str(
                        t.get("employee_name")
                        or t.get("emp_name")
                        or t.get("user_name")
                        or t.get("full_name")
                        or ""
                    ).strip()
                if not emp_code:
                    emp_code = str(
                        t.get("indo_code")
                        or t.get("employee_code")
                        or t.get("emp_code")
                        or t.get("employee_id")
                        or ""
                    ).strip()
                raw = t.get("raw")
                if isinstance(raw, dict):
                    if not emp_name:
                        emp_name = str(
                            raw.get("employee_name")
                            or raw.get("emp_name")
                            or raw.get("user_name")
                            or raw.get("full_name")
                            or ""
                        ).strip()
                    if not emp_code:
                        emp_code = str(
                            raw.get("indo_code")
                            or raw.get("employee_code")
                            or raw.get("emp_code")
                            or raw.get("employee_id")
                            or ""
                        ).strip()
                if emp_name and emp_code:
                    break

        # 3. Check SessionService
        if not emp_name or not emp_code:
            try:
                from services.session_service import SessionService
                user = SessionService().current_user
                if user:
                    if not emp_name:
                        if user.full_name and str(user.full_name).strip() and str(user.full_name).strip().lower() != "persisted user":
                            emp_name = str(user.full_name).strip()
                        elif user.display_name and str(user.display_name).strip() and str(user.display_name).strip().lower() not in ("user", "persisted user"):
                            emp_name = str(user.display_name).strip()
                        elif user.username and str(user.username).strip() and str(user.username).strip().lower() != "persisted user":
                            emp_name = str(user.username).strip()

                    if not emp_code:
                        if user.indo_code and str(user.indo_code).strip():
                            emp_code = str(user.indo_code).strip()
                        elif user.employee_id and str(user.employee_id).strip():
                            emp_code = str(user.employee_id).strip()

                    if user.raw_login_data and isinstance(user.raw_login_data, dict):
                        ld = user.raw_login_data.get("data", {}) if isinstance(user.raw_login_data.get("data"), dict) else {}
                        if not emp_name:
                            for f in ("fullName", "full_name", "name", "employee_name", "emp_name", "employeeName"):
                                v = user.raw_login_data.get(f) or ld.get(f)
                                if v and str(v).strip() and str(v).strip().lower() != "persisted user":
                                    emp_name = str(v).strip()
                                    break
                        if not emp_code:
                            for f in ("indo_code", "employee_code", "emp_code", "employee_id", "emp_id", "empCode"):
                                v = user.raw_login_data.get(f) or ld.get(f)
                                if v and str(v).strip():
                                    emp_code = str(v).strip()
                                    break
            except Exception as e:
                logger.debug("AssignedTasksTable: error checking SessionService: %s", e)

        # 4. Check SessionStore
        if not emp_name or not emp_code:
            try:
                from services.secure_session import SessionStore
                saved = SessionStore().load_session()
                if saved and isinstance(saved, dict):
                    if not emp_name:
                        emp_name = str(saved.get("full_name") or saved.get("name") or saved.get("username") or "").strip()
                    if not emp_code:
                        emp_code = str(saved.get("indo_code") or saved.get("employee_id") or "").strip()
            except Exception as e:
                logger.debug("AssignedTasksTable: error checking SessionStore: %s", e)

        # 5. Check QSettings
        if not emp_code:
            try:
                from PySide6.QtCore import QSettings
                st = QSettings("Indovision", "iHRMSMonitor")
                emp_code = str(st.value("last_employee_id") or "").strip()
            except Exception:
                pass

        return emp_name, emp_code

    def update_title(
        self,
        name: Optional[str] = None,
        code: Optional[str] = None,
        date: Optional[str] = None,
        task: Optional[Dict[str, Any]] = None,
        tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Dynamically update the centered heading above the table for the selected task."""
        target_task = task if task is not None else self.current_task()
        resolved_name, resolved_code = self._resolve_employee_info(task=target_task, tasks=tasks)
        if name:
            resolved_name = name
        if code:
            resolved_code = code

        # Resolve date: explicit argument -> target task date -> page_date -> task_list date
        date_val = ""
        if date:
            date_val = str(date).strip()
            self._page_date = date_val

        if not date_val and target_task and isinstance(target_task, dict):
            raw_d = (
                target_task.get("date")
                or target_task.get("assigned_date")
                or target_task.get("due_date")
                or target_task.get("target_date")
                or (target_task.get("raw") or {}).get("date")
                or (target_task.get("raw") or {}).get("assigned_date")
                or ""
            )
            if raw_d and str(raw_d).strip().lower() not in ("none", "null", ""):
                date_val = str(raw_d).strip()

        if not date_val and getattr(self, "_page_date", ""):
            date_val = getattr(self, "_page_date", "")

        if not date_val:
            task_list = tasks if tasks is not None else self._tasks
            for t in (task_list or []):
                raw_d = (
                    t.get("date")
                    or t.get("assigned_date")
                    or t.get("due_date")
                    or t.get("target_date")
                    or (t.get("raw") or {}).get("date")
                    or ""
                )
                if raw_d and str(raw_d).strip().lower() not in ("none", "null", ""):
                    date_val = str(raw_d).strip()
                    break

        if date_val:
            self._current_date = str(date_val)

        formatted_date = format_task_date(date_val) if date_val else ""

        if resolved_name and resolved_code and formatted_date:
            heading = f"Timesheet for {resolved_name} ({resolved_code}) on {formatted_date}"
        elif resolved_name and resolved_code:
            heading = f"Timesheet for {resolved_name} ({resolved_code})"
        elif resolved_name and formatted_date:
            heading = f"Timesheet for {resolved_name} on {formatted_date}"
        elif resolved_code and formatted_date:
            heading = f"Timesheet for {resolved_code} on {formatted_date}"
        elif formatted_date:
            heading = f"Timesheet on {formatted_date}"
        elif resolved_name:
            heading = f"Timesheet for {resolved_name}"
        elif resolved_code:
            heading = f"Timesheet for {resolved_code}"
        else:
            heading = "Timesheet"

        self.title_label.setText(heading)

    def set_tasks(self, tasks: List[Dict[str, Any]], date: Optional[str] = None) -> None:
        """Display assigned KRA tasks dynamically from API response, keeping Additional Tasks separate."""
        prev_h_scroll = self.horizontalScrollBar().value()
        prev_v_scroll = self.verticalScrollBar().value()

        raw_tasks = list(tasks or [])

        # ── 1. Separate Timesheet tasks from Additional Tasks ────────────────
        additional_items = [t for t in raw_tasks if bool(t.get("is_additional"))]
        timesheet_tasks = [dict(t) for t in raw_tasks if not bool(t.get("is_additional"))]

        self._tasks = timesheet_tasks
        self._selected_task_index = 0 if self._tasks else None
        selected_task = self._tasks[0] if self._tasks else None
        self._page_date = str(date).strip() if date else ""

        # Update dynamic heading above table for the currently selected task
        self.update_title(date=date, task=selected_task, tasks=self._tasks)

        # ── 2. Update Additional Task section exclusively ────────────────────
        if getattr(self, "additional_task_widget", None):
            task_date = date
            if not task_date and selected_task:
                task_date = selected_task.get("date")
            elif not task_date and additional_items:
                task_date = additional_items[0].get("date")
            prev_widget_date = self.additional_task_widget.date()
            date_changed = bool(task_date and prev_widget_date and str(task_date).strip() != str(prev_widget_date).strip())
            if task_date:
                self.additional_task_widget.set_date(task_date)

            if additional_items:
                t = additional_items[0]
                desc = str(t.get("description") or t.get("remark") or t.get("task") or "").strip()
                raw_dict = t.get("raw") if isinstance(t.get("raw"), dict) else {}
                is_sub = (
                    str(t.get("submit_status") or "").strip() in ("1", "2", "true", "True")
                    or str(t.get("task_completed") or "").strip() in ("1", "100")
                    or str(t.get("status") or "").strip().lower() in ("completed", "submitted")
                    or str(raw_dict.get("additional_task_status") or "").strip() in ("1", "2", "true", "True")
                    or str(t.get("additional_task_status") or "").strip() in ("1", "2", "true", "True")
                    or str(raw_dict.get("submit_status") or "").strip() in ("1", "2", "true", "True")
                    or str(raw_dict.get("status") or "").strip() in ("2",)
                    or "already submitted" in str(raw_dict.get("message") or "").lower()
                    or bool(raw_dict.get("is_already_submitted"))
                )
                self.additional_task_widget.set_task_content(desc, is_submitted=is_sub)
            else:
                is_sub = False
                if task_date:
                    try:
                        from services.task_service import TaskService
                        is_sub = TaskService().is_additional_task_submitted(task_date)
                    except Exception:
                        is_sub = False
                curr_content = self.additional_task_widget.task_content()
                is_ph = getattr(self.additional_task_widget, "_is_placeholder", lambda v: False)(curr_content)
                if date_changed or is_ph:
                    self.additional_task_widget.set_task_content("", is_submitted=is_sub)
                elif is_sub:
                    self.additional_task_widget.set_submitted(True)

        # Capture focus state if an edit field is active
        focused_widget = QApplication.focusWidget()
        focus_info = None
        if focused_widget and isinstance(focused_widget, QLineEdit):
            for r in range(self.rowCount()):
                for c in (8, 9):
                    if self._get_line_edit(r, c) == focused_widget:
                        focus_info = (r, c, focused_widget.text(), focused_widget.cursorPosition())
                        break

        self.setUpdatesEnabled(False)
        self.setRowCount(0)
        self._edited_rows.clear()

        # Check authoritative submission status
        self._is_submitted = self._is_submitted_data(self._tasks)

        # Initialize base progress baseline for each task
        for r_idx, task in enumerate(self._tasks):
            self._init_task_base_progress(task)

        # ── 3. Merge in-progress user drafts or restore confirmed saved values ─
        for r_idx, task in enumerate(self._tasks):
            t_key = self._task_key(task, r_idx)
            if t_key in self._user_drafts:
                draft = self._user_drafts[t_key]
                if not self._is_submitted:
                    if "comment" in draft:
                        task["comment"] = draft["comment"]
                        task["remark"] = draft["comment"]
                    if "task_completed" in draft:
                        task["task_completed"] = draft["task_completed"]
                else:
                    # In submitted state, if the API response is incomplete (e.g. omitted comment or task_completed),
                    # restore from the authoritative saved values using stable task key
                    if not task.get("comment") and "comment" in draft:
                        task["comment"] = draft["comment"]
                        task["remark"] = draft["comment"]
                    if (task.get("task_completed") is None or str(task.get("task_completed")).strip() == "") and "task_completed" in draft:
                        task["task_completed"] = draft["task_completed"]

        if not self._tasks:
            self.setRowCount(1)
            self.setRowHeight(0, 70)
            empty_item = QTableWidgetItem("No assigned tasks found.")
            empty_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            empty_font = QFont()
            empty_font.setPointSize(9)
            empty_item.setFont(empty_font)
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.setItem(0, 0, empty_item)
            self.setSpan(0, 0, 1, len(self.COLUMN_CONFIG))
            self.setMinimumHeight(115)
            self.save_draft_btn.setEnabled(False)
            self.submit_btn.setEnabled(False)
            self.save_draft_btn.hide()
            self.submit_btn.hide()
            if hasattr(self, "buttons_container"):
                self.buttons_container.hide()
            self.setUpdatesEnabled(True)
            return

        self.set_submitted(self._is_submitted)

        # Clear any spans
        self.clearSpans()

        # Ensure Category and Measurement Criteria remain hidden
        self.setColumnHidden(3, True)
        self.setColumnHidden(5, True)

        # Non-negative numeric regex validator for Task Completed (e.g. 25, 10.5, 100)
        num_regex = QRegularExpression(r"^\d{0,6}(\.\d{0,2})?$")

        for row, task in enumerate(self._tasks):
            self.insertRow(row)
            self.setRowHeight(row, 52)

            name = str(task.get("name") or task.get("title") or "Task").strip()
            desc = str(task.get("description") or "-").strip()
            category = str(task.get("category") or "-").strip()
            target = str(task.get("target") or "-").strip()
            criteria = str(task.get("measurement_criteria") or "-").strip()
            weight = str(task.get("weightage") or "-").strip()
            task_done = _extract_task_done(task)
            task_completed = str(task.get("task_completed") if task.get("task_completed") is not None else "").strip()
            comment = str(task.get("comment") or task.get("remark") or "").strip()

            # 0. S.No. (Read-only, Centered)
            sno_item = QTableWidgetItem(str(row + 1))
            sno_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            sno_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 0, sno_item)

            # 1. Name (Read-only, Left-aligned)
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 1, name_item)

            # 2. Description (Read-only, Left-aligned, Wrapped)
            desc_item = QTableWidgetItem(desc)
            desc_item.setToolTip(desc)
            desc_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            desc_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 2, desc_item)

            # 3. Category (Read-only, Centered, Hidden)
            cat_item = QTableWidgetItem(category)
            cat_item.setToolTip(category)
            cat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 3, cat_item)

            # 4. Target (Read-only, Centered)
            target_item = QTableWidgetItem(target)
            target_item.setToolTip(target)
            target_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            target_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 4, target_item)

            # 5. Measurement Criteria (Read-only, Left-aligned, Wrapped, Hidden)
            crit_item = QTableWidgetItem(criteria)
            crit_item.setToolTip(criteria)
            crit_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            crit_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 5, crit_item)

            # 6. Weightage (Read-only, Centered)
            weight_item = QTableWidgetItem(weight)
            weight_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            weight_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 6, weight_item)

            # 7. Task Done Till Now (Read-only, Centered)
            done_item = QTableWidgetItem(task_done)
            done_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            done_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 7, done_item)

            # ── Col 8: Task Completed — numeric QLineEdit ────────────────────
            comp_container = QWidget(self)
            comp_layout = QHBoxLayout(comp_container)
            comp_layout.setContentsMargins(4, 3, 4, 3)
            comp_layout.setSpacing(0)
            comp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            display_completed = task_completed if task_completed != "" else ("0" if self._is_submitted else "")
            completed_edit = StableLineEdit(display_completed, comp_container, table=self)
            completed_edit.setPlaceholderText("0" if not self._is_submitted else "")
            completed_edit.setValidator(QRegularExpressionValidator(num_regex, completed_edit))
            completed_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            completed_edit.setReadOnly(self._is_submitted)
            completed_edit.setStyleSheet(_LE_READONLY if self._is_submitted else _LE_NORMAL)
            completed_edit.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            completed_edit.textChanged.connect(
                lambda text, r=row: self._on_task_completed_changed(r, text)
            )
            comp_layout.addWidget(completed_edit)
            self.setCellWidget(row, 8, comp_container)

            # ── Col 9: Comment — text QLineEdit ──────────────────────────────
            comment_container = QWidget(self)
            comment_layout = QHBoxLayout(comment_container)
            comment_layout.setContentsMargins(4, 3, 4, 3)
            comment_layout.setSpacing(0)

            comment_edit = StableLineEdit(comment, comment_container, table=self)
            comment_edit.setPlaceholderText("Enter comments / work details..." if not self._is_submitted else "")
            comment_edit.setReadOnly(self._is_submitted)
            comment_edit.setStyleSheet(_LE_READONLY if self._is_submitted else _LE_NORMAL)
            comment_edit.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            comment_edit.textChanged.connect(
                lambda text, r=row: self._on_comment_changed(r, text)
            )
            comment_layout.addWidget(comment_edit)
            self.setCellWidget(row, 9, comment_container)

        # Configure logical Tab navigation order across all editable fields and actions
        prev_edit: Optional[QWidget] = None
        for r_idx in range(len(self._tasks)):
            comp_le = self._get_line_edit(r_idx, 8)
            cmt_le = self._get_line_edit(r_idx, 9)
            if comp_le and cmt_le:
                if prev_edit:
                    QWidget.setTabOrder(prev_edit, comp_le)
                QWidget.setTabOrder(comp_le, cmt_le)
                prev_edit = cmt_le

        if prev_edit:
            QWidget.setTabOrder(prev_edit, self.save_draft_btn)
            QWidget.setTabOrder(self.save_draft_btn, self.submit_btn)
            if getattr(self, "additional_task_widget", None) and hasattr(self.additional_task_widget, "text_edit"):
                QWidget.setTabOrder(self.submit_btn, self.additional_task_widget.text_edit)

        self.setMinimumHeight(min(450, 48 + len(self._tasks) * 54))
        self._adjust_column_widths()
        self.horizontalScrollBar().setValue(prev_h_scroll)
        self.verticalScrollBar().setValue(prev_v_scroll)
        self.setUpdatesEnabled(True)

        self.set_submitted(self._is_submitted)

        if focus_info:
            r, c, text, cursor_pos = focus_info
            if r < self.rowCount():
                le = self._get_line_edit(r, c)
                if le:
                    le.setFocus()
                    le.setCursorPosition(cursor_pos)

    def _on_task_completed_changed(self, row: int, text: str) -> None:
        """Synchronize backing task state and persistent drafts when user edits Task Completed."""
        val = text.strip()
        self._edited_rows.add(row)
        if row < len(self._tasks):
            task = self._tasks[row]
            task["task_completed"] = val
            t_key = self._task_key(task, row)
            if t_key not in self._user_drafts:
                self._user_drafts[t_key] = {}
            self._user_drafts[t_key]["task_completed"] = val

            prev_h = self.horizontalScrollBar().value()
            item = self.item(row, 8)
            if item and item.text() != val:
                item.setText(val)
                if self.horizontalScrollBar().value() != prev_h:
                    self.horizontalScrollBar().setValue(prev_h)

        # Reset button from retry state if user is editing
        if not self._is_submitting:
            if self.submit_btn.text().startswith("Retry"):
                self.submit_btn.setText("Submit")
                self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            if self.save_draft_btn.text().startswith("Retry"):
                self.save_draft_btn.setText("Save as Draft")
                self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())

        # Clear error styling if active
        comp_edit = self._get_line_edit(row, 8)
        if comp_edit and "border: 1.5px solid #ef4444" in comp_edit.styleSheet():
            comp_edit.setStyleSheet(_LE_NORMAL)
            comp_edit.setToolTip("")

    def _on_comment_changed(self, row: int, text: str) -> None:
        """Synchronize backing task state and persistent drafts when user edits Comment."""
        self._edited_rows.add(row)
        if row < len(self._tasks):
            self._tasks[row]["comment"] = text
            self._tasks[row]["remark"] = text
            t_key = self._task_key(self._tasks[row], row)
            if t_key not in self._user_drafts:
                self._user_drafts[t_key] = {}
            self._user_drafts[t_key]["comment"] = text

        prev_h = self.horizontalScrollBar().value()
        item = self.item(row, 9)
        if item and item.text() != text:
            item.setText(text)
            if self.horizontalScrollBar().value() != prev_h:
                self.horizontalScrollBar().setValue(prev_h)

        # Reset button from retry state if user is editing
        if not self._is_submitting:
            if self.submit_btn.text().startswith("Retry"):
                self.submit_btn.setText("Submit")
                self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            if self.save_draft_btn.text().startswith("Retry"):
                self.save_draft_btn.setText("Save as Draft")
                self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())

        # Clear error styling if active
        comment_edit = self._get_line_edit(row, 9)
        if comment_edit and "border: 1.5px solid #ef4444" in comment_edit.styleSheet():
            comment_edit.setStyleSheet(_LE_NORMAL)
            comment_edit.setToolTip("")

    def _get_task_completed(self, row: int) -> str:
        """Get the current Task Completed value from line edit or internal task dict."""
        edit = self._get_line_edit(row, 8)
        if edit:
            return edit.text().strip()
        if row < len(self._tasks):
            val = self._tasks[row].get("task_completed")
            if val is not None and str(val).strip() not in ("None", "null"):
                return str(val).strip()
            return ""
        return ""

    def _get_task_done_till_now(self, row: int) -> str:
        """Get the current Task Done Till Now value from table item or internal task dict."""
        item = self.item(row, 7)
        if item:
            return item.text().strip()
        if row < len(self._tasks):
            return _extract_task_done(self._tasks[row])
        return ""

    def _get_comment(self, row: int) -> str:
        """Get the current Comment value from line edit or internal task dict."""
        edit = self._get_line_edit(row, 9)
        if edit:
            return edit.text().strip()
        if row < len(self._tasks):
            return str(self._tasks[row].get("comment") or self._tasks[row].get("remark") or "").strip()
        return ""

    def submit_all_tasks(self, is_draft: bool = False) -> None:
        """
        Validate and submit all applicable KRA tasks (or save as draft).

        Payload structure follows TaskPMS/fill_time_sheet:
        {
            "key": "...",
            "indo_code": "...",
            "date": "YYYY-MM-DD",
            "submit_status": "0" (draft) | "1" (submit),
            "kraList": [...]
        }
        """
        if self._is_submitting:
            logger.info("submit_all_tasks: submission already in progress, ignoring duplicate call.")
            return

        if not self._tasks:
            self._show_status("No tasks available to save.", is_error=True)
            return

        # 1. Determine candidate rows to submit
        candidate_rows: set[int] = set(self._edited_rows)
        for r in range(len(self._tasks)):
            comm = self._get_comment(r)
            comp = self._get_task_completed(r)
            if comm or (comp and comp not in ("0", "")):
                candidate_rows.add(r)

        if not candidate_rows:
            if not is_draft:
                comm_edit = self._get_line_edit(0, 9)
                if comm_edit:
                    comm_edit.setStyleSheet(_LE_ERROR)
                    comm_edit.setToolTip("Please enter comments before saving.")
                    comm_edit.setFocus()
                self._show_status("Please enter comments before submitting.", is_error=True)
                return
            else:
                candidate_rows = set(range(len(self._tasks)))

        # 2. Validation
        for r in sorted(candidate_rows):
            comp_edit = self._get_line_edit(r, 8)
            comm_edit = self._get_line_edit(r, 9)
            comp_val = self._get_task_completed(r)
            comm_val = self._get_comment(r)

            if comp_val:
                try:
                    num_val = float(comp_val)
                    if num_val < 0:
                        if comp_edit:
                            comp_edit.setStyleSheet(_LE_ERROR)
                            comp_edit.setToolTip("Task Completed cannot be negative.")
                            comp_edit.setFocus()
                        self._show_status("Task Completed cannot be negative.", is_error=True)
                        return
                except ValueError:
                    if comp_edit:
                        comp_edit.setStyleSheet(_LE_ERROR)
                        comp_edit.setToolTip("Please enter a valid number.")
                        comp_edit.setFocus()
                    self._show_status("Please enter a valid number.", is_error=True)
                    return

            if not is_draft and not comm_val:
                if comm_edit:
                    comm_edit.setStyleSheet(_LE_ERROR)
                    comm_edit.setToolTip("Please enter comments before saving.")
                    comm_edit.setFocus()
                self._show_status("Please enter comments before submitting.", is_error=True)
                return

            if comp_edit:
                comp_edit.setStyleSheet(_LE_NORMAL)
                comp_edit.setToolTip("")
            if comm_edit:
                comm_edit.setStyleSheet(_LE_NORMAL)
                comm_edit.setToolTip("")

        # 3. Prevent duplicate submissions & show loading state
        self._is_submitting = True
        self.save_draft_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)

        if is_draft:
            self.save_draft_btn.setText("Saving Draft...")
            self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
            self._show_status("Saving draft...", is_error=False)
        else:
            self.submit_btn.setText("Submitting...")
            self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            self.submit_btn.show()
            self._show_status("Submitting timesheet...", is_error=False)

        # 4. Assemble payload
        rows_to_include = sorted(candidate_rows) if not is_draft else list(range(len(self._tasks)))
        kra_list: List[Dict[str, str]] = []
        resolved_date = ""

        for r in rows_to_include:
            if r >= len(self._tasks):
                continue
            task = self._tasks[r]
            d = str(task.get("date") or "").strip()
            if d and not resolved_date:
                resolved_date = d

            comm_val = self._get_comment(r)
            comp_val = self._get_task_completed(r)
            if not comp_val and task.get("task_completed") is not None and str(task.get("task_completed")).strip() != "":
                comp_val = str(task.get("task_completed")).strip()
            if not comp_val:
                comp_val = "0"
            done_val = self._get_task_done_till_now(r)
            if not done_val or done_val == "-":
                raw_td = _extract_task_done(task)
                if raw_td != "-":
                    done_val = raw_td
                else:
                    done_val = comp_val

            kra_list.append({
                "TimeSheet_id": str(task.get("timesheet_id") or ""),
                "timesheet_id": str(task.get("timesheet_id") or ""),
                "kra_id": str(task.get("kra_id") or task.get("id") or ""),
                "remark": comm_val,
                "comment": comm_val,
                "task_completed": comp_val,
                "task_done": done_val,
            })

        if not resolved_date:
            resolved_date = (
                str(getattr(self, "_page_date", "") or "").strip()
                or str(getattr(self, "_current_date", "") or "").strip()
                or date.today().strftime("%Y-%m-%d")
            )

        submit_status_val = "0" if is_draft else "1"

        def worker():
            from services.task_service import TaskService
            svc = TaskService()
            try:
                ok = True
                msg = ""
                res = None
                if kra_list:
                    ok, msg, res = svc.save_time_sheet(
                        kra_list=kra_list,
                        date=resolved_date,
                        submit_status=submit_status_val,
                    )

                is_already_sub = (
                    "already submitted" in str(msg).lower()
                    or str((res or {}).get("status")) == "2"
                    or (res or {}).get("is_already_submitted", False)
                )

                if not is_draft and is_already_sub:
                    fresh_tasks = []
                    try:
                        fresh_tasks = svc.fetch_assigned_tasks(date=resolved_date, force=True)
                    except Exception as fe:
                        logger.warning("fetch_assigned_tasks failed verifying already submitted: %s", fe)

                    if fresh_tasks and self._is_submitted_data(fresh_tasks):
                        svc.mark_timesheet_submitted(resolved_date)
                        self._signals.batch_success.emit(
                            False,
                            msg or "Timesheet already submitted.",
                            {
                                "response": res or {},
                                "fresh_tasks": fresh_tasks,
                                "saved_kra_list": kra_list,
                                "date": resolved_date,
                                "is_already_submitted": True,
                            },
                        )
                        return
                    else:
                        self._signals.batch_error.emit(
                            False,
                            "Timesheet already submitted on server, but existing record could not be confirmed.",
                        )
                        return

                if ok:
                    fresh_tasks = []
                    try:
                        fresh_tasks = svc.fetch_assigned_tasks(date=resolved_date, force=True)
                    except Exception as fe:
                        logger.warning("fetch_assigned_tasks failed after successful submit: %s", fe)

                    self._signals.batch_success.emit(
                        is_draft,
                        msg or ("Draft saved successfully." if is_draft else "Timesheet submitted successfully."),
                        {
                            "response": res or {},
                            "fresh_tasks": fresh_tasks,
                            "saved_kra_list": kra_list,
                            "date": resolved_date,
                        },
                    )
                else:
                    self._signals.batch_error.emit(is_draft, msg or "Failed to submit timesheet.")
            except Exception as e:
                logger.exception("submit_all_tasks worker exception: %s", e)
                self._signals.batch_error.emit(is_draft, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_batch_success(self, is_draft: bool, msg: str, data: dict) -> None:
        """Handle successful batch submission (draft or final submit)."""
        logger.info("AssignedTasksTable: batch success is_draft=%s: %s", is_draft, msg)
        self._is_submitting = False
        self._edited_rows.clear()

        fresh_tasks = data.get("fresh_tasks", [])
        submission_date = data.get("date") or self._page_date or self._current_date

        if not is_draft:
            # Backend has authoritatively confirmed Timesheet submission succeeded.
            # Do not clear or replace form state with an incomplete response!
            saved_items = data.get("saved_kra_list", [])
            saved_map_by_kra: Dict[str, Dict[str, Any]] = {}
            saved_map_by_ts: Dict[str, Dict[str, Any]] = {}
            for item in saved_items:
                k_id = str(item.get("kra_id") or item.get("id") or "").strip()
                ts_id = str(item.get("TimeSheet_id") or item.get("timesheet_id") or "").strip()
                if k_id:
                    saved_map_by_kra[k_id] = item
                if ts_id:
                    saved_map_by_ts[ts_id] = item

            # Update our persistent drafts and local tasks with the saved values using stable identifiers
            for r_idx, t in enumerate(self._tasks):
                k_id = str(t.get("kra_id") or t.get("id") or "").strip()
                ts_id = str(t.get("timesheet_id") or "").strip()
                matched = saved_map_by_kra.get(k_id) or saved_map_by_ts.get(ts_id)
                t_key = self._task_key(t, r_idx)
                if t_key not in self._user_drafts:
                    self._user_drafts[t_key] = {}
                if matched:
                    saved_comp = str(matched.get("task_completed") or "").strip()
                    saved_rem = str(matched.get("remark") or matched.get("comment") or "").strip()
                    if saved_comp:
                        self._user_drafts[t_key]["task_completed"] = saved_comp
                        t["task_completed"] = saved_comp
                    if saved_rem:
                        self._user_drafts[t_key]["comment"] = saved_rem
                        t["comment"] = saved_rem
                        t["remark"] = saved_rem
                    matched_done = _extract_task_done(matched)
                    if matched_done != "-":
                        self._user_drafts[t_key]["task_done"] = matched_done
                        t["task_done"] = matched_done
                        t["task_done_till_now"] = matched_done
                t["submit_status"] = "1"
                t["status"] = "Completed"
                if isinstance(t.get("raw"), dict):
                    t["raw"]["submit_status"] = "1"

            if fresh_tasks:
                for ft in fresh_tasks:
                    ft["submit_status"] = "1"
                    ft["status"] = "Completed"
                    if isinstance(ft.get("raw"), dict):
                        ft["raw"]["submit_status"] = "1"

                    k_id = str(ft.get("kra_id") or ft.get("id") or "").strip()
                    ts_id = str(ft.get("timesheet_id") or "").strip()
                    matched = saved_map_by_kra.get(k_id) or saved_map_by_ts.get(ts_id)
                    if matched:
                        saved_comp = str(matched.get("task_completed") or "").strip()
                        saved_rem = str(matched.get("remark") or matched.get("comment") or "").strip()
                        if (ft.get("task_completed") is None or str(ft.get("task_completed")).strip() == "") and saved_comp:
                            ft["task_completed"] = saved_comp
                        if not ft.get("comment") and saved_rem:
                            ft["comment"] = saved_rem
                            ft["remark"] = saved_rem
                        curr_done = _extract_task_done(ft)
                        if curr_done == "-":
                            matched_done = _extract_task_done(matched)
                            if matched_done != "-":
                                ft["task_done"] = matched_done
                                ft["task_done_till_now"] = matched_done
                self.set_tasks(fresh_tasks, date=submission_date)
            else:
                self.set_tasks(self._tasks, date=submission_date)

            # Reset button texts/styles in case unsubmitted state is ever set again
            self.submit_btn.setText("Submit")
            self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            self.save_draft_btn.setText("Save as Draft")
            self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())

            try:
                from services.task_service import TaskService
                TaskService().mark_timesheet_submitted(submission_date)
            except Exception:
                pass

            self.set_submitted(True)
            self._show_status("Timesheet submitted successfully.", is_error=False)
        else:
            # Draft saved successfully - update user drafts with saved values
            for item in data.get("saved_kra_list", []):
                k_id = str(item.get("kra_id") or item.get("id") or "").strip()
                ts_id = str(item.get("TimeSheet_id") or item.get("timesheet_id") or "").strip()
                for r_idx, t in enumerate(self._tasks):
                    if (k_id and (str(t.get("kra_id") or t.get("id") or "") == k_id)) or (ts_id and str(t.get("timesheet_id") or "") == ts_id):
                        t_key = self._task_key(t, r_idx)
                        if t_key not in self._user_drafts:
                            self._user_drafts[t_key] = {}
                        rem = str(item.get("remark") or item.get("comment") or "").strip()
                        comp = str(item.get("task_completed") or "").strip()
                        if rem:
                            self._user_drafts[t_key]["comment"] = rem
                            t["comment"] = rem
                            t["remark"] = rem
                        if comp:
                            self._user_drafts[t_key]["task_completed"] = comp
                            t["task_completed"] = comp
                        item_done = _extract_task_done(item)
                        if item_done != "-":
                            self._user_drafts[t_key]["task_done"] = item_done

            self.set_submitted(False)
            if fresh_tasks:
                for ft in fresh_tasks:
                    k_id = str(ft.get("kra_id") or ft.get("id") or "").strip()
                    ts_id = str(ft.get("timesheet_id") or "").strip()
                    for item in data.get("saved_kra_list", []):
                        if (k_id and str(item.get("kra_id") or "") == k_id) or (ts_id and str(item.get("TimeSheet_id") or item.get("timesheet_id") or "") == ts_id):
                            if item.get("task_completed"):
                                ft["task_completed"] = str(item["task_completed"]).strip()
                            if item.get("remark") or item.get("comment"):
                                ft["comment"] = str(item.get("remark") or item.get("comment")).strip()
                                ft["remark"] = ft["comment"]
                            item_done = _extract_task_done(item)
                            if item_done != "-":
                                ft["task_done"] = item_done
                                ft["task_done_till_now"] = item_done
                self.set_tasks(fresh_tasks, date=submission_date)

            if hasattr(self, "buttons_container"):
                self.buttons_container.show()
            self.save_draft_btn.setEnabled(True)
            self.submit_btn.setEnabled(True)
            self.save_draft_btn.show()
            self.submit_btn.show()
            self.save_draft_btn.setText("Draft Saved ✓")
            self.save_draft_btn.setStyleSheet(self._btn_style_success())
            self._show_status("Draft saved successfully.", is_error=False)
            QTimer.singleShot(3500, self._reset_action_buttons)

        if self._tasks:
            self.task_saved.emit(self._tasks[0])

    def _handle_batch_error(self, is_draft: bool, err_msg: str) -> None:
        """Handle failed batch submission while preserving entered values."""
        logger.warning("AssignedTasksTable: batch error is_draft=%s: %s", is_draft, err_msg)
        self._is_submitting = False
        self.set_submitted(False)

        if hasattr(self, "buttons_container"):
            self.buttons_container.show()
        self.save_draft_btn.show()
        self.submit_btn.show()
        self.save_draft_btn.setEnabled(True)
        self.submit_btn.setEnabled(True)

        if is_draft:
            self.save_draft_btn.setText("Retry Draft ⚠️")
            self.save_draft_btn.setStyleSheet(self._btn_style_error())
        else:
            self.submit_btn.setText("Retry Submit ⚠️")
            self.submit_btn.setStyleSheet(self._btn_style_error())

        self._show_status(f"Error: {err_msg}", is_error=True)

    def _show_status(self, message: str, is_error: bool = False) -> None:
        """Display feedback status below table next to common buttons."""
        if not hasattr(self, "status_msg_label") or not self.status_msg_label:
            return
        color = "#dc2626" if is_error else "#059669"
        self.status_msg_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {color};")
        self.status_msg_label.setText(message)
        self.status_msg_label.setVisible(True)
        if not is_error:
            QTimer.singleShot(4000, self.status_msg_label.hide)

    def _reset_action_buttons(self) -> None:
        """Reset action buttons back to default styling."""
        self._is_submitting = False
        if self._is_submitted:
            self.save_draft_btn.hide()
            self.submit_btn.hide()
            if hasattr(self, "buttons_container"):
                self.buttons_container.hide()
        else:
            if hasattr(self, "buttons_container"):
                self.buttons_container.show()
            self.save_draft_btn.setEnabled(True)
            self.save_draft_btn.setText("Save as Draft")
            self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
            self.save_draft_btn.show()
            self.submit_btn.setEnabled(True)
            self.submit_btn.setText("Submit")
            self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            self.submit_btn.show()

    def _on_save_clicked(self, row: int = 0) -> None:
        """Backward-compatibility hook: delegate to submit_all_tasks."""
        self.submit_all_tasks(is_draft=False)

    def _handle_submit_success(self, row: int, msg: str, data: dict) -> None:
        """Legacy row handler for compatibility."""
        self._handle_batch_success(is_draft=False, msg=msg, data=data)

    def _handle_submit_error(self, row: int, err_msg: str) -> None:
        """Legacy row error handler for compatibility."""
        self._handle_batch_error(is_draft=False, err_msg=err_msg)

    @staticmethod
    def _draft_btn_style_default() -> str:
        """Return the default Save as Draft button stylesheet."""
        return (
            "QPushButton#SaveDraftButton {"
            "  background-color: #ffffff;"
            "  color: #1a73e8;"
            "  border: 1.5px solid #1a73e8;"
            "  border-radius: 6px;"
            "  padding: 7px 18px;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "  min-width: 95px;"
            "}"
            "QPushButton#SaveDraftButton:hover {"
            "  background-color: #f0f7ff;"
            "}"
            "QPushButton#SaveDraftButton:focus {"
            "  border: 2px solid #1a73e8;"
            "  background-color: #f0f7ff;"
            "  outline: none;"
            "}"
            "QPushButton#SaveDraftButton:pressed {"
            "  background-color: #e0effe;"
            "}"
            "QPushButton#SaveDraftButton:disabled {"
            "  background-color: #f8fafc;"
            "  color: #94a3b8;"
            "  border-color: #cbd5e1;"
            "}"
        )

    @staticmethod
    def _submit_btn_style_default() -> str:
        """Return the default Submit button stylesheet."""
        return (
            "QPushButton#SubmitTasksButton {"
            "  background-color: #1a73e8;"
            "  color: #ffffff;"
            "  border: 1.5px solid transparent;"
            "  border-radius: 6px;"
            "  padding: 7px 22px;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "  min-width: 85px;"
            "}"
            "QPushButton#SubmitTasksButton:hover {"
            "  background-color: #1557b0;"
            "}"
            "QPushButton#SubmitTasksButton:focus {"
            "  border: 2px solid #93c5fd;"
            "  outline: none;"
            "}"
            "QPushButton#SubmitTasksButton:pressed {"
            "  background-color: #0d47a1;"
            "}"
            "QPushButton#SubmitTasksButton:disabled {"
            "  background-color: #93bbf8;"
            "  color: #ffffff;"
            "}"
        )

    @staticmethod
    def _btn_style_success() -> str:
        """Return success state button stylesheet."""
        return (
            "QPushButton {"
            "  background-color: #ecfdf5;"
            "  color: #059669;"
            "  border: 1px solid #10b981;"
            "  border-radius: 6px;"
            "  padding: 7px 18px;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "}"
            "QPushButton:hover {"
            "  background-color: #d1fae5;"
            "}"
        )

    @staticmethod
    def _btn_style_error() -> str:
        """Return error/retry state button stylesheet."""
        return (
            "QPushButton {"
            "  background-color: #fef2f2;"
            "  color: #dc2626;"
            "  border: 1px solid #ef4444;"
            "  border-radius: 6px;"
            "  padding: 7px 18px;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "}"
            "QPushButton:hover {"
            "  background-color: #fee2e2;"
            "}"
        )

    @staticmethod
    def _save_btn_style_default() -> str:
        """Return the default Save button stylesheet (for backward compatibility)."""
        return AssignedTasksTable._submit_btn_style_default()

    def show_loading(self, date: Optional[str] = None) -> None:
        """Display a clean loading state in the table."""
        self.update_title(date=date)
        self.setUpdatesEnabled(False)
        self.setRowCount(1)
        self.setRowHeight(0, 60)
        loading_item = QTableWidgetItem("Loading KRA...")
        loading_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        loading_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.setItem(0, 0, loading_item)
        self.setSpan(0, 0, 1, len(self.COLUMN_CONFIG))
        self.setUpdatesEnabled(True)

    def show_error(self, message: Optional[str] = None, date: Optional[str] = None) -> None:
        """Display a non-blocking error notice in the table."""
        logger.warning("AssignTaskTable: unable to load KRA data: %s", message)
        self.update_title(date=date)
        self.setUpdatesEnabled(False)
        self.setRowCount(1)
        self.setRowHeight(0, 60)
        err_item = QTableWidgetItem("Unable to load KRA data.")
        err_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        err_item.setFlags(Qt.ItemFlag.NoItemFlags)
        if message:
            err_item.setToolTip(str(message))
        self.setItem(0, 0, err_item)
        self.setSpan(0, 0, 1, len(self.COLUMN_CONFIG))
        self.setUpdatesEnabled(True)
