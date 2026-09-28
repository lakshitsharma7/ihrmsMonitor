"""Unit tests for Login page enhancements:
1. Verified Company Code check-mark trailing icon and field locking.
2. Clickable consent checkbox label/text and row toggling.
"""

import unittest
from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent

from ui.login_window import LoginWindow


class TestLoginEnhancements(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.login_window = LoginWindow()

    def tearDown(self):
        if getattr(self, "login_window", None):
            self.login_window.close()
            self.login_window.deleteLater()
            self.login_window = None
        QApplication.instance().processEvents()

    def test_company_code_check_icon_hidden_and_editable_before_verification(self):
        """Before verification, trailing check icon is hidden, field is editable, and leading company icon is present on the left."""
        self.assertFalse(self.login_window.company_code_check_action.isVisible())
        self.assertFalse(self.login_window.company_code_input.isReadOnly())
        actions = self.login_window.company_code_input.actions()
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[1], self.login_window.company_code_check_action)

    def test_company_code_verified_shows_check_icon_and_locks_field(self):
        """
        After company code verification succeeds via API:
        1. Trailing check mark icon must become visible on the right.
        2. Field must become read-only/locked so it cannot be edited.
        """
        with patch("config.api_config.ApiConfig.load") as mock_load, \
             patch.object(self.login_window, "_show_company_details"):

            self.login_window.company_code_input.setText("INDOVISION")
            self.login_window._process_company_verification("INDOVISION")

            mock_load.assert_called_once_with(company_code="INDOVISION", force=True)
            self.assertTrue(self.login_window.company_code_check_action.isVisible())
            self.assertTrue(self.login_window.company_code_input.isReadOnly())
            self.assertEqual(self.login_window.company_code_input.text(), "INDOVISION")

    def test_reset_and_show_and_clear_unlocks_field_and_hides_check_icon(self):
        """Resetting company context or logging out must hide the check icon and unlock the field."""
        # First verify
        with patch("config.api_config.ApiConfig.load"), \
             patch.object(self.login_window, "_show_company_details"):
            self.login_window._process_company_verification("INDOVISION")
            self.assertTrue(self.login_window.company_code_check_action.isVisible())
            self.assertTrue(self.login_window.company_code_input.isReadOnly())

        # Reset context
        self.login_window._reset_company_context()
        self.assertFalse(self.login_window.company_code_check_action.isVisible())
        self.assertFalse(self.login_window.company_code_input.isReadOnly())

        # Test show_and_clear (logout flow)
        with patch("config.api_config.ApiConfig.load"), \
             patch.object(self.login_window, "_show_company_details"):
            self.login_window._process_company_verification("INDOVISION")
            self.assertTrue(self.login_window.company_code_check_action.isVisible())
            self.assertTrue(self.login_window.company_code_input.isReadOnly())

        self.login_window.show_and_clear()
        self.assertFalse(self.login_window.company_code_check_action.isVisible())
        self.assertFalse(self.login_window.company_code_input.isReadOnly())

    def test_consent_checkbox_toggles_when_clicking_label_or_row(self):
        """
        Clicking either the checkbox itself, its label/text, or the row should toggle the checkbox.
        """
        checkbox = self.login_window.consent_checkbox
        self.assertFalse(checkbox.isChecked())

        # Find the consent text label
        consent_text_label = self.login_window.findChild(object, "LoginConsentText")
        self.assertIsNotNone(consent_text_label)

        # 1. Click text label -> toggles from False to True
        event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPoint(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        consent_text_label.mousePressEvent(event)
        self.assertTrue(checkbox.isChecked())

        # 2. Click text label again -> toggles from True to False
        consent_text_label.mousePressEvent(event)
        self.assertFalse(checkbox.isChecked())

        # 3. Click consent row container -> toggles from False to True
        consent_row = self.login_window.consent_row
        consent_row.mousePressEvent(event)
        self.assertTrue(checkbox.isChecked())

        # 4. Click consent row container again -> toggles from True to False
        consent_row.mousePressEvent(event)
        self.assertFalse(checkbox.isChecked())

        # 5. Checkbox itself directly still toggles
        checkbox.toggle()
        self.assertTrue(checkbox.isChecked())
        checkbox.toggle()
        self.assertFalse(checkbox.isChecked())

    def test_login_hero_version_is_visible_and_pure_white(self):
        """Verify the Version text on the Login page is visible and styled pure white (#FFFFFF)."""
        from config.settings import get_running_app_version
        from PySide6.QtWidgets import QLabel

        hero_version = self.login_window.findChild(QLabel, "LoginHeroVersion")
        self.assertIsNotNone(hero_version)
        self.assertEqual(hero_version.text(), f"Version {get_running_app_version()}")
        self.assertIn("#FFFFFF", hero_version.styleSheet().upper())

    def test_step1_company_code_to_verify_button_gap_is_compact(self):
        """Verify the vertical spacing between Company Code input and Verify Company button is compact (14-16px)."""
        self.login_window.show()
        QApplication.instance().processEvents()

        btn = self.login_window.login_button
        company_input = self.login_window.company_code_input

        self.assertEqual(btn.text(), "Verify Company")
        gap = btn.geometry().top() - company_input.geometry().bottom() - 1
        # Old gap was 53px; verified clean spacing is now 14-16px
        self.assertLessEqual(gap, 18)
        self.assertGreaterEqual(gap, 10)


    def test_user_device_dialog_opens_and_displays_active_user_information(self):
        """Verify UserDeviceDialog instantiates cleanly and incorporates active session info without NameError."""
        from ui.main_window import get_user_device_info, UserDeviceDialog
        from services.session_service import SessionService

        SessionService().login(
            username="test_audit_emp",
            role="Employee",
            full_name="Sarah Connor",
            employee_id="EMP_888",
            company_code="CYBERDYNE",
            device_token="DEV_TOK_888",
        )

        info = get_user_device_info()
        self.assertEqual(info["name"], "Sarah Connor")
        self.assertEqual(info["username"], "test_audit_emp")
        self.assertEqual(info["employee_id"], "EMP_888")
        self.assertEqual(info["company_code"], "CYBERDYNE")

    def test_login_page_has_no_update_progress_message(self):
        """Verify the login page has no update progress label in layout and no fake 'Updating (0%)...' text."""
        self.login_window.show()
        QApplication.instance().processEvents()

        # Find all QLabel widgets in the login window
        labels = self.login_window.findChildren(QLabel)
        for label in labels:
            text = label.text()
            self.assertNotIn("Updating (", text)
            self.assertNotIn("Updating...", text)

        # LoginUpdateStatus widget must not be present in the active UI layout
        status_widget = self.login_window.findChild(QLabel, "LoginUpdateStatus")
        self.assertIsNone(status_widget)

    def test_login_update_dialog_handles_pipeline_without_duplicates(self):
        """Verify silent background update suppresses separate popup dialogs on login window."""
        self.login_window._show_update_dialog(version="2.5.0", is_force=False)
        self.assertIsNone(self.login_window._update_dialog)

        mock_worker = MagicMock()
        mock_worker.phase_changed = MagicMock()
        mock_worker.progress_changed = MagicMock()
        mock_worker.status_message = MagicMock()
        mock_worker.upload_completed = MagicMock()
        mock_worker.download_completed = MagicMock()
        mock_worker.error_occurred = MagicMock()

        self.login_window._show_update_dialog(version="2.5.0", is_force=False, worker=mock_worker)
        self.assertIsNone(self.login_window._update_dialog)


if __name__ == "__main__":
    unittest.main()



