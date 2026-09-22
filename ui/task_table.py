"""Assigned Tasks and KRA / Timesheet table widget for the iHRMS Monitor Dashboard."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QHBoxLayout,
    QHeaderView,
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
    padding: 9px 10px;
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


class TaskTableSignals(QObject):
    """Qt signals for asynchronous timesheet submit/save operations."""

    submit_success = Signal(int, str, dict)  # row_idx, message, payload_data
    submit_error = Signal(int, str)  # row_idx, error_message


class AssignedTasksTable(QTableWidget):
    """
    Dynamic KRA / Assigned Tasks and Timesheet Entry Table.

    Columns:
        0. Name
        1. Description
        2. Category
        3. Target
        4. Measurement Criteria
        5. Weightage
        6. Task Done Till Now
        7. Task Completed (Editable numeric QLineEdit)
        8. Comment (Editable text QLineEdit)
        9. Action (Save button)
    """

    # Column config: (header_label, initial_width_px, header_alignment)
    COLUMN_CONFIG = [
        ("Name",                 160, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Description",          220, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Category",             110, Qt.AlignmentFlag.AlignCenter),
        ("Target",                90, Qt.AlignmentFlag.AlignCenter),
        ("Measurement Criteria", 190, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Weightage",             90, Qt.AlignmentFlag.AlignCenter),
        ("Task Done Till Now",   130, Qt.AlignmentFlag.AlignCenter),
        ("Task Completed",       130, Qt.AlignmentFlag.AlignCenter),
        ("Comment",              220, Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter),
        ("Action",               110, Qt.AlignmentFlag.AlignCenter),
    ]

    task_saved = Signal(dict)  # Emitted when a timesheet is saved successfully

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._tasks: List[Dict[str, Any]] = []
        self._signals = TaskTableSignals()
        self._signals.submit_success.connect(self._handle_submit_success)
        self._signals.submit_error.connect(self._handle_submit_error)

        self.setObjectName("AssignedTasksTable")
        self.setStyleSheet(TABLE_STYLESHEET)

        self.setColumnCount(len(self.COLUMN_CONFIG))
        self.setShowGrid(True)
        self.setWordWrap(True)

        # ── Header ────────────────────────────────────────────────────────────
        header = self.horizontalHeader()
        header.setFixedHeight(40)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(70)
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

        self.setMinimumWidth(600)
        self.setMinimumHeight(120)

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

    def set_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """Display assigned KRA tasks dynamically from API response."""
        self.setUpdatesEnabled(False)
        self.setRowCount(0)
        self._tasks = list(tasks or [])

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
            self.setUpdatesEnabled(True)
            return

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

            # 0. Name (Read-only, Left-aligned)
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(name)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 0, name_item)

            # 1. Description (Read-only, Left-aligned, Wrapped)
            desc_item = QTableWidgetItem(desc)
            desc_item.setToolTip(desc)
            desc_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            desc_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 1, desc_item)

            # 2. Category (Read-only, Centered)
            cat_item = QTableWidgetItem(category)
            cat_item.setToolTip(category)
            cat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 2, cat_item)

            # 3. Target (Read-only, Centered)
            target_item = QTableWidgetItem(target)
            target_item.setToolTip(target)
            target_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            target_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 3, target_item)

            # 4. Measurement Criteria (Read-only, Left-aligned, Wrapped)
            crit_item = QTableWidgetItem(criteria)
            crit_item.setToolTip(criteria)
            crit_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            crit_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 4, crit_item)

            # 5. Weightage (Read-only, Centered)
            weight_item = QTableWidgetItem(weight)
            weight_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            weight_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 5, weight_item)

            # 6. Task Done Till Now (Read-only, Centered)
            done_item = QTableWidgetItem(task_done)
            done_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            done_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 6, done_item)

            # ── Col 7: Task Completed — editable numeric QLineEdit ────────────
            comp_container = QWidget()
            comp_layout = QHBoxLayout(comp_container)
            comp_layout.setContentsMargins(6, 4, 6, 4)
            comp_layout.setSpacing(0)
            comp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            completed_edit = QLineEdit(task_completed)
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
            self.setCellWidget(row, 7, comp_container)

            # ── Col 8: Comment — editable text QLineEdit ──────────────────────
            comment_container = QWidget()
            comment_layout = QHBoxLayout(comment_container)
            comment_layout.setContentsMargins(6, 4, 6, 4)
            comment_layout.setSpacing(0)

            comment_edit = QLineEdit(comment)
            comment_edit.setPlaceholderText("Enter comments / work details...")
            comment_edit.setStyleSheet(_LE_NORMAL)
            comment_edit.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            comment_edit.textChanged.connect(
                lambda text, r=row: self._on_comment_changed(r, text)
            )
            comment_layout.addWidget(comment_edit)
            self.setCellWidget(row, 8, comment_container)

            # ── Col 9: Action — Save button ───────────────────────────────────
            action_container = QWidget()
            action_layout = QHBoxLayout(action_container)
            action_layout.setContentsMargins(6, 4, 6, 4)
            action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            save_btn = QPushButton("Save")
            save_btn.setToolTip("Save timesheet entry for this KRA task")
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            save_btn.setStyleSheet(self._save_btn_style_default())
            save_btn.clicked.connect(lambda _, r=row: self._on_save_clicked(r))
            action_layout.addWidget(save_btn)
            self.setCellWidget(row, 9, action_container)

        self.setMinimumHeight(min(450, 42 + len(self._tasks) * 54))
        self.setUpdatesEnabled(True)

    def _on_task_completed_changed(self, row: int, text: str) -> None:
        """Synchronize backing task state when user edits Task Completed."""
        val = text.strip()
        if row < len(self._tasks):
            self._tasks[row]["task_completed"] = val
        if self.item(row, 7):
            self.item(row, 7).setText(val)

        # Clear error styling if active
        comp_edit = self._get_line_edit(row, 7)
        if comp_edit and "border: 1.5px solid #ef4444" in comp_edit.styleSheet():
            comp_edit.setStyleSheet(_LE_NORMAL)
            comp_edit.setToolTip("")

    def _on_comment_changed(self, row: int, text: str) -> None:
        """Synchronize backing task state when user edits Comment."""
        if row < len(self._tasks):
            self._tasks[row]["comment"] = text
            self._tasks[row]["remark"] = text
        if self.item(row, 8):
            self.item(row, 8).setText(text)

        # Clear error styling if active
        comment_edit = self._get_line_edit(row, 8)
        if comment_edit and "border: 1.5px solid #ef4444" in comment_edit.styleSheet():
            comment_edit.setStyleSheet(_LE_NORMAL)
            comment_edit.setToolTip("")

    def _on_save_clicked(self, row: int) -> None:
        """Validate and save KRA timesheet row data to the backend API."""
        if row >= len(self._tasks):
            return

        task = self._tasks[row]
        completed_edit = self._get_line_edit(row, 7)
        comment_edit = self._get_line_edit(row, 8)
        action_widget = self.cellWidget(row, 9)

        if not completed_edit or not comment_edit:
            return

        # 1. Validate Task Completed numeric input
        comp_val_str = completed_edit.text().strip()
        if comp_val_str:
            try:
                num_val = float(comp_val_str)
                if num_val < 0:
                    completed_edit.setStyleSheet(_LE_ERROR)
                    completed_edit.setToolTip("Task Completed cannot be negative.")
                    completed_edit.setFocus()
                    return
            except ValueError:
                completed_edit.setStyleSheet(_LE_ERROR)
                completed_edit.setToolTip("Please enter a valid number.")
                completed_edit.setFocus()
                return
        else:
            comp_val_str = "0"

        # 2. Validate Comment
        comment_text = comment_edit.text().strip()
        if not comment_text:
            comment_edit.setStyleSheet(_LE_ERROR)
            comment_edit.setToolTip("Please enter comments before saving.")
            comment_edit.setFocus()
            return

        # Restore normal styling
        completed_edit.setStyleSheet(_LE_NORMAL)
        completed_edit.setToolTip("")
        comment_edit.setStyleSheet(_LE_NORMAL)
        comment_edit.setToolTip("")

        save_btn = action_widget.findChild(QPushButton) if action_widget else None
        if save_btn:
            save_btn.setEnabled(False)
            save_btn.setText("Saving...")
            save_btn.setToolTip("Saving timesheet...")
            save_btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #93bbf8;"
                "  color: #ffffff;"
                "  border: none;"
                "  border-radius: 6px;"
                "  padding: 6px 16px;"
                "  font-size: 12px;"
                "  font-weight: 600;"
                "  min-width: 65px;"
                "}"
            )

        is_additional = bool(task.get("is_additional", False))
        date_val = str(task.get("date") or "").strip()
        kra_id_val = str(task.get("kra_id") or task.get("id") or "")
        timesheet_id_val = str(task.get("timesheet_id") or "")

        def worker():
            from services.task_service import TaskService
            svc = TaskService()
            try:
                if is_additional:
                    ok, msg, res = svc.save_additional_task(
                        task=comment_text,
                        date=date_val,
                        status=1 if comp_val_str in ("1", "100") else 0,
                    )
                else:
                    kra_item = {
                        "TimeSheet_id": timesheet_id_val,
                        "kra_id": kra_id_val,
                        "remark": comment_text,
                        "task_completed": comp_val_str,
                    }
                    ok, msg, res = svc.save_time_sheet(
                        kra_list=[kra_item],
                        date=date_val,
                        submit_status=comp_val_str,
                    )

                if ok:
                    fresh_tasks = svc.fetch_assigned_tasks(date=date_val, force=True)
                    self._signals.submit_success.emit(
                        row,
                        msg,
                        {
                            "response": res or {},
                            "fresh_tasks": fresh_tasks,
                            "saved_task": {
                                "kra_id": kra_id_val,
                                "timesheet_id": timesheet_id_val,
                                "task_completed": comp_val_str,
                                "comment": comment_text,
                            },
                        },
                    )
                else:
                    self._signals.submit_error.emit(row, msg)
            except Exception as e:
                self._signals.submit_error.emit(row, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_submit_success(self, row: int, msg: str, data: dict) -> None:
        """Update UI state and internal cache on successful timesheet submission."""
        saved_info = data.get("saved_task", {})
        fresh_tasks = data.get("fresh_tasks", [])

        if row < len(self._tasks):
            task = self._tasks[row]
            task_completed_val = saved_info.get("task_completed", "")
            comment_val = saved_info.get("comment", "")

            if fresh_tasks:
                for ft in fresh_tasks:
                    if ft.get("kra_id") and ft.get("kra_id") == task.get("kra_id"):
                        task_completed_val = str(ft.get("task_completed") or task_completed_val)
                        comment_val = str(ft.get("comment") or ft.get("remark") or comment_val)
                        task.update(ft)
                        break

            task["task_completed"] = task_completed_val
            task["comment"] = comment_val
            task["remark"] = comment_val

            completed_edit = self._get_line_edit(row, 7)
            comment_edit = self._get_line_edit(row, 8)
            if completed_edit:
                completed_edit.setText(task_completed_val)
            if comment_edit:
                comment_edit.setText(comment_val)

            if self.item(row, 7):
                self.item(row, 7).setText(task_completed_val)
            if self.item(row, 8):
                self.item(row, 8).setText(comment_val)

            raw_res = data.get("response", {})
            if isinstance(raw_res, dict):
                ts_id = raw_res.get("TimeSheet_id") or raw_res.get("timesheet_id") or raw_res.get("id")
                if ts_id:
                    task["timesheet_id"] = str(ts_id)

            self.task_saved.emit(task)

        action_widget = self.cellWidget(row, 9)
        if action_widget:
            save_btn = action_widget.findChild(QPushButton)
            if save_btn:
                save_btn.setEnabled(True)
                save_btn.setText("Saved ✓")
                save_btn.setToolTip("Timesheet saved successfully.")
                save_btn.setStyleSheet(
                    "QPushButton {"
                    "  background-color: #ecfdf5;"
                    "  color: #059669;"
                    "  border: 1px solid #10b981;"
                    "  border-radius: 6px;"
                    "  padding: 6px 16px;"
                    "  font-size: 12px;"
                    "  font-weight: 600;"
                    "  min-width: 65px;"
                    "}"
                    "QPushButton:hover {"
                    "  background-color: #d1fae5;"
                    "}"
                )

                QTimer.singleShot(3000, lambda btn=save_btn: self._reset_save_button(btn))

    def _handle_submit_error(self, row: int, err_msg: str) -> None:
        """Update UI to show retry state on error while preserving user input."""
        logger.warning("AssignTaskTable: unable to save timesheet for row %d: %s", row, err_msg)
        action_widget = self.cellWidget(row, 9)
        if action_widget:
            save_btn = action_widget.findChild(QPushButton)
            if save_btn:
                save_btn.setEnabled(True)
                save_btn.setText("Retry ⚠️")
                save_btn.setToolTip(f"Unable to save changes ({err_msg}). Click to retry.")
                save_btn.setStyleSheet(
                    "QPushButton {"
                    "  background-color: #fef2f2;"
                    "  color: #dc2626;"
                    "  border: 1px solid #ef4444;"
                    "  border-radius: 6px;"
                    "  padding: 6px 16px;"
                    "  font-size: 12px;"
                    "  font-weight: 600;"
                    "  min-width: 65px;"
                    "}"
                    "QPushButton:hover {"
                    "  background-color: #fee2e2;"
                    "}"
                )

    def _reset_save_button(self, save_btn: QPushButton) -> None:
        """Reset save button back to default state after success timeout."""
        if save_btn and save_btn.text() == "Saved ✓":
            save_btn.setText("Save")
            save_btn.setToolTip("Save timesheet entry for this KRA task")
            save_btn.setStyleSheet(self._save_btn_style_default())

    @staticmethod
    def _save_btn_style_default() -> str:
        """Return the default Save button stylesheet."""
        return (
            "QPushButton {"
            "  background-color: #1a73e8;"
            "  color: #ffffff;"
            "  border: none;"
            "  border-radius: 6px;"
            "  padding: 6px 16px;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "  min-width: 65px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #1557b0;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #0d47a1;"
            "}"
            "QPushButton:disabled {"
            "  background-color: #93bbf8;"
            "  color: #ffffff;"
            "}"
        )

    def show_loading(self) -> None:
        """Display a clean loading state in the table."""
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

    def show_error(self, message: Optional[str] = None) -> None:
        """Display a non-blocking error notice in the table."""
        logger.warning("AssignTaskTable: unable to load KRA data: %s", message)
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
