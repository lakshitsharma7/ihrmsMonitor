"""Unit tests for Status card Version button layout and Release Summary interaction."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton, QLabel, QComboBox

_app = QApplication.instance() or QApplication([])

from config.settings import get_running_app_version
from services.activity_service import ActivityService
from services.session_service import SessionService
from ui.dashboard import DashboardPage
from ui.release_summary_dialog import ReleaseSummaryDialog, get_all_releases


class TestVersionReleaseSummaryUI(unittest.TestCase):
    def setUp(self):
        SessionService().clear()
        SessionService().login(
            username="dinesh",
            role="Employee",
            full_name="Dinesh Dev",
        )
        self.mock_service = MagicMock(spec=ActivityService)
        self.mock_service.get_today_total_seconds.return_value = 120
        self.mock_service.get_persisted_daily_active_seconds.return_value = 120
        self.mock_service.get_uploaded_records_count.return_value = 2
        self.mock_service.get_today_total_idle_seconds.return_value = 15
        self.mock_service.get_today_timeline.return_value = []

    def tearDown(self):
        SessionService().clear()

    # ------------------------------------------------------------------
    # 1. Version Button Position & Appearance on Right Side of Status Card
    # ------------------------------------------------------------------

    def test_version_button_on_right_side_of_status_card(self):
        """Verify Version is moved to the right side of the Status card as a clickable button."""
        page = DashboardPage(self.mock_service)
        try:
            status_card = None
            for gb in page.findChildren(QGroupBox):
                if gb.title() == "Status":
                    status_card = gb
                    break
            self.assertIsNotNone(status_card, "Status group box not found")

            # Must have version_button as a QPushButton
            self.assertTrue(hasattr(page, "version_button"))
            self.assertIsInstance(page.version_button, QPushButton)
            self.assertEqual(page.version_button.cursor().shape(), Qt.CursorShape.PointingHandCursor)

            # Version button must be on the right side of status_row
            status_row = status_card.layout().itemAt(0).layout()
            self.assertIsNotNone(status_row)
            # Last widget in status_row is version_button
            last_item = status_row.itemAt(status_row.count() - 1).widget()
            self.assertIs(last_item, page.version_button)

            # Must contain the dynamically fetched installed version
            installed = get_running_app_version()
            self.assertIn(installed, page.version_button.text())

            # Preserves Status, Idle Time, Last Update, and Paused button
            self.assertTrue(hasattr(page, "network_status_label"))
            self.assertTrue(hasattr(page, "idle_time_label"))
            self.assertTrue(hasattr(page, "last_update_label"))
            self.assertTrue(hasattr(page, "workpulse_toggle_button"))
        finally:
            page.close()
            page.deleteLater()

    def test_version_button_dynamic_text_update(self):
        """Verify calling set_version updates the version button dynamically without hardcoding."""
        page = DashboardPage(self.mock_service)
        try:
            page.set_version("2.5.0")
            self.assertIn("2.5.0", page.version_button.text())
            self.assertIn("2.5.0", page.version_label.text())

            page.set_version("v3.1")
            self.assertIn("3.1", page.version_button.text())
        finally:
            page.close()
            page.deleteLater()

    def test_click_version_button_opens_release_summary_dialog(self):
        """Verify clicking the Version button opens the ReleaseSummaryDialog."""
        page = DashboardPage(self.mock_service)
        try:
            with patch.object(ReleaseSummaryDialog, "exec") as mock_exec:
                page.version_button.click()
                mock_exec.assert_called_once()
        finally:
            page.close()
            page.deleteLater()

    # ------------------------------------------------------------------
    # 2. Release Summary Dialog Data & Behavior
    # ------------------------------------------------------------------

    def test_dialog_displays_installed_version_dynamically(self):
        """Verify ReleaseSummaryDialog displays installed version dynamically and marks it as Installed."""
        installed = get_running_app_version()
        dlg = ReleaseSummaryDialog(installed_version=installed)
        dlg.show()
        try:
            # Combo box has installed version selected
            sel_rel = dlg.version_combo.currentData()
            self.assertEqual(sel_rel["version"], installed)
            self.assertTrue(sel_rel["is_installed"])
            self.assertFalse(sel_rel["is_update"])

            # Detail badge says Installed
            self.assertEqual(dlg.detail_badge.text(), "Installed")
            self.assertFalse(dlg.detail_badge.isHidden())

            # Detail version label matches installed
            self.assertIn(installed, dlg.detail_version_label.text())

            # Summary text is displayed for installed version if available
            if sel_rel.get("summary"):
                self.assertFalse(dlg.summary_text.isHidden())
                self.assertTrue(dlg.empty_notes_label.isHidden())
                self.assertIn(sel_rel["summary"][:20], dlg.summary_text.toPlainText())
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_dialog_distinguishes_newer_version_update_available(self):
        """Verify newer server version is clearly distinguished as Update Available."""
        installed = "1.1"
        newer_server = "1.2"
        dlg = ReleaseSummaryDialog(installed_version=installed, server_version=newer_server)
        dlg.show()
        try:
            # Check items in combo box
            combo_texts = [dlg.version_combo.itemText(i) for i in range(dlg.version_combo.count())]
            self.assertTrue(any("Update Available" in t for t in combo_texts))
            self.assertTrue(any("Installed" in t for t in combo_texts))

            # Select the update version (item 0)
            dlg.version_combo.setCurrentIndex(0)
            sel_rel = dlg.version_combo.currentData()
            self.assertEqual(sel_rel["version"], newer_server)
            self.assertTrue(sel_rel["is_update"])
            self.assertFalse(sel_rel["is_installed"])

            # Detail badge says Update Available
            self.assertEqual(dlg.detail_badge.text(), "Update Available")
            self.assertFalse(dlg.update_action_btn.isHidden())
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_dialog_does_not_show_update_when_server_version_equal_or_lower(self):
        """Verify update is NOT shown when server version <= installed version."""
        # 1. Server version == Installed version
        dlg_same = ReleaseSummaryDialog(installed_version="1.1", server_version="1.1")
        dlg_same.show()
        try:
            combo_texts = [dlg_same.version_combo.itemText(i) for i in range(dlg_same.version_combo.count())]
            self.assertFalse(any("Update Available" in t for t in combo_texts))
        finally:
            dlg_same.close()
            dlg_same.deleteLater()

        # 2. Server version < Installed version
        dlg_lower = ReleaseSummaryDialog(installed_version="1.1", server_version="1.0")
        dlg_lower.show()
        try:
            combo_texts = [dlg_lower.version_combo.itemText(i) for i in range(dlg_lower.version_combo.count())]
            self.assertFalse(any("Update Available" in t for t in combo_texts))
        finally:
            dlg_lower.close()
            dlg_lower.deleteLater()

    def test_dialog_older_version_selection_updates_summary(self):
        """Verify picking an older version from dropdown updates the displayed release summary and date."""
        dlg = ReleaseSummaryDialog(installed_version="1.1")
        dlg.show()
        try:
            # Find an older version index, e.g. 1.0 or 2.0.2
            older_idx = None
            for i in range(dlg.version_combo.count()):
                rel = dlg.version_combo.itemData(i)
                if not rel.get("is_installed") and not rel.get("is_update"):
                    older_idx = i
                    break
            self.assertIsNotNone(older_idx, "Older version must be present in history")

            # Select older version
            dlg.version_combo.setCurrentIndex(older_idx)
            sel_rel = dlg.version_combo.currentData()

            # Badge marks Previous Version
            self.assertEqual(dlg.detail_badge.text(), "Previous Version")
            self.assertIn(sel_rel["version"], dlg.detail_version_label.text())

            # If date exists, displayed
            if sel_rel.get("date"):
                self.assertFalse(dlg.detail_date_label.isHidden())
                self.assertIn(sel_rel["date"], dlg.detail_date_label.text())

            # If summary exists, displayed in summary_text
            if sel_rel.get("summary"):
                self.assertFalse(dlg.summary_text.isHidden())
                self.assertTrue(dlg.empty_notes_label.isHidden())
                self.assertEqual(dlg.summary_text.toPlainText(), sel_rel["summary"])
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_dialog_missing_release_notes_shows_fallback_without_fabrication(self):
        """Verify versions without release notes display the required fallback message."""
        installed = "1.1"
        # Server version has no changelog entry in version.log
        dlg = ReleaseSummaryDialog(installed_version=installed, server_version="9.9.9")
        dlg.show()
        try:
            # Select 9.9.9
            dlg.version_combo.setCurrentIndex(0)
            self.assertEqual(dlg.version_combo.currentData()["version"], "9.9.9")

            # Must display exact fallback message
            self.assertFalse(dlg.empty_notes_label.isHidden())
            self.assertTrue(dlg.summary_text.isHidden())
            self.assertEqual(dlg.empty_notes_label.text(), "Release notes are not available for this version.")
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_get_all_releases_order_newest_to_oldest(self):
        """Verify releases list is ordered newest to oldest."""
        releases = get_all_releases(installed_version="1.1", server_version="2.5")
        self.assertTrue(len(releases) >= 2)
        # First item is the newer server update
        self.assertEqual(releases[0]["version"], "2.5")
        self.assertTrue(releases[0]["is_update"])

        # Second item is installed version
        self.assertEqual(releases[1]["version"], "1.1")
        self.assertTrue(releases[1]["is_installed"])
