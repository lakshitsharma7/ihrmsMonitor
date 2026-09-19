"""Assigned Tasks and KRA / Timesheet table widget for the iHRMS Monitor Dashboard."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
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
    border: 1.5px solid #cbd5e1;
    border-radius: 6px;
    gridline-color: #cbd5e1;
    font-size: 12px;
}

QTableWidget#AssignedTasksTable::item {
    padding: 6px 8px;
    color: #1e293b;
    border-right: 1px solid #cbd5e1;
    border-bottom: 1px solid #cbd5e1;
}

QTableWidget#AssignedTasksTable::item:alternate {
    background-color: #f8fafc;
}

QTableWidget#AssignedTasksTable::item:selected {
    background-color: #e2e8f0;
    color: #0f172a;
}

QHeaderView {
    background-color: #f1f5f9;
    border: none;
}

QHeaderView::section {
    background-color: #f1f5f9;
    color: #0f172a;
    font-weight: 700;
    font-size: 12px;
    padding: 8px 6px;
    border-top: none;
    border-left: none;
    border-right: 1px solid #cbd5e1;
    border-bottom: 2px solid #94a3b8;
}

QTableCornerButton::section {
    background-color: #f1f5f9;
    border-right: 1px solid #cbd5e1;
    border-bottom: 2px solid #94a3b8;
}

QScrollBar:horizontal {
    height: 10px;
    background: #f1f5f9;
    border-radius: 4px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #94a3b8;
    min-width: 24px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background: #64748b;
}

QScrollBar:vertical {
    width: 10px;
    background: #f1f5f9;
    border-radius: 4px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #94a3b8;
    min-height: 24px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #64748b;
}
"""


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

    COLUMN_CONFIG = [
        ("Name", 140, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        ("Description", 220, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        ("Category", 110, Qt.AlignmentFlag.AlignCenter),
        ("Target", 95, Qt.AlignmentFlag.AlignCenter),
        ("Measurement Criteria", 190, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        ("Weightage", 95, Qt.AlignmentFlag.AlignCenter),
        ("Task Done Till Now", 135, Qt.AlignmentFlag.AlignCenter),
        ("Task Completed", 120, Qt.AlignmentFlag.AlignCenter),
        ("Comment", 220, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        ("Action", 100, Qt.AlignmentFlag.AlignCenter),
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

        header = self.horizontalHeader()
        header.setFixedHeight(42)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(75)
        header.setStretchLastSection(False)

        # Set individual column headers with exact alignments and initial minimum widths
        for col_idx, (col_name, col_width, col_align) in enumerate(self.COLUMN_CONFIG):
            header_item = QTableWidgetItem(col_name)
            header_item.setTextAlignment(col_align)
            header_font = QFont()
            header_font.setBold(True)
            header_font.setPointSize(9)
            header_item.setFont(header_font)
            header_item.setToolTip(col_name)
            self.setHorizontalHeaderItem(col_idx, header_item)
            header.setSectionResizeMode(col_idx, QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(col_idx, col_width)

        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(42)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAlternatingRowColors(True)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        self.setMinimumHeight(200)

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
            empty_item = QTableWidgetItem("No assigned tasks found.")
            empty_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.setItem(0, 0, empty_item)
            self.setSpan(0, 0, 1, len(self.COLUMN_CONFIG))
            self.setUpdatesEnabled(True)
            return

        # Clear any spans
        self.clearSpans()

        # Non-negative numeric regex validator for Task Completed (e.g. 25, 10.5, 100)
        num_regex = QRegularExpression(r"^\d{0,6}(\.\d{0,2})?$")

        for row, task in enumerate(self._tasks):
            self.insertRow(row)

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

            # 1. Description (Read-only, Left-aligned)
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

            # 4. Measurement Criteria (Read-only, Left-aligned)
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

            # 7. Task Completed (Editable numeric QLineEdit, Centered)
            completed_item = QTableWidgetItem(task_completed)
            completed_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(row, 7, completed_item)

            comp_container = QWidget()
            comp_layout = QHBoxLayout(comp_container)
            comp_layout.setContentsMargins(4, 3, 4, 3)
            comp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            completed_edit = QLineEdit(task_completed)
            completed_edit.setPlaceholderText("0")
            completed_edit.setValidator(QRegularExpressionValidator(num_regex, completed_edit))
            completed_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            completed_edit.setStyleSheet(
                "QLineEdit {"
                "  background-color: #ffffff;"
                "  border: 1.5px solid #94a3b8;"
                "  border-radius: 4px;"
                "  padding: 4px 6px;"
                "  font-size: 12px;"
                "  font-weight: 500;"
                "  min-width: 65px;"
                "  max-width: 85px;"
                "}"
                "QLineEdit:hover {"
                "  border: 1.5px solid #64748b;"
                "}"
                "QLineEdit:focus {"
                "  border: 2px solid #1a73e8;"
                "  background-color: #f8faff;"
                "}"
            )
            completed_edit.textChanged.connect(
                lambda text, r=row: self._on_task_completed_changed(r, text)
            )
            comp_layout.addWidget(completed_edit)
            self.setCellWidget(row, 7, comp_container)

            # 8. Comment / Work Done (Editable text QLineEdit, Left-aligned)
            comment_item = QTableWidgetItem(comment)
            comment_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(row, 8, comment_item)

            comment_container = QWidget()
            comment_layout = QHBoxLayout(comment_container)
            comment_layout.setContentsMargins(4, 3, 4, 3)

            comment_edit = QLineEdit(comment)
            comment_edit.setPlaceholderText("Enter comments / work details...")
            comment_edit.setStyleSheet(
                "QLineEdit {"
                "  background-color: #ffffff;"
                "  border: 1.5px solid #94a3b8;"
                "  border-radius: 4px;"
                "  padding: 4px 8px;"
                "  font-size: 12px;"
                "}"
                "QLineEdit:hover {"
                "  border: 1.5px solid #64748b;"
                "}"
                "QLineEdit:focus {"
                "  border: 2px solid #1a73e8;"
                "  background-color: #f8faff;"
                "}"
            )
            comment_edit.textChanged.connect(
                lambda text, r=row: self._on_comment_changed(r, text)
            )
            comment_layout.addWidget(comment_edit)
            self.setCellWidget(row, 8, comment_container)

            # 9. Action (Save Button, Centered)
            action_container = QWidget()
            action_layout = QHBoxLayout(action_container)
            action_layout.setContentsMargins(4, 3, 4, 3)
            action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            save_btn = QPushButton("Save")
            save_btn.setToolTip("Save timesheet entry for this KRA task")
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            save_btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #1a73e8;"
                "  color: #ffffff;"
                "  border: none;"
                "  border-radius: 4px;"
                "  padding: 5px 14px;"
                "  font-size: 11px;"
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
            save_btn.clicked.connect(lambda _, r=row: self._on_save_clicked(r))
            action_layout.addWidget(save_btn)
            self.setCellWidget(row, 9, action_container)

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
        if comp_edit and "border: 1.5px solid #d93025" in comp_edit.styleSheet():
            comp_edit.setStyleSheet(
                "QLineEdit {"
                "  background-color: #ffffff;"
                "  border: 1.5px solid #94a3b8;"
                "  border-radius: 4px;"
                "  padding: 4px 6px;"
                "  font-size: 12px;"
                "  font-weight: 500;"
                "  min-width: 65px;"
                "  max-width: 85px;"
                "}"
                "QLineEdit:focus {"
                "  border: 2px solid #1a73e8;"
                "  background-color: #f8faff;"
                "}"
            )
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
        if comment_edit and "border: 1.5px solid #d93025" in comment_edit.styleSheet():
            comment_edit.setStyleSheet(
                "QLineEdit {"
                "  background-color: #ffffff;"
                "  border: 1.5px solid #94a3b8;"
                "  border-radius: 4px;"
                "  padding: 4px 8px;"
                "  font-size: 12px;"
                "}"
                "QLineEdit:focus {"
                "  border: 2px solid #1a73e8;"
                "  background-color: #f8faff;"
                "}"
            )
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
                    completed_edit.setStyleSheet(
                        "QLineEdit {"
                        "  background-color: #fff5f5;"
                        "  border: 1.5px solid #d93025;"
                        "  border-radius: 4px;"
                        "  padding: 4px 6px;"
                        "  font-size: 12px;"
                        "  min-width: 65px;"
                        "  max-width: 85px;"
                        "}"
                    )
                    completed_edit.setToolTip("Task Completed cannot be negative.")
                    completed_edit.setFocus()
                    return
            except ValueError:
                completed_edit.setStyleSheet(
                    "QLineEdit {"
                    "  background-color: #fff5f5;"
                    "  border: 1.5px solid #d93025;"
                    "  border-radius: 4px;"
                    "  padding: 4px 6px;"
                    "  font-size: 12px;"
                    "  min-width: 65px;"
                    "  max-width: 85px;"
                    "}"
                )
                completed_edit.setToolTip("Please enter a valid number.")
                completed_edit.setFocus()
                return
        else:
            comp_val_str = "0"

        # 2. Validate Comment
        comment_text = comment_edit.text().strip()
        if not comment_text:
            comment_edit.setStyleSheet(
                "QLineEdit {"
                "  background-color: #fff5f5;"
                "  border: 1.5px solid #d93025;"
                "  border-radius: 4px;"
                "  padding: 4px 8px;"
                "  font-size: 12px;"
                "}"
            )
            comment_edit.setToolTip("Please enter comments before saving.")
            comment_edit.setFocus()
            return

        # Restore normal styling
        completed_edit.setStyleSheet(
            "QLineEdit {"
            "  background-color: #ffffff;"
            "  border: 1.5px solid #94a3b8;"
            "  border-radius: 4px;"
            "  padding: 4px 6px;"
            "  font-size: 12px;"
            "  font-weight: 500;"
            "  min-width: 65px;"
            "  max-width: 85px;"
            "}"
            "QLineEdit:focus {"
            "  border: 2px solid #1a73e8;"
            "  background-color: #f8faff;"
            "}"
        )
        completed_edit.setToolTip("")

        comment_edit.setStyleSheet(
            "QLineEdit {"
            "  background-color: #ffffff;"
            "  border: 1.5px solid #94a3b8;"
            "  border-radius: 4px;"
            "  padding: 4px 8px;"
            "  font-size: 12px;"
            "}"
            "QLineEdit:focus {"
            "  border: 2px solid #1a73e8;"
            "  background-color: #f8faff;"
            "}"
        )
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
                "  border-radius: 4px;"
                "  padding: 5px 14px;"
                "  font-size: 11px;"
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
                    # Re-fetch the fresh KRA data to confirm persisted values from backend
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

        # Find matching task in fresh tasks or update current row
        if row < len(self._tasks):
            task = self._tasks[row]
            task_completed_val = saved_info.get("task_completed", "")
            comment_val = saved_info.get("comment", "")

            # If fresh tasks returned from backend, check for updated task
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
                    "  background-color: #e6f4ea;"
                    "  color: #137333;"
                    "  border: 1px solid #34a853;"
                    "  border-radius: 4px;"
                    "  padding: 5px 14px;"
                    "  font-size: 11px;"
                    "  font-weight: 600;"
                    "  min-width: 65px;"
                    "}"
                    "QPushButton:hover {"
                    "  background-color: #ceead6;"
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
                    "  background-color: #fce8e6;"
                    "  color: #c5221f;"
                    "  border: 1px solid #ea4335;"
                    "  border-radius: 4px;"
                    "  padding: 5px 14px;"
                    "  font-size: 11px;"
                    "  font-weight: 600;"
                    "  min-width: 65px;"
                    "}"
                    "QPushButton:hover {"
                    "  background-color: #fad2cf;"
                    "}"
                )

    def _reset_save_button(self, save_btn: QPushButton) -> None:
        """Reset save button back to default state."""
        if save_btn and save_btn.text() == "Saved ✓":
            save_btn.setText("Save")
            save_btn.setToolTip("Save timesheet entry for this KRA task")
            save_btn.setStyleSheet(
                "QPushButton {"
                "  background-color: #1a73e8;"
                "  color: #ffffff;"
                "  border: none;"
                "  border-radius: 4px;"
                "  padding: 5px 14px;"
                "  font-size: 11px;"
                "  font-weight: 600;"
                "  min-width: 65px;"
                "}"
                "QPushButton:hover {"
                "  background-color: #1557b0;"
                "}"
            )

    def show_loading(self) -> None:
        """Display a clean loading state in the table."""
        self.setUpdatesEnabled(False)
        self.setRowCount(1)
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


