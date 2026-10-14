"""Assigned Tasks and KRA / Timesheet table widget for the iHRMS Monitor Dashboard."""

from __future__ import annotations

from datetime import date, datetime
import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QRegularExpressionValidator
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
    QWidget,
)

from utils.logger import get_logger

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
    padding: 8px 10px;
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
    font-size: 12px;
    padding: 8px 6px;
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

QScrollBar:horizontal {
    height: 8px;
    background: #f1f5f9;
    border-radius: 4px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #cbd5e1;
    min-width: 24px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background: #94a3b8;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

QScrollBar::vertical {
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
    "  padding: 5px 8px;"
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
    "  padding: 5px 8px;"
    "  font-size: 12px;"
    "  color: #991b1b;"
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
    if raw_date is None or not str(raw_date).strip():
        return datetime.now().strftime("%d %B %Y")

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
        ("S.No.",                  55, Qt.AlignmentFlag.AlignCenter),
        ("Name",                 140, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Description",          180, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Category",             100, Qt.AlignmentFlag.AlignCenter),
        ("Target",                80, Qt.AlignmentFlag.AlignCenter),
        ("Measurement Criteria", 165, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Weightage",             95, Qt.AlignmentFlag.AlignCenter),
        ("Task Done Till Now",   145, Qt.AlignmentFlag.AlignCenter),
        ("Task Completed",       130, Qt.AlignmentFlag.AlignCenter),
        ("Comment",              220, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
    ]

    task_saved = Signal(dict)  # Emitted when a timesheet is saved successfully

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._tasks: List[Dict[str, Any]] = []
        self._is_submitting: bool = False
        self._edited_rows: set[int] = set()

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
            "    font-size: 13px;"
            "    font-weight: 600;"
            "    padding: 2px 0px 6px 0px;"
            "}"
        )
        self._current_date: str = ""
        self.update_title()

        # ── Bottom Action Controls ──────────────────────────────────────────
        self.actions_widget = QWidget()
        self.actions_widget.setObjectName("TaskTableActionsWidget")
        actions_layout = QHBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(4, 8, 4, 4)
        actions_layout.setSpacing(10)

        self.status_msg_label = QLabel("", self.actions_widget)
        self.status_msg_label.setStyleSheet("font-size: 12px; font-weight: 500;")
        self.status_msg_label.setVisible(False)
        actions_layout.addWidget(self.status_msg_label)

        actions_layout.addStretch(1)

        self.save_draft_btn = QPushButton("Save as Draft", self.actions_widget)
        self.save_draft_btn.setObjectName("SaveDraftButton")
        self.save_draft_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
        self.save_draft_btn.clicked.connect(lambda: self.submit_all_tasks(is_draft=True))
        actions_layout.addWidget(self.save_draft_btn)

        self.submit_btn = QPushButton("Submit", self.actions_widget)
        self.submit_btn.setObjectName("SubmitTasksButton")
        self.submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_btn.setStyleSheet(self._submit_btn_style_default())
        self.submit_btn.clicked.connect(lambda: self.submit_all_tasks(is_draft=False))
        actions_layout.addWidget(self.submit_btn)

        # ── Header ────────────────────────────────────────────────────────────
        header = self.horizontalHeader()
        header.setFixedHeight(40)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(50)
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
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.setAutoScroll(False)

        self.setMinimumWidth(600)
        self.setMinimumHeight(120)

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible) -> None:
        """
        Preserve horizontal scroll position so item navigation/updates do not jump horizontally.
        Allows vertical scrolling to work normally.
        """
        prev_h = self.horizontalScrollBar().value()
        super().scrollTo(index, hint)
        if self.horizontalScrollBar().value() != prev_h:
            self.horizontalScrollBar().setValue(prev_h)

    def resizeEvent(self, event) -> None:
        """Dynamically adjust column widths when the table container resizes."""
        super().resizeEvent(event)
        self._adjust_column_widths()

    def _adjust_column_widths(self) -> None:
        """Responsively adjust column widths to fill available width or allow clean scrolling."""
        if self.columnCount() != len(self.COLUMN_CONFIG):
            return

        prev_h = self.horizontalScrollBar().value()
        viewport_width = self.viewport().width()
        base_widths = [cfg[1] for cfg in self.COLUMN_CONFIG]
        total_base = sum(base_widths)

        # Stretchable text columns: Name (1), Description (2), Measurement Criteria (5), Comment (9)
        stretchable = [1, 2, 5, 9]
        weights = {1: 1, 2: 2, 5: 2, 9: 2}
        total_weight = sum(weights.values())

        if viewport_width > total_base:
            extra = viewport_width - total_base
            for col_idx in range(len(self.COLUMN_CONFIG)):
                if col_idx in stretchable:
                    added = int(extra * weights[col_idx] / total_weight)
                    self.setColumnWidth(col_idx, base_widths[col_idx] + added)
                else:
                    self.setColumnWidth(col_idx, base_widths[col_idx])
        else:
            for col_idx in range(len(self.COLUMN_CONFIG)):
                self.setColumnWidth(col_idx, base_widths[col_idx])

        if self.horizontalScrollBar().value() != prev_h:
            self.horizontalScrollBar().setValue(prev_h)

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

    def _resolve_employee_info(self, tasks: Optional[List[Dict[str, Any]]] = None) -> tuple[str, str]:
        """
        Dynamically resolve (employee_name, employee_code) from tasks, session, or stored credentials.
        """
        emp_name = ""
        emp_code = ""

        # 1. Check tasks data if available
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
                        or ""
                    ).strip()
            if emp_name and emp_code:
                break

        # 2. Check SessionService
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

        # 3. Check SessionStore
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

        # 4. Check QSettings
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
        tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Dynamically update the centered heading above the table."""
        resolved_name, resolved_code = self._resolve_employee_info(tasks=tasks)
        if name:
            resolved_name = name
        if code:
            resolved_code = code

        date_val = date
        if not date_val:
            task_list = tasks if tasks is not None else self._tasks
            for t in task_list:
                d = str(t.get("date") or t.get("assigned_date") or "").strip()
                if d:
                    date_val = d
                    break
        if not date_val:
            date_val = getattr(self, "_current_date", "") or datetime.now().strftime("%Y-%m-%d")

        self._current_date = str(date_val)
        formatted_date = format_task_date(date_val)

        if resolved_name and resolved_code:
            heading = f"Task for {resolved_name} ({resolved_code}) on {formatted_date}"
        elif resolved_name:
            heading = f"Task for {resolved_name} on {formatted_date}"
        elif resolved_code:
            heading = f"Task for {resolved_code} on {formatted_date}"
        else:
            heading = f"Task on {formatted_date}"

        self.title_label.setText(heading)

    def set_tasks(self, tasks: List[Dict[str, Any]], date: Optional[str] = None) -> None:
        """Display assigned KRA tasks dynamically from API response."""
        prev_h_scroll = self.horizontalScrollBar().value()
        prev_v_scroll = self.verticalScrollBar().value()

        # Update dynamic heading above table
        self.update_title(date=date, tasks=tasks)

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
        self._tasks = list(tasks or [])
        self._edited_rows.clear()

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
            self.setUpdatesEnabled(True)
            return

        self.save_draft_btn.setEnabled(True)
        self.submit_btn.setEnabled(True)

        # Clear any spans
        self.clearSpans()

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
            task_done = str(task.get("task_done") or task.get("task_done_till_now") or "-").strip()
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

            # 3. Category (Read-only, Centered)
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

            # 5. Measurement Criteria (Read-only, Left-aligned, Wrapped)
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

            # ── Col 8: Task Completed — editable numeric QLineEdit ────────────
            comp_container = QWidget(self)
            comp_layout = QHBoxLayout(comp_container)
            comp_layout.setContentsMargins(6, 4, 6, 4)
            comp_layout.setSpacing(0)
            comp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            completed_edit = StableLineEdit(task_completed, comp_container, table=self)
            completed_edit.setPlaceholderText("0")
            completed_edit.setValidator(QRegularExpressionValidator(num_regex, completed_edit))
            completed_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            completed_edit.setStyleSheet(_LE_NORMAL)
            completed_edit.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            completed_edit.textChanged.connect(
                lambda text, r=row: self._on_task_completed_changed(r, text)
            )
            comp_layout.addWidget(completed_edit)
            self.setCellWidget(row, 8, comp_container)

            # ── Col 9: Comment — editable text QLineEdit ──────────────────────
            comment_container = QWidget(self)
            comment_layout = QHBoxLayout(comment_container)
            comment_layout.setContentsMargins(6, 4, 6, 4)
            comment_layout.setSpacing(0)

            comment_edit = StableLineEdit(comment, comment_container, table=self)
            comment_edit.setPlaceholderText("Enter comments / work details...")
            comment_edit.setStyleSheet(_LE_NORMAL)
            comment_edit.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            comment_edit.textChanged.connect(
                lambda text, r=row: self._on_comment_changed(r, text)
            )
            comment_layout.addWidget(comment_edit)
            self.setCellWidget(row, 9, comment_container)

        self.setMinimumHeight(min(450, 48 + len(self._tasks) * 54))
        self._adjust_column_widths()
        self.horizontalScrollBar().setValue(prev_h_scroll)
        self.verticalScrollBar().setValue(prev_v_scroll)
        self.setUpdatesEnabled(True)

        if focus_info:
            r, c, text, cursor_pos = focus_info
            if r < self.rowCount():
                le = self._get_line_edit(r, c)
                if le:
                    le.setText(text)
                    le.setFocus()
                    le.setCursorPosition(cursor_pos)

    def _on_task_completed_changed(self, row: int, text: str) -> None:
        """Synchronize backing task state when user edits Task Completed."""
        val = text.strip()
        self._edited_rows.add(row)
        if row < len(self._tasks):
            self._tasks[row]["task_completed"] = val

        prev_h = self.horizontalScrollBar().value()
        item = self.item(row, 8)
        if item and item.text() != val:
            item.setText(val)
            if self.horizontalScrollBar().value() != prev_h:
                self.horizontalScrollBar().setValue(prev_h)

        # Clear error styling if active
        comp_edit = self._get_line_edit(row, 8)
        if comp_edit and "border: 1.5px solid #ef4444" in comp_edit.styleSheet():
            comp_edit.setStyleSheet(_LE_NORMAL)
            comp_edit.setToolTip("")

    def _on_comment_changed(self, row: int, text: str) -> None:
        """Synchronize backing task state when user edits Comment."""
        self._edited_rows.add(row)
        if row < len(self._tasks):
            self._tasks[row]["comment"] = text
            self._tasks[row]["remark"] = text

        prev_h = self.horizontalScrollBar().value()
        item = self.item(row, 9)
        if item and item.text() != text:
            item.setText(text)
            if self.horizontalScrollBar().value() != prev_h:
                self.horizontalScrollBar().setValue(prev_h)

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
            return str(self._tasks[row].get("task_completed") or "0").strip()
        return "0"

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
            self._show_status("Submitting timesheet...", is_error=False)

        # 4. Assemble payload
        rows_to_include = sorted(candidate_rows) if not is_draft else list(range(len(self._tasks)))
        kra_list: List[Dict[str, str]] = []
        additional_tasks_to_save: List[tuple[str, str, int]] = []
        resolved_date = ""

        for r in rows_to_include:
            if r >= len(self._tasks):
                continue
            task = self._tasks[r]
            d = str(task.get("date") or "").strip()
            if d and not resolved_date:
                resolved_date = d

            comm_val = self._get_comment(r)
            comp_val = self._get_task_completed(r) or "0"

            if bool(task.get("is_additional", False)):
                additional_tasks_to_save.append((
                    comm_val,
                    d or resolved_date,
                    1 if comp_val in ("1", "100") else 0
                ))
            else:
                kra_list.append({
                    "TimeSheet_id": str(task.get("timesheet_id") or ""),
                    "kra_id": str(task.get("kra_id") or task.get("id") or ""),
                    "remark": comm_val,
                    "task_completed": comp_val,
                })

        submit_status_val = "0" if is_draft else "1"

        def worker():
            from services.task_service import TaskService
            svc = TaskService()
            try:
                for add_comm, add_date, add_status in additional_tasks_to_save:
                    svc.save_additional_task(task=add_comm, date=add_date, status=add_status)

                ok = True
                msg = ""
                res = None
                if kra_list:
                    ok, msg, res = svc.save_time_sheet(
                        kra_list=kra_list,
                        date=resolved_date,
                        submit_status=submit_status_val,
                    )

                if ok:
                    fresh_tasks = svc.fetch_assigned_tasks(date=resolved_date, force=True)
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
        if fresh_tasks:
            for ft in fresh_tasks:
                ft_kra_id = str(ft.get("kra_id") or ft.get("id") or "")
                for local_t in self._tasks:
                    local_k_id = str(local_t.get("kra_id") or local_t.get("id") or "")
                    if ft_kra_id and ft_kra_id == local_k_id:
                        if ft.get("timesheet_id"):
                            local_t["timesheet_id"] = str(ft["timesheet_id"])
                        break

        if self._tasks:
            self.task_saved.emit(self._tasks[0])

        if is_draft:
            self.save_draft_btn.setEnabled(True)
            self.submit_btn.setEnabled(True)
            self.save_draft_btn.setText("Draft Saved ✓")
            self.save_draft_btn.setStyleSheet(self._btn_style_success())
            self._show_status("Draft saved successfully.", is_error=False)
        else:
            self.submit_btn.setEnabled(True)
            self.save_draft_btn.setEnabled(True)
            self.submit_btn.setText("Submitted ✓")
            self.submit_btn.setStyleSheet(self._btn_style_success())
            self._show_status("Timesheet submitted successfully.", is_error=False)

        QTimer.singleShot(3500, self._reset_action_buttons)

    def _handle_batch_error(self, is_draft: bool, err_msg: str) -> None:
        """Handle failed batch submission while preserving entered values."""
        logger.warning("AssignedTasksTable: batch error is_draft=%s: %s", is_draft, err_msg)
        self._is_submitting = False
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
        self.save_draft_btn.setEnabled(True)
        self.submit_btn.setEnabled(True)
        self.save_draft_btn.setText("Save as Draft")
        self.submit_btn.setText("Submit")
        self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
        self.submit_btn.setStyleSheet(self._submit_btn_style_default())

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
            "  border: none;"
            "  border-radius: 6px;"
            "  padding: 7px 22px;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "  min-width: 85px;"
            "}"
            "QPushButton#SubmitTasksButton:hover {"
            "  background-color: #1557b0;"
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
