"""Modal dialog for applying employee leave requests.

Sends leave application to:
    Endpoint: leave/apply_leave_v2
    Method: POST
    Payload: indo_code, key, from_date, to_date, comments, leave_type_id, duration_id
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from PySide6.QtCore import QDate, QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.attendance_service import AttendanceService
from utils.logger import get_logger

logger = get_logger(__name__)

# Standard 7 Leave Types as fallback if dynamic quota has not been loaded
DEFAULT_LEAVE_TYPES = [
    {"id": "1", "code": "CL", "name": "Casual Leave"},
    {"id": "2", "code": "SL", "name": "Sick Leave"},
    {"id": "3", "code": "CO", "name": "Comp Off"},
    {"id": "4", "code": "OD", "name": "Business Trip / On Duty"},
    {"id": "5", "code": "LWP", "name": "Leave Without Pay"},
    {"id": "6", "code": "EL", "name": "Paid Leave / Earned Leave"},
    {"id": "7", "code": "RH", "name": "Restricted / Floating Holiday"},
]

DURATION_OPTIONS = [
    {"id": "6", "name": "Full Day"},
    {"id": "1", "name": "First Half (Morning)"},
    {"id": "2", "name": "Second Half (Afternoon)"},
]


class _ApplyLeaveWorker(QObject):
    """Background worker for asynchronous leave application API call."""

    finished = Signal(dict)

    def __init__(
        self,
        service: AttendanceService,
        from_date: str,
        to_date: str,
        leave_type_id: str,
        duration_id: str,
        comments: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._from_date = from_date
        self._to_date = to_date
        self._leave_type_id = leave_type_id
        self._duration_id = duration_id
        self._comments = comments

    def run(self) -> None:
        try:
            result = self._service.apply_leave(
                from_date=self._from_date,
                to_date=self._to_date,
                leave_type_id=self._leave_type_id,
                duration_id=self._duration_id,
                comments=self._comments,
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.error("Exception in apply leave worker: %s", exc)
            self.finished.emit({
                "success": False,
                "status": 500,
                "message": f"Unexpected error: {str(exc)}",
                "error": str(exc),
            })


class ApplyLeaveDialog(QDialog):
    """Dialog allowing employees to apply for leave with leave type and duration selection."""

    leave_applied = Signal(dict)

    def __init__(
        self,
        service: AttendanceService | None = None,
        parent: QWidget | None = None,
        prefill_date: str | datetime | QDate | None = None,
        quota_items: list[dict] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service or AttendanceService()
        self._quota_items = quota_items or []
        self._worker_thread: QThread | None = None

        self.setWindowTitle("Apply Leave")
        self.setFixedSize(500, 600)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._init_ui(prefill_date)

    def _init_ui(self, prefill_date: str | datetime | QDate | None) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: #FFFFFF;
                color: #0F172A;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            }
            QLabel {
                color: #334155;
            }
            """
        )

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(14)

        # Header Section
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        title = QLabel("Apply for Leave", self)
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #0F172A;")
        header_layout.addWidget(title)

        subtitle = QLabel("Submit your leave application for supervisor approval.", self)
        subtitle.setStyleSheet("font-size: 12px; color: #64748B;")
        header_layout.addWidget(subtitle)

        main_layout.addLayout(header_layout)

        # Employee Info Card
        emp_card = QFrame(self)
        emp_card.setStyleSheet(
            "QFrame { background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; }"
        )
        emp_layout = QHBoxLayout(emp_card)
        emp_layout.setContentsMargins(12, 10, 12, 10)

        emp_code = self._service._get_active_employee_id() or "Employee"
        emp_label = QLabel(f"<b>Employee:</b> {emp_code}", emp_card)
        emp_label.setStyleSheet("font-size: 12px; color: #334155;")
        emp_layout.addWidget(emp_label)

        main_layout.addWidget(emp_card)

        # Form Fields Container
        form_frame = QFrame(self)
        form_frame.setStyleSheet("QFrame { background: transparent; }")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)

        # 1. Leave Type Selector
        lt_lbl = QLabel("Leave Type *", self)
        lt_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        form_layout.addWidget(lt_lbl)

        self.leave_type_combo = QComboBox(self)
        self.leave_type_combo.setStyleSheet(
            """
            QComboBox {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 6px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QComboBox:focus {
                border-color: #4F46E5;
            }
            """
        )
        self._populate_leave_types()
        form_layout.addWidget(self.leave_type_combo)

        # 2. Duration Selector
        dur_lbl = QLabel("Duration *", self)
        dur_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        form_layout.addWidget(dur_lbl)

        self.duration_combo = QComboBox(self)
        self.duration_combo.setStyleSheet(
            """
            QComboBox {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 6px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QComboBox:focus {
                border-color: #4F46E5;
            }
            """
        )
        for opt in DURATION_OPTIONS:
            self.duration_combo.addItem(opt["name"], opt["id"])
        self.duration_combo.currentIndexChanged.connect(self._on_duration_changed)
        form_layout.addWidget(self.duration_combo)

        # 3. Date Range Row (From Date & To Date)
        date_row = QHBoxLayout()
        date_row.setSpacing(12)

        # From Date Column
        from_col = QVBoxLayout()
        from_col.setSpacing(4)
        from_lbl = QLabel("From Date *", self)
        from_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        from_col.addWidget(from_lbl)

        self.from_date_edit = QDateEdit(self)
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDisplayFormat("dd-MM-yyyy")
        self.from_date_edit.setStyleSheet(
            """
            QDateEdit {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 6px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QDateEdit:focus {
                border-color: #4F46E5;
            }
            """
        )
        from_col.addWidget(self.from_date_edit)
        date_row.addLayout(from_col)

        # To Date Column
        to_col = QVBoxLayout()
        to_col.setSpacing(4)
        to_lbl = QLabel("To Date *", self)
        to_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        to_col.addWidget(to_lbl)

        self.to_date_edit = QDateEdit(self)
        self.to_date_edit.setCalendarPopup(True)
        self.to_date_edit.setDisplayFormat("dd-MM-yyyy")
        self.to_date_edit.setStyleSheet(
            """
            QDateEdit {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 6px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QDateEdit:focus {
                border-color: #4F46E5;
            }
            QDateEdit:disabled {
                background: #F1F5F9; color: #94A3B8;
            }
            """
        )
        to_col.addWidget(self.to_date_edit)
        date_row.addLayout(to_col)

        # Set initial dates
        initial_date = QDate.currentDate()
        if prefill_date:
            if isinstance(prefill_date, QDate):
                initial_date = prefill_date
            elif isinstance(prefill_date, datetime):
                initial_date = QDate(prefill_date.year, prefill_date.month, prefill_date.day)
            else:
                s = str(prefill_date).strip()
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
                    try:
                        dt = datetime.strptime(s, fmt)
                        initial_date = QDate(dt.year, dt.month, dt.day)
                        break
                    except Exception:
                        pass

        self.from_date_edit.setDate(initial_date)
        self.to_date_edit.setDate(initial_date)
        self.from_date_edit.dateChanged.connect(self._on_from_date_changed)

        form_layout.addLayout(date_row)

        # 4. Comments / Reason Field
        comments_lbl = QLabel("Reason / Comments *", self)
        comments_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        form_layout.addWidget(comments_lbl)

        self.comments_edit = QTextEdit(self)
        self.comments_edit.setPlaceholderText("Please explain reason for taking leave (e.g. medical appointment, annual family leave, personal work)...")
        self.comments_edit.setMaximumHeight(85)
        self.comments_edit.setStyleSheet(
            """
            QTextEdit {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 8px 10px; font-size: 12px; color: #0F172A; background: #FFFFFF;
            }
            QTextEdit:focus {
                border-color: #4F46E5;
            }
            """
        )
        form_layout.addWidget(self.comments_edit)

        main_layout.addWidget(form_frame)

        # Feedback / Status Message Box
        self.feedback_label = QLabel("", self)
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setVisible(False)
        main_layout.addWidget(self.feedback_label)

        main_layout.addStretch(1)

        # Button Row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setFixedSize(90, 34)
        self.cancel_btn.setStyleSheet(
            """
            QPushButton {
                background: #F1F5F9; border: 1px solid #E2E8F0;
                color: #334155; border-radius: 6px;
                font-weight: 600; font-size: 12px;
            }
            QPushButton:hover {
                background: #E2E8F0; color: #0F172A;
            }
            """
        )
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        btn_layout.addStretch(1)

        self.submit_btn = QPushButton("Submit Application", self)
        self.submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_btn.setMinimumWidth(140)
        self.submit_btn.setFixedHeight(34)
        self.submit_btn.setStyleSheet(
            """
            QPushButton {
                background: #4F46E5; border: 1px solid #4338CA;
                color: #FFFFFF; border-radius: 6px;
                padding: 6px 16px; font-weight: 600; font-size: 12px;
            }
            QPushButton:hover {
                background: #4338CA;
            }
            QPushButton:disabled {
                background: #A5B4FC; border-color: #A5B4FC; color: #EEF2FF;
            }
            """
        )
        self.submit_btn.clicked.connect(self._handle_submit)
        btn_layout.addWidget(self.submit_btn)

        main_layout.addLayout(btn_layout)

    def _populate_leave_types(self) -> None:
        """Populate leave types combo box with available quotas or fallback types."""
        self.leave_type_combo.clear()

        # If quota items are provided, use them
        if self._quota_items:
            for item in self._quota_items:
                lt_id = str(item.get("leave_type_id") or item.get("raw", {}).get("lt_id") or "").strip()
                name = item.get("name") or item.get("leave_type") or f"Leave Type {lt_id}"
                code = item.get("code") or item.get("short_name") or ""
                avail = item.get("available")
                label = f"{name} ({code})" if code else name
                if avail is not None:
                    avail_str = f"{avail:g}" if isinstance(avail, (int, float)) else str(avail)
                    label += f" — {avail_str} days available"
                self.leave_type_combo.addItem(label, lt_id)
        else:
            # Fall back to default types
            for lt in DEFAULT_LEAVE_TYPES:
                label = f"{lt['name']} ({lt['code']})"
                self.leave_type_combo.addItem(label, lt["id"])

    def _on_duration_changed(self) -> None:
        """Lock or sync To Date when half-day is selected."""
        dur_id = self.duration_combo.currentData()
        if dur_id in ("1", "2"):  # Half day
            self.to_date_edit.setDate(self.from_date_edit.date())
            self.to_date_edit.setEnabled(False)
        else:
            self.to_date_edit.setEnabled(True)

    def _on_from_date_changed(self, new_date: QDate) -> None:
        """Ensure To Date is not before From Date."""
        dur_id = self.duration_combo.currentData()
        if dur_id in ("1", "2") or self.to_date_edit.date() < new_date:
            self.to_date_edit.setDate(new_date)

    def _show_message(self, message: str, is_error: bool = True) -> None:
        """Display error or success banner."""
        if is_error:
            self.feedback_label.setStyleSheet(
                "QLabel { background-color: #FEF2F2; color: #B91C1C; "
                "border: 1px solid #FECACA; border-radius: 6px; "
                "padding: 8px 12px; font-size: 12px; font-weight: 500; }"
            )
        else:
            self.feedback_label.setStyleSheet(
                "QLabel { background-color: #F0FDF4; color: #15803D; "
                "border: 1px solid #BBF7D0; border-radius: 6px; "
                "padding: 8px 12px; font-size: 12px; font-weight: 600; }"
            )
        self.feedback_label.setText(message)
        self.feedback_label.setVisible(True)

    def _handle_submit(self) -> None:
        """Validate inputs and launch background worker."""
        # 1. Validation
        from_val = self.from_date_edit.date()
        to_val = self.to_date_edit.date()

        if to_val < from_val:
            self._show_message("To Date cannot be earlier than From Date.", is_error=True)
            return

        lt_id = self.leave_type_combo.currentData()
        if not lt_id:
            self._show_message("Please select a valid Leave Type.", is_error=True)
            return

        dur_id = self.duration_combo.currentData() or "6"
        comments = self.comments_edit.toPlainText().strip()
        if not comments:
            self._show_message("Please enter a reason/comment for the leave application.", is_error=True)
            self.comments_edit.setFocus()
            return

        from_date_str = from_val.toString("dd-MM-yyyy")
        to_date_str = to_val.toString("dd-MM-yyyy")

        # 2. UI Loading State
        self.feedback_label.setVisible(False)
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Submitting...")
        self.cancel_btn.setEnabled(False)

        # 3. Launch Worker
        self._worker_thread = QThread(self)
        self._worker = _ApplyLeaveWorker(
            service=self._service,
            from_date=from_date_str,
            to_date=to_date_str,
            leave_type_id=str(lt_id),
            duration_id=str(dur_id),
            comments=comments,
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_submit_finished)
        self._worker_thread.start()

    def _on_submit_finished(self, result: dict) -> None:
        """Handle response from background worker."""
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait()

        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Submit Application")
        self.cancel_btn.setEnabled(True)

        if result.get("success"):
            success_msg = result.get("message") or "Leave application submitted successfully."
            self._show_message(f"✅ {success_msg}", is_error=False)
            self.submit_btn.setEnabled(False)
            self.leave_applied.emit(result)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1200, self.accept)
        else:
            err_msg = result.get("message") or result.get("error") or "Failed to submit leave application."
            self._show_message(f"⚠️ {err_msg}", is_error=True)
