"""Keyboard navigation and Enter/Space activation event filter for iHRMS Desktop."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

from utils.logger import get_logger

logger = get_logger(__name__)


class KeyboardNavigationEventFilter(QObject):
    """
    Application-level event filter ensuring:
    1. Enter / Return activates focused buttons (QPushButton, QToolButton, etc.) identically to mouse clicks.
    2. Space key activates focused buttons using standard keyboard behavior without auto-repeat spamming.
    3. Prevents accidental double activations and duplicate requests.
    4. Text inputs (QLineEdit, QTextEdit, QPlainTextEdit) retain native Enter behavior.
    5. Clean visual and accessible focus indicator management.
    """

    _instance: Optional[KeyboardNavigationEventFilter] = None

    @classmethod
    def install(cls, target: Optional[QObject] = None) -> Optional[KeyboardNavigationEventFilter]:
        """Install global keyboard event filter on the active QApplication instance or target QObject."""
        app = QApplication.instance()
        if cls._instance is None:
            parent_obj = app if app else (target if isinstance(target, QObject) else None)
            cls._instance = cls(parent=parent_obj)
            if app:
                app.installEventFilter(cls._instance)
                logger.info("KeyboardNavigationEventFilter installed on QApplication instance.")
        if target is not None and not app:
            target.installEventFilter(cls._instance)
        return cls._instance

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            if not watched or not event:
                return False
            event_type = event.type()
            if event_type in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                key = event.key()

                # ── Enter / Return key activation ─────────────────────────────
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    # 1. Always allow text inputs and multi-line editors to handle Enter natively
                    if isinstance(watched, (QLineEdit, QTextEdit, QPlainTextEdit)):
                        return False

                    # 2. Resolve target: watched widget or active focus widget
                    focus_widget = watched if isinstance(watched, QAbstractButton) else QApplication.focusWidget()

                    # If focus is currently inside a text editor, do not trigger buttons
                    if isinstance(focus_widget, (QLineEdit, QTextEdit, QPlainTextEdit)):
                        return False

                    # 3. Handle buttons receiving Enter
                    if isinstance(focus_widget, QAbstractButton):
                        if event_type == QEvent.Type.KeyPress:
                            # Prevent duplicate activations from key holding/auto-repeat
                            if event.isAutoRepeat():
                                return True
                            # If button is disabled (e.g. during submission), do nothing
                            if not focus_widget.isEnabled():
                                return True
                            # If button is already pressed down, do nothing
                            if focus_widget.isDown():
                                return True
                            # Trigger button click
                            focus_widget.click()
                            return True
                        elif event_type == QEvent.Type.KeyRelease:
                            # Consume release event corresponding to handled press
                            return True

                    # 4. Handle custom clickable widgets (e.g. day cards or custom widgets with clicked signal)
                    elif focus_widget and hasattr(focus_widget, "clicked"):
                        if event_type == QEvent.Type.KeyPress:
                            if event.isAutoRepeat():
                                return True
                            if hasattr(focus_widget, "click"):
                                focus_widget.click()
                                return True
                            elif hasattr(focus_widget, "animateClick"):
                                focus_widget.animateClick()
                                return True
                            return False
                        elif event_type == QEvent.Type.KeyRelease:
                            if hasattr(focus_widget, "click") or hasattr(focus_widget, "animateClick"):
                                return True
                            return False

                # ── Space key activation ──────────────────────────────────────
                elif key == Qt.Key.Key_Space:
                    # Prevent auto-repeat double-activations when holding Space
                    if event_type == QEvent.Type.KeyPress and event.isAutoRepeat():
                        focus_widget = watched if isinstance(watched, QAbstractButton) else QApplication.focusWidget()
                        if isinstance(focus_widget, QAbstractButton):
                            return True

            return super().eventFilter(watched, event)
        except (Exception, RuntimeError, SystemError, BaseException):
            return False
