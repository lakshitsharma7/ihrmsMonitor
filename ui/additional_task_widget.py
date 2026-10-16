"""Add Additional Task widget for the iHRMS Monitor Dashboard."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from utils.logger import get_logger

logger = get_logger(__name__)


class CenteredFlowLayout(QLayout):
    """
    Horizontally centered flow layout that keeps items side-by-side with an exact
    horizontal spacing (default 16px) and wraps onto new centered lines when width
    is constrained, preventing clipping on narrow screens.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        margin: int = 0,
        h_spacing: int = 16,
        v_spacing: int = 8,
    ) -> None:
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._item_list = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item) -> None:
        self._item_list.append(item)

    def count(self) -> int:
        return len(self._item_list)

    def itemAt(self, index: int):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply_geometry=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply_geometry=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, apply_geometry: bool = False) -> int:
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        effective_width = effective_rect.width()

        lines = []
        current_line = []
        current_line_width = 0

        for item in self._item_list:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            item_w = item.sizeHint().width()
            item_h = item.sizeHint().height()
            space = self._h_spacing if current_line else 0
            if current_line and effective_width > 0 and (current_line_width + space + item_w > effective_width):
                lines.append((current_line, current_line_width))
                current_line = [(item, item_w, item_h)]
                current_line_width = item_w
            else:
                current_line.append((item, item_w, item_h))
                current_line_width += space + item_w

        if current_line:
            lines.append((current_line, current_line_width))

        y = effective_rect.y()
        for line_items, line_w in lines:
            line_h = max(ih for _, _, ih in line_items) if line_items else 0
            start_x = effective_rect.x() + max(0, (effective_width - line_w) // 2)
            x = start_x
            for item, iw, ih in line_items:
                if apply_geometry:
                    item_y = y + (line_h - ih) // 2
                    item.setGeometry(QRect(x, item_y, iw, ih))
                x += iw + self._h_spacing
            y += line_h + self._v_spacing

        total_height = (y - effective_rect.y() - self._v_spacing) if lines else 0
        return total_height + margins.top() + margins.bottom()


class TaskMarginArea(QWidget):
    """Left margin area for LinedTaskTextEdit holding the vertical red margin accent."""

    def __init__(self, editor: LinedTaskTextEdit) -> None:
        super().__init__(editor)
        self.editor = editor
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def sizeHint(self) -> QSize:
        return QSize(self.editor.margin_area_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.margin_area_paint_event(event)

    def mousePressEvent(self, event) -> None:
        self.editor.setFocus()
        super().mousePressEvent(event)


class LinedTaskTextEdit(QPlainTextEdit):
    """
    Custom multiline text editor featuring subtle horizontal notebook writing lines
    and a vertical margin rule accent matching corporate notebook UI.
    """

    @staticmethod
    def _default_stylesheet() -> str:
        return (
            "QPlainTextEdit#LinedTaskTextEdit {"
            "    background-color: #fafbfc;"
            "    color: #1e293b;"
            "    border: 1px solid #cbd5e1;"
            "    border-radius: 8px;"
            "    selection-background-color: #bfdbfe;"
            "    selection-color: #0f172a;"
            "    font-size: 13px;"
            "}"
            "QPlainTextEdit#LinedTaskTextEdit:focus {"
            "    background-color: #ffffff;"
            "    border: 1.5px solid #3b82f6;"
            "}"
        )

    @staticmethod
    def _error_stylesheet() -> str:
        return (
            "QPlainTextEdit#LinedTaskTextEdit {"
            "    background-color: #fafbfc;"
            "    color: #1e293b;"
            "    border: 1.5px solid #ef4444;"
            "    border-radius: 8px;"
            "    selection-background-color: #bfdbfe;"
            "    selection-color: #0f172a;"
            "    font-size: 13px;"
            "}"
            "QPlainTextEdit#LinedTaskTextEdit:focus {"
            "    background-color: #ffffff;"
            "    border: 1.5px solid #ef4444;"
            "}"
        )

    @staticmethod
    def _readonly_stylesheet() -> str:
        return (
            "QPlainTextEdit#LinedTaskTextEdit {"
            "    background-color: #fafbfc;"
            "    color: #1e293b;"
            "    border: 1px solid #cbd5e1;"
            "    border-radius: 8px;"
            "    selection-background-color: #bfdbfe;"
            "    selection-color: #0f172a;"
            "    font-size: 13px;"
            "}"
            "QPlainTextEdit#LinedTaskTextEdit:focus {"
            "    background-color: #fafbfc;"
            "    border: 1px solid #cbd5e1;"
            "}"
        )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LinedTaskTextEdit")
        font = QFont("Segoe UI", 10)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        self.setFont(font)
        self.setPlaceholderText("Enter additional tasks or daily activity details here...")

        # Fixed left margin area holding the red margin rule at x=28px
        self.margin_area = TaskMarginArea(self)
        self.document().setDocumentMargin(8)
        self.setViewportMargins(self.margin_area_width(), 0, 0, 0)
        self.updateRequest.connect(self._update_margin_area)
        self.margin_area.show()

        self.setMinimumHeight(140)
        self.setMaximumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.setStyleSheet(self._default_stylesheet())

    def margin_area_width(self) -> int:
        return 38

    def update_margin_area_geometry(self) -> None:
        cr = self.contentsRect()
        self.margin_area.setGeometry(QRect(cr.left(), cr.top(), self.margin_area_width(), cr.height()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_margin_area_geometry()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.margin_area.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.margin_area.update()

    def _update_margin_area(self, rect: QRect, dy: int) -> None:
        self.margin_area.update()
        if rect.contains(self.viewport().rect()):
            self.update_margin_area_geometry()

    def margin_area_paint_event(self, event) -> None:
        painter = QPainter(self.margin_area)
        rect = self.margin_area.rect()

        # 1. Subtle professional blue-grey horizontal writing lines (darker & readable)
        line_color = QColor(165, 185, 215, 220)
        painter.setPen(QPen(line_color, 1, Qt.PenStyle.SolidLine))

        lh = max(24, self.fontMetrics().lineSpacing() + 6)
        block = self.firstVisibleBlock()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        y = top + lh
        while y < rect.bottom():
            painter.drawLine(0, y, rect.width(), y)
            y += lh

        # 2. Vertical margin accent rule (gentle red/coral line fixed at x=28)
        margin_pen = QPen(QColor(239, 68, 68, 110), 1.2, Qt.PenStyle.SolidLine)
        painter.setPen(margin_pen)
        painter.drawLine(28, 0, 28, rect.bottom())

        painter.end()

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        rect = self.viewport().rect()

        # 1. Subtle professional blue-grey horizontal writing lines (darker & readable)
        line_color = QColor(165, 185, 215, 220)
        painter.setPen(QPen(line_color, 1, Qt.PenStyle.SolidLine))

        lh = max(24, self.fontMetrics().lineSpacing() + 6)
        block = self.firstVisibleBlock()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        y = top + lh
        while y < rect.bottom():
            painter.drawLine(0, y, rect.width(), y)
            y += lh

        painter.end()

        # 2. Render text, cursor, and selection cleanly on top (starts to the right of red line)
        super().paintEvent(event)


class AdditionalTaskSignals(QObject):
    """Qt signals for asynchronous additional task submission."""

    save_success = Signal(bool, str, dict)  # is_draft, message, response_dict
    save_error = Signal(bool, str)          # is_draft, error_message


class AdditionalTaskWidget(QWidget):
    """
    Dedicated Add Additional Task component directly below the Assigned Tasks table.

    UI components:
      - Centered heading: 'Add Additional Task'
      - Large lined multiline task entry area (LinedTaskTextEdit)
      - Bottom action buttons: [ Save As Draft ] and [ Submit Task ]
      - Live status feedback and error prevention
    """

    task_saved = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AdditionalTaskWidget")

        self._date: str = datetime.now().strftime("%Y-%m-%d")
        self._is_submitting: bool = False
        self._is_submitted: bool = False

        self._signals = AdditionalTaskSignals()
        self._signals.save_success.connect(self._handle_save_success)
        self._signals.save_error.connect(self._handle_save_error)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(8)

        # ── Centered Heading ────────────────────────────────────────────────
        self.heading_label = QLabel("Add Additional Task", self)
        self.heading_label.setObjectName("AdditionalTaskHeading")
        self.heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heading_label.setStyleSheet(
            "QLabel#AdditionalTaskHeading {"
            "    color: #1e293b;"
            "    font-size: 14px;"
            "    font-weight: 700;"
            "    padding: 6px 0px 4px 0px;"
            "}"
        )
        layout.addWidget(self.heading_label)

        # ── Large Lined Multiline Text Editor ──────────────────────────────
        self.text_edit = LinedTaskTextEdit(self)
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit)

        # ── Bottom Action Controls ──────────────────────────────────────────
        actions_layout = QVBoxLayout()
        actions_layout.setContentsMargins(2, 6, 2, 2)
        actions_layout.setSpacing(6)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_msg_label = QLabel("", self)
        self.status_msg_label.setStyleSheet("font-size: 12px; font-weight: 500;")
        self.status_msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_msg_label.setVisible(False)
        actions_layout.addWidget(self.status_msg_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_container = QWidget(self)
        self.btn_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        btn_layout = CenteredFlowLayout(self.btn_container, margin=0, h_spacing=16, v_spacing=8)

        self.save_draft_btn = QPushButton("Save As Draft", self.btn_container)
        self.save_draft_btn.setObjectName("AddlSaveDraftButton")
        self.save_draft_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
        self.save_draft_btn.clicked.connect(lambda: self.save_task(is_draft=True))
        btn_layout.addWidget(self.save_draft_btn)

        self.submit_btn = QPushButton("Submit Task", self.btn_container)
        self.submit_btn.setObjectName("AddlSubmitButton")
        self.submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_btn.setStyleSheet(self._submit_btn_style_default())
        self.submit_btn.clicked.connect(lambda: self.save_task(is_draft=False))
        btn_layout.addWidget(self.submit_btn)

        actions_layout.addWidget(self.btn_container)
        layout.addLayout(actions_layout)

    @property
    def is_submitted(self) -> bool:
        """Return whether the additional task is submitted."""
        return self._is_submitted

    def set_submitted(self, submitted: bool) -> None:
        """Update submission state, text edit read-only mode, and button visibility according to backend status."""
        self._is_submitted = bool(submitted)
        if self._is_submitted:
            self.save_draft_btn.hide()
            self.submit_btn.hide()
            if hasattr(self, "btn_container"):
                self.btn_container.hide()
            self.submit_btn.setText("Submit Task")
            self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            self.save_draft_btn.setText("Save As Draft")
            self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
            self.text_edit.setReadOnly(True)
            self.text_edit.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.text_edit.setStyleSheet(self.text_edit._readonly_stylesheet())
        else:
            if hasattr(self, "btn_container"):
                self.btn_container.show()
            self.save_draft_btn.show()
            self.submit_btn.show()
            self.save_draft_btn.setEnabled(True)
            self.submit_btn.setEnabled(True)
            if not self._is_submitting:
                if not self.submit_btn.text().startswith("Retry"):
                    self.submit_btn.setText("Submit Task")
                    self.submit_btn.setStyleSheet(self._submit_btn_style_default())
                if not self.save_draft_btn.text().startswith("Draft Saved") and not self.save_draft_btn.text().startswith("Retry"):
                    self.save_draft_btn.setText("Save As Draft")
                    self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
            self.text_edit.setReadOnly(False)
            self.text_edit.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            self.text_edit.setStyleSheet(self.text_edit._default_stylesheet())

    def set_date(self, date_str: Optional[str]) -> None:
        """Set working date for additional task submissions."""
        if date_str and str(date_str).strip():
            new_date = str(date_str).strip()
            if new_date != self._date:
                self._date = new_date
                try:
                    from services.task_service import TaskService
                    is_sub = TaskService().is_additional_task_submitted(new_date)
                except Exception:
                    is_sub = False
                self.set_submitted(is_sub)
        else:
            self._date = datetime.now().strftime("%Y-%m-%d")

    def date(self) -> str:
        """Return the current working date."""
        return self._date

    def set_task_content(self, text: str, is_submitted: Optional[bool] = None) -> None:
        """Set task text content programmatically and update submission status if provided."""
        curr = self.text_edit.toPlainText().strip()
        new_val = (text or "").strip()
        if new_val:
            if new_val != curr:
                self.text_edit.setPlainText(new_val)
        elif not curr and new_val != curr:
            self.text_edit.setPlainText(new_val)

        if is_submitted is not None:
            if is_submitted:
                try:
                    from services.task_service import TaskService
                    TaskService().mark_additional_task_submitted(self._date)
                except Exception:
                    pass
            self.set_submitted(is_submitted)
        else:
            try:
                from services.task_service import TaskService
                is_sub = self._is_submitted or TaskService().is_additional_task_submitted(self._date)
            except Exception:
                is_sub = self._is_submitted
            self.set_submitted(is_sub)

    def task_content(self) -> str:
        """Get the current additional task text content."""
        return self.text_edit.toPlainText().strip()

    def clear(self) -> None:
        """Clear the task text editor."""
        self.text_edit.clear()

    def _on_text_changed(self) -> None:
        """Clear error border styling and reset retry labels when user starts typing."""
        if not self._is_submitted:
            if "border: 1.5px solid #ef4444" in self.text_edit.styleSheet():
                self.text_edit.setStyleSheet(self.text_edit._default_stylesheet())
                self.text_edit.setToolTip("")
            if hasattr(self, "status_msg_label") and self.status_msg_label.isVisible():
                if "color: #dc2626" in self.status_msg_label.styleSheet() or "error" in self.status_msg_label.text().lower():
                    self.status_msg_label.hide()
            if not self._is_submitting:
                if self.submit_btn.text().startswith("Retry"):
                    self.submit_btn.setText("Submit Task")
                    self.submit_btn.setStyleSheet(self._submit_btn_style_default())
                if self.save_draft_btn.text().startswith("Retry"):
                    self.save_draft_btn.setText("Save As Draft")
                    self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())

    def save_task(self, is_draft: bool = False) -> None:
        """
        Validate and save or submit additional task asynchronously via TaskService.save_additional_task.
        Payload:
          key: <api_key>
          indo_code: <indo_code>
          date: <YYYY-MM-DD>
          status: 0 (Draft) | 1 (Submit)
          task: <text>
        """
        if self._is_submitting:
            logger.info("AdditionalTaskWidget: save already in progress, ignoring duplicate call.")
            return

        task_text = self.text_edit.toPlainText().strip()

        # Validation
        if not task_text:
            if not is_draft:
                self.text_edit.setStyleSheet(self.text_edit._error_stylesheet())
                self.text_edit.setToolTip("Please enter task details before submitting.")
                self.text_edit.setFocus()
                self._show_status("Please enter task description before submitting.", is_error=True)
                return
            else:
                self._show_status("Please enter task description to save as draft.", is_error=True)
                return

        # Prevent duplicate submissions & set loading state
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
            self._show_status("Submitting additional task...", is_error=False)

        target_date = self._date or datetime.now().strftime("%Y-%m-%d")
        status_val = "0" if is_draft else "1"

        def worker():
            from services.task_service import TaskService
            svc = TaskService()
            try:
                ok, msg, res = svc.save_additional_task(
                    task=task_text,
                    date=target_date,
                    status=status_val,
                )
                if not ok:
                    self._signals.save_error.emit(is_draft, msg or "Failed to save additional task.")
                    return

                res_dict = res if isinstance(res, dict) else {}
                is_already_sub = (
                    res_dict.get("is_already_submitted", False)
                    or str(res_dict.get("status")) == "2"
                    or "already submitted" in str(msg).lower()
                )

                if is_already_sub:
                    # Retrieve existing saved task data through application's supported data flow
                    try:
                        tasks = svc.fetch_assigned_tasks(date=target_date, force=True)
                        add_task = next((t for t in tasks if t.get("is_additional")), None)
                    except Exception as fetch_err:
                        logger.warning("AdditionalTaskWidget: error fetching existing tasks: %s", fetch_err)
                        add_task = None

                    if add_task:
                        confirmed_text = str(add_task.get("description") or add_task.get("remark") or "").strip()
                        add_sub_status = str(add_task.get("submit_status") or "").strip()
                        add_task_status = str(add_task.get("additional_task_status") or "").strip()
                        raw_dict = add_task.get("raw") if isinstance(add_task.get("raw"), dict) else {}
                        raw_status = str(raw_dict.get("status") or "").strip()
                        raw_msg = str(raw_dict.get("message") or raw_dict.get("response") or "").lower()
                        is_confirmed = (
                            add_sub_status in ("1", "2", "true", "True")
                            or add_task_status in ("1", "2", "true", "True")
                            or str(add_task.get("status") or "").strip().lower() in ("completed", "submitted")
                            or raw_status in ("2",)
                            or "already submitted" in raw_msg
                            or bool(raw_dict.get("is_already_submitted"))
                        )
                        if is_confirmed:
                            svc.mark_additional_task_submitted(target_date)
                            self._signals.save_success.emit(
                                is_draft,
                                msg or "Task already submitted",
                                {
                                    **res_dict,
                                    "is_already_submitted": True,
                                    "is_confirmed": True,
                                    "confirmed_text": confirmed_text or task_text,
                                },
                            )
                            return

                    # If the existing API cannot confirm the saved content or submitted state,
                    # show a clear message and do not fabricate success.
                    self._signals.save_error.emit(
                        is_draft,
                        "Task already submitted on server, but existing content could not be confirmed.",
                    )
                else:
                    self._signals.save_success.emit(
                        is_draft,
                        msg or ("Draft saved successfully." if is_draft else "Task submitted successfully."),
                        {
                            **res_dict,
                            "is_newly_saved": True,
                            "is_already_submitted": False,
                            "is_confirmed": True,
                        },
                    )
            except Exception as e:
                logger.exception("AdditionalTaskWidget worker error: %s", e)
                self._signals.save_error.emit(is_draft, str(e))

        threading.Thread(target=worker, daemon=True, name="AdditionalTaskWorker").start()

    def _handle_save_success(self, is_draft: bool, msg: str, data: dict) -> None:
        """Handle successful save or draft response."""
        logger.info("AdditionalTaskWidget: save success is_draft=%s: %s", is_draft, msg)
        self._is_submitting = False

        is_already_sub = data.get("is_already_submitted", False)
        is_confirmed = data.get("is_confirmed", False)
        confirmed_text = data.get("confirmed_text")

        if is_draft:
            self.set_submitted(False)
            if hasattr(self, "btn_container"):
                self.btn_container.show()
            self.save_draft_btn.setEnabled(True)
            self.submit_btn.setEnabled(True)
            self.save_draft_btn.show()
            self.submit_btn.show()
            self.save_draft_btn.setText("Draft Saved ✓")
            self.save_draft_btn.setStyleSheet(self._btn_style_success())
            self._show_status("Draft saved successfully.", is_error=False)
            QTimer.singleShot(3500, self._reset_action_buttons)
        elif is_already_sub and is_confirmed:
            # Confirmed already-submitted response:
            # Hide BOTH buttons, keep task text visible & read-only with selection and copying enabled
            if confirmed_text:
                curr = self.text_edit.toPlainText().strip()
                if confirmed_text != curr:
                    self.text_edit.setPlainText(confirmed_text)
            try:
                from services.task_service import TaskService
                TaskService().mark_additional_task_submitted(self._date)
            except Exception:
                pass
            self.set_submitted(True)
            self._show_status("Task already submitted.", is_error=False)
        else:
            # Successfully submitted: make read-only and hide BOTH Save As Draft and Submit Task buttons
            self.submit_btn.setText("Submit Task")
            self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            self.save_draft_btn.setText("Save As Draft")
            self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
            try:
                from services.task_service import TaskService
                TaskService().mark_additional_task_submitted(self._date)
            except Exception:
                pass
            self.set_submitted(True)
            self._show_status("Additional task submitted successfully.", is_error=False)

        self.task_saved.emit({
            "task": self.text_edit.toPlainText().strip(),
            "date": self._date,
            "is_draft": is_draft,
            "response": data,
        })

    def _handle_save_error(self, is_draft: bool, err_msg: str) -> None:
        """Handle save error while preserving user entered text."""
        logger.warning("AdditionalTaskWidget: save error is_draft=%s: %s", is_draft, err_msg)
        self._is_submitting = False
        self.set_submitted(False)
        if hasattr(self, "btn_container"):
            self.btn_container.show()
        self.save_draft_btn.setEnabled(True)
        self.submit_btn.setEnabled(True)
        self.save_draft_btn.show()
        self.submit_btn.show()

        if is_draft:
            self.save_draft_btn.setText("Retry Draft ⚠️")
            self.save_draft_btn.setStyleSheet(self._btn_style_error())
        else:
            self.submit_btn.setText("Retry Submit ⚠️")
            self.submit_btn.setStyleSheet(self._btn_style_error())

        self._show_status(f"Error: {err_msg}", is_error=True)

    def _show_status(self, message: str, is_error: bool = False) -> None:
        """Display status notification next to buttons."""
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
            if hasattr(self, "btn_container"):
                self.btn_container.hide()
            self.text_edit.setReadOnly(True)
            self.text_edit.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            self.text_edit.setStyleSheet(self.text_edit._readonly_stylesheet())
        else:
            if hasattr(self, "btn_container"):
                self.btn_container.show()
            self.save_draft_btn.setEnabled(True)
            self.submit_btn.setEnabled(True)
            self.save_draft_btn.setText("Save As Draft")
            self.submit_btn.setText("Submit Task")
            self.save_draft_btn.setStyleSheet(self._draft_btn_style_default())
            self.submit_btn.setStyleSheet(self._submit_btn_style_default())
            self.save_draft_btn.show()
            self.submit_btn.show()
            self.text_edit.setReadOnly(False)
            self.text_edit.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            self.text_edit.setStyleSheet(self.text_edit._default_stylesheet())

    @staticmethod
    def _draft_btn_style_default() -> str:
        return (
            "QPushButton#AddlSaveDraftButton {"
            "  background-color: #ffffff;"
            "  color: #1a73e8;"
            "  border: 1.5px solid #1a73e8;"
            "  border-radius: 6px;"
            "  padding: 7px 18px;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "  min-width: 95px;"
            "}"
            "QPushButton#AddlSaveDraftButton:hover {"
            "  background-color: #f0f7ff;"
            "}"
            "QPushButton#AddlSaveDraftButton:pressed {"
            "  background-color: #e0effe;"
            "}"
            "QPushButton#AddlSaveDraftButton:disabled {"
            "  background-color: #f8fafc;"
            "  color: #94a3b8;"
            "  border-color: #cbd5e1;"
            "}"
        )

    @staticmethod
    def _submit_btn_style_default() -> str:
        return (
            "QPushButton#AddlSubmitButton {"
            "  background-color: #1a73e8;"
            "  color: #ffffff;"
            "  border: none;"
            "  border-radius: 6px;"
            "  padding: 7px 22px;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "  min-width: 95px;"
            "}"
            "QPushButton#AddlSubmitButton:hover {"
            "  background-color: #1557b0;"
            "}"
            "QPushButton#AddlSubmitButton:pressed {"
            "  background-color: #0d47a1;"
            "}"
            "QPushButton#AddlSubmitButton:disabled {"
            "  background-color: #93bbf8;"
            "  color: #ffffff;"
            "}"
        )

    @staticmethod
    def _btn_style_success() -> str:
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
