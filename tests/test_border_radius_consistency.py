"""Tests for border-radius consistency across iHRMS Desktop dashboard UI."""

import unittest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton, QLabel

from services.activity_service import ActivityService
from services.session_service import SessionService
from ui.dashboard import DashboardPage
from ui.styles import APP_STYLESHEET
from ui.attendance_page import AttendancePage


class TestBorderRadiusConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLESHEET)

    def setUp(self):
        SessionService().clear()
        SessionService().login(
            username="testuser",
            role="User",
            full_name="Test User",
        )
        self.mock_service = MagicMock(spec=ActivityService)
        self.mock_service.get_today_total_seconds.return_value = 3600
        self.mock_service.get_persisted_daily_active_seconds.return_value = 3600
        self.mock_service.get_today_total_idle_seconds.return_value = 60
        self.mock_service.get_uploaded_records_count.return_value = 10
        self.mock_service.get_today_timeline.return_value = []

    def tearDown(self):
        SessionService().clear()

    def test_01_dashboard_cards_have_consistent_object_names_and_rules(self):
        """Verify Today's Time, Attendance, and Status cards match the 8px QGroupBox card standard."""
        page = DashboardPage(self.mock_service)
        try:
            boxes = page.findChildren(QGroupBox)
            titles = [gb.title() for gb in boxes]
            self.assertIn("Today's Time", titles)
            self.assertIn("Status", titles)

            # Check that Today's Time card has objectName TodayTimeCard
            today_card = [gb for gb in boxes if gb.title() == "Today's Time"][0]
            self.assertEqual(today_card.objectName(), "TodayTimeCard")

            # Check AttendanceCard
            att_card = page.findChild(QGroupBox, "AttendanceCard")
            self.assertIsNotNone(att_card)

            # Check StatusCard
            status_card = page.findChild(QGroupBox, "StatusCard")
            self.assertIsNotNone(status_card)

            # Verify APP_STYLESHEET includes consistent 8px radius for QGroupBox and card IDs
            self.assertIn("border-radius: 8px;", APP_STYLESHEET)
            self.assertIn("QGroupBox", APP_STYLESHEET)
            self.assertIn("#AttendanceCard", APP_STYLESHEET)
            self.assertIn("#StatusCard", APP_STYLESHEET)
        finally:
            page.close()
            page.deleteLater()

    def test_02_version_button_uses_consistent_6px_radius_without_pill_shape(self):
        """Verify version button uses standard 6px border-radius and avoids 11px pill shape."""
        page = DashboardPage(self.mock_service)
        try:
            btn = page.version_button
            self.assertIsNotNone(btn)
            stylesheet = btn.styleSheet()
            self.assertIn("border-radius: 6px;", stylesheet)
            self.assertNotIn("border-radius: 11px;", stylesheet)
        finally:
            page.close()
            page.deleteLater()

    def test_03_status_badge_and_attendance_badge_have_subtle_consistent_radius(self):
        """Verify status badge in APP_STYLESHEET and attendance badge use consistent 6px radius."""
        page = DashboardPage(self.mock_service)
        try:
            # Check attendance_status_badge
            badge = page.attendance_status_badge
            self.assertIsNotNone(badge)
            self.assertIn("border-radius: 6px;", badge.styleSheet())

            # Check StatusBadge rule in APP_STYLESHEET
            self.assertIn("#StatusBadge {", APP_STYLESHEET)
            self.assertIn("border-radius: 6px;", APP_STYLESHEET)
            self.assertNotIn("border-radius: 10px;", APP_STYLESHEET)
        finally:
            page.close()
            page.deleteLater()

    def test_04_dashboard_action_buttons_use_consistent_6px_radius(self):
        """Verify Attendance button, Paused/Resume button, and general buttons use 6px radius."""
        page = DashboardPage(self.mock_service)
        try:
            # Paused button stylesheet
            page._apply_toggle_button_style(is_active=True)
            self.assertIn("border-radius: 6px;", page.workpulse_toggle_button.styleSheet())

            # Resume button stylesheet
            page.set_paused(True)
            self.assertIn("border-radius: 6px;", page.workpulse_toggle_button.styleSheet())

            # Attendance button in APP_STYLESHEET
            self.assertIn("QPushButton#AttendanceButton", APP_STYLESHEET)
            self.assertIn("QPushButton {", APP_STYLESHEET)
        finally:
            page.close()
            page.deleteLater()

    def test_05_leave_balance_button_in_attendance_page_uses_consistent_6px_radius(self):
        """Verify Leave Balance button in Attendance page uses consistent 6px radius (not 10px)."""
        att_service = MagicMock()
        att_page = AttendancePage(service=att_service)
        try:
            btn = att_page.leave_balance_button
            self.assertIsNotNone(btn)
            stylesheet = btn.styleSheet()
            self.assertIn("border-radius: 6px;", stylesheet)
            self.assertNotIn("border-radius: 10px;", stylesheet)
        finally:
            att_page.close()
            att_page.deleteLater()

    def test_06_month_navigation_buttons_use_consistent_6px_radius(self):
        """Verify Previous Month and Next Month buttons use consistent 6px radius without circular 14px rounding."""
        att_service = MagicMock()
        att_page = AttendancePage(service=att_service)
        try:
            prev_btn = att_page.cal_prev_btn
            next_btn = att_page.cal_next_btn
            self.assertIsNotNone(prev_btn)
            self.assertIsNotNone(next_btn)

            # Verify tooltips
            self.assertEqual(prev_btn.toolTip(), "Previous Month")
            self.assertEqual(next_btn.toolTip(), "Next Month")

            # Verify both styles match and use standard 6px radius
            prev_style = prev_btn.styleSheet()
            next_style = next_btn.styleSheet()
            self.assertEqual(prev_style, next_style)
            self.assertIn("border-radius: 6px;", prev_style)
            self.assertNotIn("border-radius: 14px;", prev_style)

            # Verify dimensions and subtle rectangular appearance preserved
            self.assertIn("min-width: 28px;", prev_style)
            self.assertIn("min-height: 28px;", prev_style)
        finally:
            att_page.close()
            att_page.deleteLater()

    def test_07_release_summary_new_and_improvement_sections_have_equal_border_radius(self):
        """Verify NEW and IMPROVEMENT outer boxes and inner badges have matching corner radii."""
        import re
        from ui.release_summary_dialog import (
            ReleaseSummaryDialog,
            render_categorized_summary_html,
            RELEASE_SECTION_BORDER_RADIUS,
            RELEASE_BADGE_BORDER_RADIUS,
        )

        test_cats = {
            "NEW": ["Added new dark mode toggle option", "Added biometric quick punch"],
            "IMPROVEMENT": ["Improved sync speed by 40%", "Refined table responsiveness"],
        }
        html_out = render_categorized_summary_html(test_cats)

        # 1. Shared tokens exist and match standard
        self.assertEqual(RELEASE_SECTION_BORDER_RADIUS, "8px")
        self.assertEqual(RELEASE_BADGE_BORDER_RADIUS, "4px")

        # 2. Both sections use shared CSS styling rules
        self.assertIn(".release-card", html_out)
        self.assertIn(".release-badge", html_out)

        # 3. Outer box border-radius for NEW and IMPROVEMENT must be identical
        new_box_match = re.search(r'<table[^>]*class="release-card"[^>]*style="[^"]*background-color:\s*#f0fdf4[^"]*border-radius:\s*([^;"]+)', html_out)
        imp_box_match = re.search(r'<table[^>]*class="release-card"[^>]*style="[^"]*background-color:\s*#f0fdf9[^"]*border-radius:\s*([^;"]+)', html_out)
        self.assertIsNotNone(new_box_match, "NEW outer box should have a border-radius style")
        self.assertIsNotNone(imp_box_match, "IMPROVEMENT outer box should have a border-radius style")
        self.assertEqual(new_box_match.group(1).strip(), imp_box_match.group(1).strip())
        self.assertEqual(new_box_match.group(1).strip(), "8px")

        # 4. Inner label badge border-radius for NEW and IMPROVEMENT must be identical
        new_badge_match = re.search(r'<td[^>]*class="release-badge"[^>]*style="[^"]*background-color:\s*#dcfce7[^"]*border-radius:\s*([^;"]+)', html_out)
        imp_badge_match = re.search(r'<td[^>]*class="release-badge"[^>]*style="[^"]*background-color:\s*#ccfbf1[^"]*border-radius:\s*([^;"]+)', html_out)
        self.assertIsNotNone(new_badge_match, "NEW inner badge should have a border-radius style")
        self.assertIsNotNone(imp_badge_match, "IMPROVEMENT inner badge should have a border-radius style")
        self.assertEqual(new_badge_match.group(1).strip(), imp_badge_match.group(1).strip())
        self.assertEqual(new_badge_match.group(1).strip(), "4px")

        # 5. Preserves existing green and teal theme colors
        self.assertIn("#15803d", html_out)  # NEW green text
        self.assertIn("#0f766e", html_out)  # IMPROVEMENT teal text
        self.assertIn("#bbf7d0", html_out)  # NEW border
        self.assertIn("#99f6e4", html_out)  # IMPROVEMENT border

        # 6. Verify consistent rendering across dialog versions
        dlg = ReleaseSummaryDialog(installed_version="1.1")
        try:
            self.assertFalse(dlg.summary_text.isHidden())
            doc_html = dlg.summary_text.document().toHtml()
            self.assertIn("NEW", doc_html)
            self.assertIn("IMPROVEMENT", doc_html)
        finally:
            dlg.close()
            dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()


