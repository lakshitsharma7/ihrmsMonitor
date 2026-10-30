"""Modal dialog for submitting Missed Punch attendance regularization and viewing API output.

Sends missed punch request to:
    Endpoint: Punch/mispunch
    Method: POST
    Payload: key, indo_code, date, in_time, out_time, comments, atten_id
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from PySide6.QtCore import QDate, QObject, QThread, QTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from services.attendance_service import AttendanceService
from utils.logger import get_logger

logger = get_logger(__name__)


class _MissedPunchWorker(QObject):
    """Background worker for asynchronous missed punch API call."""

    finished = Signal(dict)

    def __init__(
        self,
        service: AttendanceService,
        date_str: str,
        in_time_str: str,
        out_time_str: str,
        comments: str,
        atten_id: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._date_str = date_str
        self._in_time_str = in_time_str
        self._out_time_str = out_time_str
        self._comments = comments
        self._atten_id = atten_id

    def run(self) -> None:
        try:
            result = self._service.submit_missed_punch(
                date=self._date_str,
                in_time=self._in_time_str,
                out_time=self._out_time_str,
                comments=self._comments,
                atten_id=self._atten_id,
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.error("Exception in missed punch worker: %s", exc)
            self.finished.emit({
                "success": False,
                "status": 500,
                "message": f"Network / server error: {str(exc)}",
                "data": None,
                "raw_data": None,
                "error": str(exc),
            })


class MissedPunchDialog(QDialog):
    """Dialog allowing employees to submit a missed punch regularization request and view API output."""

    punch_submitted = Signal(dict)

    def __init__(
        self,
        service: AttendanceService | None = None,
        parent: QWidget | None = None,
        prefill_date: str | datetime | QDate | None = None,
        atten_id: str = "",
    ) -> None:
        super().__init__(parent)
        self._service = service or AttendanceService()
        self._atten_id = str(atten_id or "").strip()
        self._worker_thread: QThread | None = None
        self._last_api_result: dict[str, Any] | None = None

        self.setWindowTitle("Missed Punch — Attendance Regularization")
        self.resize(500, 480)
        self.setMinimumSize(460, 420)
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

        title = QLabel("⏰ Missed Punch Regularization", self)
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A;")
        title_col.addWidget(title)

        subtitle = QLabel("Submit missing punch timings directly via the official Missed Punch API.", self)
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

        # Employee & Company Info Card
        emp_card = QFrame(scroll_content)
        emp_card.setStyleSheet(
            "QFrame { background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; }"
        )
        emp_layout = QHBoxLayout(emp_card)
        emp_layout.setContentsMargins(12, 8, 12, 8)
        emp_layout.setSpacing(8)

        emp_code = self._service._get_active_employee_id() or "Employee"
        emp_label = QLabel(f"<b>Employee:</b> {emp_code}", emp_card)
        emp_label.setStyleSheet("font-size: 12px; color: #334155;")
        emp_layout.addWidget(emp_label)

        emp_layout.addStretch(1)

        api_ep_label = QLabel("<b>API:</b> Punch/mispunch", emp_card)
        api_ep_label.setStyleSheet("font-size: 11px; color: #64748B;")
        emp_layout.addWidget(api_ep_label)

        if self._atten_id:
            atten_label = QLabel(f"<b>Atten ID:</b> {self._atten_id}", emp_card)
            atten_label.setStyleSheet("font-size: 11px; color: #64748B;")
            emp_layout.addWidget(atten_label)

        scroll_layout.addWidget(emp_card)

        # --------------------------------------------------------------
        # 3. Form Fields Box (compact, clean layout with direct label placement)
        # --------------------------------------------------------------
        self.form_box = QFrame(scroll_content)
        self.form_box.setStyleSheet("QFrame { background: transparent; }")
        form_layout = QVBoxLayout(self.form_box)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(12)

        # 3.1 Date Field
        date_section = QVBoxLayout()
        date_section.setSpacing(4)
        date_lbl = QLabel("Date *", self.form_box)
        date_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        date_section.addWidget(date_lbl)

        self.date_edit = QDateEdit(self.form_box)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MM-yyyy")
        self.date_edit.setMaximumDate(QDate.currentDate())
        self.date_edit.setFixedHeight(34)
        self.date_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.date_edit.setStyleSheet(
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

        # Set initial date
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
        self.date_edit.setDate(initial_date)
        date_section.addWidget(self.date_edit)
        form_layout.addLayout(date_section)

        # 3.2 Timing Fields (Punch In & Punch Out)
        time_row = QHBoxLayout()
        time_row.setSpacing(14)

        # In-Time column
        in_col = QVBoxLayout()
        in_col.setSpacing(4)
        self.in_time_cb = QCheckBox("Punch In Time", self.form_box)
        self.in_time_cb.setChecked(True)
        self.in_time_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.in_time_cb.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        in_col.addWidget(self.in_time_cb)

        self.in_time_edit = QTimeEdit(self.form_box)
        self.in_time_edit.setDisplayFormat("HH:mm:ss")
        self.in_time_edit.setTime(QTime(9, 30, 0))
        self.in_time_edit.setFixedHeight(34)
        self.in_time_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.in_time_edit.setStyleSheet(
            """
            QTimeEdit {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 5px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QTimeEdit:focus {
                border-color: #4F46E5;
            }
            QTimeEdit:disabled {
                background: #F1F5F9; color: #94A3B8;
            }
            """
        )
        self.in_time_cb.toggled.connect(self.in_time_edit.setEnabled)
        in_col.addWidget(self.in_time_edit)
        time_row.addLayout(in_col)

        # Out-Time column
        out_col = QVBoxLayout()
        out_col.setSpacing(4)
        self.out_time_cb = QCheckBox("Punch Out Time", self.form_box)
        self.out_time_cb.setChecked(True)
        self.out_time_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.out_time_cb.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        out_col.addWidget(self.out_time_cb)

        self.out_time_edit = QTimeEdit(self.form_box)
        self.out_time_edit.setDisplayFormat("HH:mm:ss")
        self.out_time_edit.setTime(QTime(18, 30, 0))
        self.out_time_edit.setFixedHeight(34)
        self.out_time_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.out_time_edit.setStyleSheet(
            """
            QTimeEdit {
                border: 1px solid #CBD5E1; border-radius: 6px;
                padding: 5px 10px; font-size: 13px; color: #0F172A; background: #FFFFFF;
            }
            QTimeEdit:focus {
                border-color: #4F46E5;
            }
            QTimeEdit:disabled {
                background: #F1F5F9; color: #94A3B8;
            }
            """
        )
        self.out_time_cb.toggled.connect(self.out_time_edit.setEnabled)
        out_col.addWidget(self.out_time_edit)
        time_row.addLayout(out_col)

        form_layout.addLayout(time_row)

        # 3.3 Reason / Comments Section
        comments_section = QVBoxLayout()
        comments_section.setSpacing(4)
        comments_lbl = QLabel("Reason / Comments *", self.form_box)
        comments_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #1E293B;")
        comments_section.addWidget(comments_lbl)

        self.comments_edit = QTextEdit(self.form_box)
        self.comments_edit.setPlaceholderText("Please explain why punch was missed (required)...")
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
        self.api_output_group = QGroupBox("Missed Punch API Response", scroll_content)
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
        self.api_message_label = QLabel("No request submitted yet.", self.api_output_group)
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

        self.submit_btn = QPushButton("Submit Missed Punch", self)
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
        date_val = self.date_edit.date()
        date_str = date_val.toString("dd-MM-yyyy")

        in_time_str = self.in_time_edit.time().toString("HH:mm:ss") if self.in_time_cb.isChecked() else ""
        out_time_str = self.out_time_edit.time().toString("HH:mm:ss") if self.out_time_cb.isChecked() else ""

        if not in_time_str and not out_time_str:
            self._show_message("Please enable at least one punch timing (In Time or Out Time).", is_error=True)
            return

        comments = self.comments_edit.toPlainText().strip()
        if not comments:
            self._show_message("Please enter a reason/comment for the missed punch.", is_error=True)
            self.comments_edit.setFocus()
            return

        # 2. UI Loading State
        self.feedback_label.setVisible(False)
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Submitting to API...")
        self.close_btn.setEnabled(False)
        self.close_icon_btn.setEnabled(False)

        # 3. Launch Worker
        self._worker_thread = QThread(self)
        self._worker = _MissedPunchWorker(
            service=self._service,
            date_str=date_str,
            in_time_str=in_time_str,
            out_time_str=out_time_str,
            comments=comments,
            atten_id=self._atten_id,
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
        self.submit_btn.setText("Submit Missed Punch")
        self.close_btn.setEnabled(True)
        self.close_icon_btn.setEnabled(True)

        is_success = bool(result.get("success"))
        status_code = result.get("status", 200 if is_success else 400)
        message = result.get("message") or (
            "Missed punch request submitted successfully." if is_success else "Failed to submit request."
        )

        # 1. Update Feedback Banner
        if is_success:
            self._show_message(f"✅ {message}", is_error=False)
            self.submit_btn.setText("Submitted ✓")
            self.submit_btn.setEnabled(False)
            self.close_btn.setText("Close")
            self.punch_submitted.emit(result)
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
            "endpoint": "Punch/mispunch",
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
                logger.debug("Error stopping missed punch worker: %s", exc)
