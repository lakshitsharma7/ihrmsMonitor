"""Modal dialog for applying employee leave requests and viewing API response output.

Sends leave application to:
    Endpoint: leave/apply_leave_v2
    Method: POST
    Payload: indo_code, key, from_date, to_date, comments, leave_type_id, duration_id
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from PySide6.QtCore import QDate, QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
                "message": f"Network / server error: {str(exc)}",
                "data": None,
                "raw_data": None,
                "error": str(exc),
            })


class ApplyLeaveDialog(QDialog):
    """Dialog allowing employees to apply for leave with leave type and duration selection and view API output."""

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
        self._last_api_result: dict[str, Any] | None = None

        # Pre-load dynamic quota items if not provided
        if not self._quota_items:
            try:
                quota_res = self._service.get_leave_quota()
                if isinstance(quota_res, dict) and quota_res.get("items"):
                    self._quota_items = quota_res.get("items", [])
            except Exception as quota_err:
                logger.debug("Could not pre-load leave quota items: %s", quota_err)

        self.setWindowTitle("Apply Leave — Employee Request")
        self.resize(500, 520)
        self.setMinimumSize(460, 440)
        self.setWindowFlags(
            (self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
            | Qt.WindowType.WindowCloseButtonHint
        )

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

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 16, 20, 16)
        root_layout.setSpacing(10)

        # --------------------------------------------------------------
        # 1. Header Row with Title, Subtitle, and prominent Close (✕) button
        # --------------------------------------------------------------
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title = QLabel("✈️ Apply for Leave", self)
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A;")
        title_col.addWidget(title)

        subtitle = QLabel("Submit your leave application for supervisor approval via the Leave Apply API.", self)
        subtitle.setStyleSheet("font-size: 11.5px; color: #64748B;")
        title_col.addWidget(subtitle)

        header_row.addLayout(title_col, 1)

        self.close_icon_btn = QPushButton("✕", self)
        self.close_icon_btn.setObjectName("HeaderCloseButton")
        self.close_icon_btn.setToolTip("Close")
        self.close_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_icon_btn.setFixedSize(28, 28)
        self.close_icon_btn.setStyleSheet(
            """
            QPushButton#HeaderCloseButton {
                background: #F1F5F9;
                color: #64748B;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 700;
                padding: 0;
            }
            QPushButton#HeaderCloseButton:hover {
                background: #FEE2E2;
                color: #DC2626;
                border-color: #FECACA;
            }
            QPushButton#HeaderCloseButton:pressed {
                background: #FCA5A5;
                color: #991B1B;
            }
            QPushButton#HeaderCloseButton:disabled {
                background: #F8FAFC;
                color: #CBD5E1;
                border-color: #F1F5F9;
            }
            """
        )
        self.close_icon_btn.clicked.connect(self.reject)
        header_row.addWidget(self.close_icon_btn, 0, Qt.AlignmentFlag.AlignTop)

        root_layout.addLayout(header_row)

        # --------------------------------------------------------------
        # 2. Scrollable container for form and dynamic API response
        # --------------------------------------------------------------
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)

        # Dynamic Employee & Company Info Card
        emp_card = QFrame(scroll_content)
        emp_card.setStyleSheet(
            "QFrame { background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; }"
        )
        emp_layout = QHBoxLayout(emp_card)
        emp_layout.setContentsMargins(12, 8, 12, 8)
        emp_layout.setSpacing(8)

        emp_code = self._service._get_active_employee_id() or "Employee"
        emp_name = ""
        comp_code = ""
        try:
            from services.session_service import SessionService
            u = SessionService().current_user
            if u:
                emp_name = u.display_name or ""
                comp_code = u.company_code or ""
        except Exception:
            pass
        if not comp_code:
            try:
                from config.api_config import ApiConfig
                comp_code = ApiConfig().company_code or ""
            except Exception:
                pass

        emp_text = f"<b>Employee:</b> {emp_code}"
        if emp_name and emp_name.lower() != "employee":
            emp_text += f" ({emp_name})"
        emp_label = QLabel(emp_text, emp_card)
        emp_label.setStyleSheet("font-size: 12px; color: #334155;")
        emp_layout.addWidget(emp_label)

        emp_layout.addStretch(1)

        comp_text = f"<b>Company:</b> {comp_code}" if comp_code else "<b>API:</b> leave/apply_leave_v2"
        comp_label = QLabel(comp_text, emp_card)
        comp_label.setStyleSheet("font-size: 11px; color: #64748B;")
        emp_layout.addWidget(comp_label)

        scroll_layout.addWidget(emp_card)

        # --------------------------------------------------------------
        # 3. Form Fields Box (compact, clean layout with direct label placement)
        # --------------------------------------------------------------
        self.form_box = QFrame(scroll_content)
        self.form_box.setStyleSheet("QFrame { background: transparent; }")
        form_layout = QVBoxLayout(self.form_box)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(12)

        # 3.1 Leave Type Selector
        lt_section = QVBoxLayout()
        lt_section.setSpacing(4)
        lt_lbl = QLabel("Leave Type *", self.form_box)
        lt_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        lt_section.addWidget(lt_lbl)

        self.leave_type_combo = QComboBox(self.form_box)
        self.leave_type_combo.setFixedHeight(34)
        self.leave_type_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.leave_type_combo.setStyleSheet(
            """
            QComboBox {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 5px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QComboBox:focus {
                border-color: #4F46E5;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #E2E8F0;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background: #F8FAFC;
            }
            """
        )
        self._populate_leave_types()
        lt_section.addWidget(self.leave_type_combo)
        form_layout.addLayout(lt_section)

        # 3.2 Duration Selector
        dur_section = QVBoxLayout()
        dur_section.setSpacing(4)
        dur_lbl = QLabel("Duration *", self.form_box)
        dur_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        dur_section.addWidget(dur_lbl)

        self.duration_combo = QComboBox(self.form_box)
        self.duration_combo.setFixedHeight(34)
        self.duration_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.duration_combo.setStyleSheet(
            """
            QComboBox {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 5px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QComboBox:focus {
                border-color: #4F46E5;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #E2E8F0;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background: #F8FAFC;
            }
            """
        )
        for opt in DURATION_OPTIONS:
            self.duration_combo.addItem(opt["name"], opt["id"])
        self.duration_combo.currentIndexChanged.connect(self._on_duration_changed)
        dur_section.addWidget(self.duration_combo)
        form_layout.addLayout(dur_section)

        # 3.3 Date Range Row (From Date & To Date side by side with equal widths)
        date_row = QHBoxLayout()
        date_row.setSpacing(14)

        # From Date Column
        from_col = QVBoxLayout()
        from_col.setSpacing(4)
        from_lbl = QLabel("From Date *", self.form_box)
        from_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        from_col.addWidget(from_lbl)

        self.from_date_edit = QDateEdit(self.form_box)
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDisplayFormat("dd-MM-yyyy")
        self.from_date_edit.setFixedHeight(34)
        self.from_date_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.from_date_edit.setStyleSheet(
            """
            QDateEdit {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 5px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QDateEdit:focus {
                border-color: #4F46E5;
            }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #E2E8F0;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background: #F8FAFC;
            }
            """
        )
        from_col.addWidget(self.from_date_edit)
        date_row.addLayout(from_col, 1)

        # To Date Column
        to_col = QVBoxLayout()
        to_col.setSpacing(4)
        to_lbl = QLabel("To Date *", self.form_box)
        to_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        to_col.addWidget(to_lbl)

        self.to_date_edit = QDateEdit(self.form_box)
        self.to_date_edit.setCalendarPopup(True)
        self.to_date_edit.setDisplayFormat("dd-MM-yyyy")
        self.to_date_edit.setFixedHeight(34)
        self.to_date_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.to_date_edit.setStyleSheet(
            """
            QDateEdit {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 5px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QDateEdit:focus {
                border-color: #4F46E5;
            }
            QDateEdit:disabled {
                background: #F1F5F9; color: #94A3B8;
            }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #E2E8F0;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background: #F8FAFC;
            }
            """
        )
        to_col.addWidget(self.to_date_edit)
        date_row.addLayout(to_col, 1)

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

        # 3.4 Reason / Comments Section
        comments_section = QVBoxLayout()
        comments_section.setSpacing(4)
        comments_lbl = QLabel("Reason / Comments *", self.form_box)
        comments_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        comments_section.addWidget(comments_lbl)

        self.comments_edit = QTextEdit(self.form_box)
        self.comments_edit.setPlaceholderText("Please explain reason for taking leave (required)...")
        self.comments_edit.setFixedHeight(72)
        self.comments_edit.setAcceptRichText(False)
        self.comments_edit.setStyleSheet(
            """
            QTextEdit {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 6px 10px; font-size: 12.5px; color: #0F172A; background: #FFFFFF;
            }
            QTextEdit:focus {
                border-color: #4F46E5;
            }
            """
        )
        comments_section.addWidget(self.comments_edit)
        form_layout.addLayout(comments_section)

        scroll_layout.addWidget(self.form_box)

        # --------------------------------------------------------------
        # 4. Status / Feedback Banner
        # --------------------------------------------------------------
        self.feedback_label = QLabel("", scroll_content)
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setVisible(False)
        scroll_layout.addWidget(self.feedback_label)

        # --------------------------------------------------------------
        # 5. Dynamic API Output Display Box
        # --------------------------------------------------------------
        self.api_output_group = QGroupBox("Leave Application API Response", scroll_content)
        self.api_output_group.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid #CBD5E1; border-radius: 8px;
                font-size: 12px; font-weight: 700; color: #1E293B;
                margin-top: 6px; padding: 12px; background: #F8FAFC;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #4338CA;
            }
            """
        )
        api_output_layout = QVBoxLayout(self.api_output_group)
        api_output_layout.setSpacing(8)

        # Status row
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.api_status_badge = QLabel("● Ready", self.api_output_group)
        self.api_status_badge.setStyleSheet(
            "background-color: #EEF2FF; color: #4F46E5; font-size: 11.5px; font-weight: 700; "
            "padding: 3px 8px; border-radius: 6px; border: 1px solid #C7D2FE;"
        )
        status_row.addWidget(self.api_status_badge)
        status_row.addStretch(1)
        api_output_layout.addLayout(status_row)

        # Server message
        self.api_message_label = QLabel("No application submitted yet.", self.api_output_group)
        self.api_message_label.setStyleSheet("font-size: 12px; color: #334155; font-weight: 600;")
        self.api_message_label.setWordWrap(True)
        api_output_layout.addWidget(self.api_message_label)

        # API Details text / payload view
        self.api_details_text = QTextEdit(self.api_output_group)
        self.api_details_text.setReadOnly(True)
        self.api_details_text.setFixedHeight(120)
        self.api_details_text.setStyleSheet(
            """
            QTextEdit {
                background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 6px;
                padding: 6px; font-family: monospace; font-size: 11px; color: #1E293B;
            }
            """
        )
        self.api_details_text.setPlaceholderText("API response JSON payload will appear here...")
        api_output_layout.addWidget(self.api_details_text)

        self.api_output_group.setVisible(False)
        scroll_layout.addWidget(self.api_output_group)

        # Absorbs vertical space to keep form elements tightly stacked at the top
        scroll_layout.addStretch(1)

        scroll_area.setWidget(scroll_content)
        root_layout.addWidget(scroll_area, 1)

        # --------------------------------------------------------------
        # 6. Action Button Row (Cancel / Close & Submit)
        # --------------------------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.close_btn = QPushButton("Cancel", self)
        self.close_btn.setObjectName("SecondaryButton")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFixedSize(90, 34)
        self.close_btn.setStyleSheet(
            """
            QPushButton {
                background: #F1F5F9; border: 1px solid #CBD5E1;
                color: #334155; border-radius: 6px;
                font-weight: 600; font-size: 12px;
            }
            QPushButton:hover {
                background: #E2E8F0; color: #0F172A;
            }
            QPushButton:disabled {
                background: #F8FAFC; color: #94A3B8; border-color: #E2E8F0;
            }
            """
        )
        self.close_btn.clicked.connect(self.reject)
        self.cancel_btn = self.close_btn
        btn_layout.addWidget(self.close_btn)

        btn_layout.addStretch(1)

        self.submit_btn = QPushButton("Submit Application", self)
        self.submit_btn.setObjectName("PrimaryButton")
        self.submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_btn.setMinimumWidth(160)
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

        root_layout.addLayout(btn_layout)

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
        self.submit_btn.setText("Submitting to API...")
        self.close_btn.setEnabled(False)
        self.close_icon_btn.setEnabled(False)

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
        """Handle response from background worker and display API output."""
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait()

        self._last_api_result = result
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Submit Application")
        self.close_btn.setEnabled(True)
        self.close_icon_btn.setEnabled(True)

        is_success = bool(result.get("success"))
        status_code = result.get("status", 200 if is_success else 400)
        message = result.get("message") or (
            "Leave application submitted successfully." if is_success else "Failed to submit leave application."
        )

        # 1. Update Feedback Banner
        if is_success:
            self._show_message(f"✅ {message}", is_error=False)
            self.submit_btn.setText("Submitted ✓")
            self.submit_btn.setEnabled(False)
            self.close_btn.setText("Close")
            self.leave_applied.emit(result)
        else:
            err_msg = result.get("error") or message
            self._show_message(f"⚠️ {err_msg}", is_error=True)

        # 2. Render Dynamic API Response Output Box
        self.api_output_group.setVisible(True)

        if is_success:
            self.api_status_badge.setText(f"● Success (HTTP {status_code})")
            self.api_status_badge.setStyleSheet(
                "background-color: #DCFCE7; color: #16A34A; font-size: 11.5px; font-weight: 700; "
                "padding: 3px 8px; border-radius: 6px; border: 1px solid #BBF7D0;"
            )
        else:
            self.api_status_badge.setText(f"● Error (HTTP {status_code})")
            self.api_status_badge.setStyleSheet(
                "background-color: #FEE2E2; color: #DC2626; font-size: 11.5px; font-weight: 700; "
                "padding: 3px 8px; border-radius: 6px; border: 1px solid #FECACA;"
            )

        self.api_message_label.setText(str(message))

        # Format details view
        details_info: dict[str, Any] = {
            "endpoint": "leave/apply_leave_v2",
            "status": status_code,
            "success": is_success,
            "message": message,
        }
        if result.get("data") is not None:
            details_info["response_data"] = result.get("data")
        elif result.get("raw_data") is not None:
            details_info["raw_data"] = result.get("raw_data")
        if result.get("error"):
            details_info["error"] = result.get("error")

        try:
            formatted_json = json.dumps(details_info, indent=2)
            self.api_details_text.setPlainText(formatted_json)
        except Exception:
            self.api_details_text.setPlainText(str(details_info))

    def reject(self) -> None:
        """Dismiss the dialog cleanly without submitting or triggering any network request."""
        self._cleanup_worker()
        super().reject()

    def closeEvent(self, event) -> None:
        """Safely clean up any worker thread when window close is triggered."""
        self._cleanup_worker()
        event.accept()
        super().closeEvent(event)

    def _cleanup_worker(self) -> None:
        """Stop running worker thread if dialog is dismissed while active."""
        if self._worker_thread and self._worker_thread.isRunning():
            try:
                self._worker_thread.quit()
                self._worker_thread.wait(500)
            except Exception as exc:
                logger.debug("Error stopping apply leave worker: %s", exc)
