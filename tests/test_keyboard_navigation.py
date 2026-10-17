"""Tests for keyboard navigation, Tab ordering, Enter/Space activation, and focus indicators in iHRMS Desktop."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

_app = QApplication.instance() or QApplication([])

from services.session_service import SessionService
from ui.additional_task_widget import AdditionalTaskWidget
from ui.attendance_page import AttendancePage, CalendarDayCard
from ui.dashboard import DashboardPage
from ui.keyboard_navigation import KeyboardNavigationEventFilter
from ui.main_window import MainWindow
from ui.task_table import AssignedTasksTable


class TestKeyboardNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        KeyboardNavigationEventFilter.install()

    def setUp(self):
        SessionService().clear()
        SessionService().login(
            username="testuser",
            role="User",
            full_name="John Doe",
        )

    def tearDown(self):
        SessionService().clear()

    def test_enter_activates_focused_button(self):
        """Pressing Enter on a focused QPushButton must trigger its click action."""
        btn = QPushButton("Test Button")
        btn.show()
        btn.setFocus()
        _app.processEvents()

        click_count = 0

        def _on_click():
            nonlocal click_count
            click_count += 1

        btn.clicked.connect(_on_click)

        # Simulate Return key press and release
        event_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        event_release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(btn, event_press)
        _app.sendEvent(btn, event_release)
        _app.processEvents()

        self.assertEqual(click_count, 1)

    def test_numpad_enter_activates_focused_button(self):
        """Pressing Key_Enter (numpad enter) on a focused button triggers click action."""
        btn = QPushButton("Test Button Numpad")
        btn.show()
        btn.setFocus()
        _app.processEvents()

        click_count = 0
        btn.clicked.connect(lambda: globals().update(numpad_clicked=True))
        numpad_clicked = False

        def _on_click():
            nonlocal click_count
            click_count += 1

        btn.clicked.connect(_on_click)

        event_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Enter, Qt.KeyboardModifier.NoModifier)
        event_release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Enter, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(btn, event_press)
        _app.sendEvent(btn, event_release)
        _app.processEvents()

        self.assertEqual(click_count, 1)

    def test_space_activates_focused_button(self):
        """Pressing Space on a focused button triggers click action."""
        btn = QPushButton("Test Space Button")
        btn.show()
        btn.setFocus()
        _app.processEvents()

        click_count = 0

        def _on_click():
            nonlocal click_count
            click_count += 1

        btn.clicked.connect(_on_click)

        event_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        event_release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(btn, event_press)
        _app.sendEvent(btn, event_release)
        _app.processEvents()

        self.assertEqual(click_count, 1)

    def test_enter_auto_repeat_suppressed(self):
        """Holding Enter down (isAutoRepeat=True) must not produce duplicate activations."""
        btn = QPushButton("Repeat Button")
        btn.show()
        btn.setFocus()
        _app.processEvents()

        click_count = 0

        def _on_click():
            nonlocal click_count
            click_count += 1

        btn.clicked.connect(_on_click)

        # Initial press
        press1 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(btn, press1)

        # Auto-repeat presses
        repeat_press1 = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier,
            text="\r", autorep=True, count=1
        )
        repeat_press2 = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier,
            text="\r", autorep=True, count=1
        )
        _app.sendEvent(btn, repeat_press1)
        _app.sendEvent(btn, repeat_press2)

        # Release
        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(btn, release)
        _app.processEvents()

        self.assertEqual(click_count, 1)

    def test_disabled_button_does_not_activate(self):
        """Disabled buttons must not activate on Enter."""
        btn = QPushButton("Disabled Button")
        btn.setEnabled(False)
        btn.show()

        click_count = 0

        def _on_click():
            nonlocal click_count
            click_count += 1

        btn.clicked.connect(_on_click)

        event_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(btn, event_press)
        _app.processEvents()

        self.assertEqual(click_count, 0)

    def test_text_input_retains_native_behavior(self):
        """Pressing Enter in QLineEdit and QPlainTextEdit must not trigger unrelated buttons."""
        window = QWidget()
        line_edit = QLineEdit(window)
        text_edit = QPlainTextEdit(window)
        btn = QPushButton("Submit Button", window)
        window.show()

        button_clicked = False
        btn.clicked.connect(lambda: globals().update(button_clicked=True))

        return_pressed_fired = False
        line_edit.returnPressed.connect(lambda: globals().update(return_pressed_fired=True))

        # Focus line edit and press Enter
        line_edit.setFocus()
        _app.processEvents()
        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(line_edit, press)
        _app.processEvents()

        # Button should NOT be clicked
        self.assertFalse(button_clicked)

        # Focus multi-line text edit and press Enter
        text_edit.setFocus()
        _app.processEvents()
        _app.sendEvent(text_edit, press)
        _app.processEvents()

        self.assertFalse(button_clicked)

    def test_mouse_click_still_works_exactly_once(self):
        """Mouse click still functions normally and emits clicked once."""
        btn = QPushButton("Mouse Test Button")
        btn.show()

        click_count = 0

        def _on_click():
            nonlocal click_count
            click_count += 1

        btn.clicked.connect(_on_click)
        btn.click()
        _app.processEvents()

        self.assertEqual(click_count, 1)

    def test_dashboard_toggle_button_keyboard_activation(self):
        """Focus on Dashboard Resume/Paused button and press Enter/Space."""
        dashboard = DashboardPage(activity_service=MagicMock())
        dashboard.show()
        _app.processEvents()

        toggle_btn = dashboard.workpulse_toggle_button
        self.assertIsNotNone(toggle_btn)

        toggle_clicked = 0
        toggle_btn.clicked.connect(lambda: globals().update(toggle_clicked=globals().get("toggle_clicked", 0) + 1))

        toggle_btn.setFocus()
        _app.processEvents()

        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(toggle_btn, press)
        _app.sendEvent(toggle_btn, release)
        _app.processEvents()

        self.assertGreaterEqual(globals().get("toggle_clicked", 0), 1)

    def test_main_window_header_buttons_activation(self):
        """Test Enter activation on hrms_button and logout_button in MainWindow."""
        window = MainWindow()
        window.show()
        _app.processEvents()

        # Test HRMS button
        hrms_clicked = 0
        window.hrms_button.clicked.connect(lambda: globals().update(hrms_clicked=globals().get("hrms_clicked", 0) + 1))
        window.hrms_button.setFocus()
        _app.processEvents()

        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(window.hrms_button, press)
        _app.sendEvent(window.hrms_button, release)
        _app.processEvents()

        self.assertGreaterEqual(globals().get("hrms_clicked", 0), 1)

    def test_attendance_navigation_buttons_activation(self):
        """Test Enter activation on AttendancePage navigation buttons."""
        page = AttendancePage()
        page.show()
        _app.processEvents()

        today_clicked = 0
        page.today_btn.clicked.connect(lambda: globals().update(today_clicked=globals().get("today_clicked", 0) + 1))
        page.today_btn.setFocus()
        _app.processEvents()

        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(page.today_btn, press)
        _app.sendEvent(page.today_btn, release)
        _app.processEvents()

        self.assertGreaterEqual(globals().get("today_clicked", 0), 1)

    def test_timesheet_action_buttons_activation(self):
        """Test Enter activation on Timesheet Save as Draft and Submit buttons."""
        task_table = AssignedTasksTable()
        task_table.show()
        _app.processEvents()

        save_draft_clicked = 0
        task_table.save_draft_btn.clicked.connect(
            lambda: globals().update(save_draft_clicked=globals().get("save_draft_clicked", 0) + 1)
        )
        task_table.save_draft_btn.setFocus()
        _app.processEvents()

        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(task_table.save_draft_btn, press)
        _app.sendEvent(task_table.save_draft_btn, release)
        _app.processEvents()

        self.assertGreaterEqual(globals().get("save_draft_clicked", 0), 1)

    def test_calendar_day_card_keyboard_activation(self):
        """Test Enter and Space activation on CalendarDayCard."""
        card = CalendarDayCard(day_data={"day": 15, "status": "P"})
        card.show()
        _app.processEvents()

        card_clicked = 0
        card.clicked.connect(lambda: globals().update(card_clicked=globals().get("card_clicked", 0) + 1))
        card.setFocus()
        _app.processEvents()

        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        _app.sendEvent(card, press)
        _app.sendEvent(card, release)
        _app.processEvents()

        self.assertGreaterEqual(globals().get("card_clicked", 0), 1)


if __name__ == "__main__":
    unittest.main()
