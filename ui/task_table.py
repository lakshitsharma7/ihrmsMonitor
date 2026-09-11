"""Assigned Tasks and KRA table widget for the iHRMS Monitor Dashboard."""

from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)


class AssignedTasksTable(QTableWidget):
    """
    Assigned Tasks / KRAs table.

    Columns:
        1. Task / KRA Title
        2. Description
        3. Status
        4. Date
        5. Weightage
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setColumnCount(5)

        self.setHorizontalHeaderLabels(
            [
                "Task / KRA Title",
                "Description",
                "Status",
                "Date",
                "Weightage",
            ]
        )

        header = self.horizontalHeader()

        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
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
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.verticalHeader().setDefaultSectionSize(32)
        self.setMinimumHeight(150)

    def set_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """Display assigned tasks or empty state."""
        self.setUpdatesEnabled(False)
        self.setRowCount(0)

        if not tasks:
            self.setRowCount(1)
            empty_item = QTableWidgetItem("No assigned tasks found for today.")
            empty_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.setItem(0, 1, empty_item)
            self.setSpan(0, 0, 1, 5)
            self.setUpdatesEnabled(True)
            return

        # Clear any spans
        self.clearSpans()

        for row, task in enumerate(tasks):
            self.insertRow(row)

            title_item = QTableWidgetItem(task.get("title") or "Task")
            desc_item = QTableWidgetItem(task.get("description") or "-")
            status_item = QTableWidgetItem(task.get("status") or "-")
            date_item = QTableWidgetItem(task.get("date") or "-")
            weight_item = QTableWidgetItem(task.get("weightage") or "-")

            # Alignment
            status_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            date_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            weight_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )

            self.setItem(row, 0, title_item)
            self.setItem(row, 1, desc_item)
            self.setItem(row, 2, status_item)
            self.setItem(row, 3, date_item)
            self.setItem(row, 4, weight_item)

        self.resizeRowsToContents()
        self.setUpdatesEnabled(True)

    def show_loading(self) -> None:
        """Display a clean loading state in the table."""
        self.setUpdatesEnabled(False)
        self.setRowCount(1)
        loading_item = QTableWidgetItem("Loading assigned tasks...")
        loading_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        loading_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.setItem(0, 1, loading_item)
        self.setSpan(0, 0, 1, 5)
        self.setUpdatesEnabled(True)

    def show_error(self, message: str) -> None:
        """Display a non-blocking error notice in the table."""
        self.setUpdatesEnabled(False)
        self.setRowCount(1)
        err_item = QTableWidgetItem(f"Could not load tasks ({message})")
        err_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        err_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.setItem(0, 1, err_item)
        self.setSpan(0, 0, 1, 5)
        self.setUpdatesEnabled(True)
