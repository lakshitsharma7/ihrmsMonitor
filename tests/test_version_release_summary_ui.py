"""Unit tests for Status card Version button layout and Release Summary interaction."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QLabel, QPushButton, QWidget

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
            self.assertEqual(page.version_button.text(), "Version: 2.5.0")
            self.assertEqual(page.version_label.text(), "Version: 2.5.0")

            page.set_version("v3.1")
            self.assertEqual(page.version_button.text(), "Version: 3.1")
            self.assertEqual(page.version_label.text(), "Version: 3.1")
        finally:
            page.close()
            page.deleteLater()

    def test_version_badge_displays_version_number_and_never_only_prefix(self):
        """Verify badge displays 'Version: 1.1' instead of only 'Version:', handles empty/prefix inputs, and transitions dynamically."""
        page = DashboardPage(self.mock_service)
        try:
            running_v = get_running_app_version()
            # Initial state
            self.assertEqual(page.version_label.text(), f"Version: {running_v}")
            self.assertEqual(page.version_button.text(), f"Version: {running_v}")
            self.assertNotEqual(page.version_label.text(), "Version:")
            self.assertNotEqual(page.version_label.text(), "Version")

            # Passing 'Version:' should cleanly resolve using single source of truth
            page.set_version("Version:")
            self.assertEqual(page.version_label.text(), f"Version: {running_v}")

            # Passing empty string or None should cleanly fallback to running version
            page.set_version("")
            self.assertEqual(page.version_label.text(), f"Version: {running_v}")
            page.set_version(None)
            self.assertEqual(page.version_label.text(), f"Version: {running_v}")

            # Dynamic updates (1.1 -> 1.2 -> 1.3)
            page.set_version("1.2")
            self.assertEqual(page.version_label.text(), "Version: 1.2")
            self.assertEqual(page.version_button.text(), "Version: 1.2")

            page.set_version("1.3")
            self.assertEqual(page.version_label.text(), "Version: 1.3")
            self.assertEqual(page.version_button.text(), "Version: 1.3")

            # Verify sizeHint does not clip the version text
            self.assertGreaterEqual(page.version_button.sizeHint().width(), page.version_label.sizeHint().width())
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

            # Summary text is displayed for installed version in professional category-wise format
            if sel_rel.get("summary"):
                self.assertFalse(dlg.summary_text.isHidden())
                self.assertTrue(dlg.empty_notes_label.isHidden())
                pt = dlg.summary_text.toPlainText()
                html_txt = dlg.summary_text.toHtml()
                # Categories present
                self.assertIn("NEW", pt)
                self.assertIn("IMPROVEMENT", pt)
                # Green styling for NEW and IMPROVEMENT
                self.assertIn("#15803d", html_txt)
                self.assertIn("#0f766e", html_txt)
                # Empty FIX category must be hidden
                self.assertNotIn("FIX", pt)
                self.assertNotIn("#b91c1c", html_txt)
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

            # If summary exists, displayed in summary_text as categorized HTML
            if sel_rel.get("summary"):
                self.assertFalse(dlg.summary_text.isHidden())
                self.assertTrue(dlg.empty_notes_label.isHidden())
                self.assertGreater(len(dlg.summary_text.toPlainText()), 10)
                self.assertIn("<table", dlg.summary_text.toHtml().lower())
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
        releases = get_all_releases(installed_version="1.0.0", server_version="2.5")
        self.assertTrue(len(releases) >= 2)
        # First item is the newer server update
        self.assertEqual(releases[0]["version"], "2.5")
        self.assertTrue(releases[0]["is_update"])

        # Second item is installed version
        self.assertEqual(releases[1]["version"], "1.0.0")
        self.assertTrue(releases[1]["is_installed"])

    def test_release_notes_categorization_and_colors_across_versions(self):
        """Verify categorization, styling colors, and empty category suppression across versions."""
        dlg = ReleaseSummaryDialog(installed_version="1.1")
        dlg.show()
        try:
            # 1. Test Version 1.1 (selected by default)
            pt_11 = dlg.summary_text.toPlainText()
            html_11 = dlg.summary_text.toHtml()
            self.assertIn("NEW", pt_11)
            self.assertIn("IMPROVEMENT", pt_11)
            self.assertNotIn("FIX", pt_11)  # Empty FIX category hidden
            self.assertIn("#15803d", html_11)  # Green for NEW
            self.assertIn("#0f766e", html_11)  # Teal/green for IMPROVEMENT
            self.assertNotIn("#b91c1c", html_11)  # Red absent when no fixes

            # 2. Test Version 2.0.1 (has bug fixes)
            idx_201 = None
            for i in range(dlg.version_combo.count()):
                if dlg.version_combo.itemData(i).get("version") == "2.0.1":
                    idx_201 = i
                    break
            if idx_201 is not None:
                dlg.version_combo.setCurrentIndex(idx_201)
                pt_201 = dlg.summary_text.toPlainText()
                html_201 = dlg.summary_text.toHtml()
                self.assertIn("NEW", pt_201)
                self.assertIn("IMPROVEMENT", pt_201)
                self.assertIn("FIX", pt_201)  # Has bug fixes
                self.assertIn("#15803d", html_201)
                self.assertIn("#0f766e", html_201)
                self.assertIn("#b91c1c", html_201)  # Red for FIX
                self.assertIn("#fee2e2", html_201)  # Light red badge background
                self.assertIn("#fff5f5", html_201)  # Subtle light-red card background
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_switching_versions_updates_notes_dynamically(self):
        """Verify selecting another version dynamically displays that version's actual notes under proper categories."""
        dlg = ReleaseSummaryDialog(installed_version="1.1")
        dlg.show()
        try:
            # Start at 1.1
            self.assertIn("Native macOS & Windows", dlg.summary_text.toPlainText())

            # Switch to 1.0
            idx_10 = None
            for i in range(dlg.version_combo.count()):
                if dlg.version_combo.itemData(i).get("version") == "1.0":
                    idx_10 = i
                    break
            self.assertIsNotNone(idx_10)
            dlg.version_combo.setCurrentIndex(idx_10)
            pt_10 = dlg.summary_text.toPlainText()
            self.assertIn("Current application version unified to 1.0", pt_10)
            self.assertNotIn("Native macOS & Windows production distribution", pt_10)

            # Switch back to 1.1
            idx_11 = None
            for i in range(dlg.version_combo.count()):
                if dlg.version_combo.itemData(i).get("version") == "1.1":
                    idx_11 = i
                    break
            self.assertIsNotNone(idx_11)
            dlg.version_combo.setCurrentIndex(idx_11)
            self.assertIn("Native macOS & Windows", dlg.summary_text.toPlainText())
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_structured_category_support(self):
        """Verify pre-structured category dictionaries are rendered correctly without duplicate parsing."""
        from ui.release_summary_dialog import render_categorized_summary_html
        custom_cats = {
            "NEW": ["Custom shiny feature"],
            "IMPROVEMENT": ["Speed optimization 2x"],
            "FIX": ["Crash on shutdown resolved"],
        }
        rendered = render_categorized_summary_html(custom_cats)
        self.assertIn("Custom shiny feature", rendered)
        self.assertIn("Speed optimization 2x", rendered)
        self.assertIn("Crash on shutdown resolved", rendered)
        self.assertIn("#15803d", rendered)
        self.assertIn("#0f766e", rendered)
        self.assertIn("#b91c1c", rendered)

    def test_top_right_close_button_flags_and_close_event(self):
        """Verify window flags include WindowCloseButtonHint and QCloseEvent closes only the dialog."""
        parent = QWidget()
        parent.show()
        try:
            dlg = ReleaseSummaryDialog(installed_version="1.1", parent=parent)
            dlg.show()
            # 1. WindowCloseButtonHint must be enabled
            flags = dlg.windowFlags()
            self.assertTrue(bool(flags & Qt.WindowCloseButtonHint), "WindowCloseButtonHint must be set")

            # 2. ContextHelp button must be disabled
            self.assertFalse(bool(flags & Qt.WindowContextHelpButtonHint), "WindowContextHelpButtonHint must NOT be set")

            # 3. Dispatching QCloseEvent (equivalent to clicking top-right [X])
            from PySide6.QtGui import QCloseEvent
            ev = QCloseEvent()
            _app.sendEvent(dlg, ev)

            # Event is accepted, dialog is closed, parent remains open
            self.assertTrue(ev.isAccepted())
            self.assertFalse(dlg.isVisible(), "Dialog must be closed after closeEvent")
            self.assertTrue(parent.isVisible(), "Parent window must remain open")
        finally:
            parent.close()
            parent.deleteLater()

    def test_bottom_close_button_and_reopen(self):
        """Verify bottom Close button dismisses dialog, and dialog can be reopened normally."""
        parent = QWidget()
        parent.show()
        try:
            # 1. Open first instance and close via bottom close_btn
            dlg1 = ReleaseSummaryDialog(installed_version="1.1", parent=parent)
            dlg1.show()
            self.assertTrue(dlg1.isVisible())
            dlg1.close_btn.click()
            self.assertFalse(dlg1.isVisible(), "Dialog must be closed after close_btn click")
            self.assertTrue(parent.isVisible(), "Parent window must remain open")

            # 2. Reopen second instance and close via closeEvent / [X]
            dlg2 = ReleaseSummaryDialog(installed_version="1.1", parent=parent)
            dlg2.show()
            self.assertTrue(dlg2.isVisible())
            dlg2.close()
            self.assertFalse(dlg2.isVisible(), "Dialog must be closed after close()")
            self.assertTrue(parent.isVisible(), "Parent window must remain open")
        finally:
            parent.close()
            parent.deleteLater()

    def test_version_selector_search_filtering_and_restoration(self):
        """Verify version search input filters versions dynamically and restores list on clear."""
        from ui.release_summary_dialog import SearchableVersionComboBox
        dlg = ReleaseSummaryDialog(installed_version="1.1")
        dlg.show()
        try:
            self.assertIsInstance(dlg.version_combo, SearchableVersionComboBox)
            dlg.version_combo.showPopup()

            popup = dlg.version_combo._popup_frame
            self.assertIsNotNone(popup)
            self.assertTrue(popup.isVisible())

            search_input = dlg.version_combo._search_input
            list_widget = dlg.version_combo._list_widget
            self.assertEqual(search_input.placeholderText(), "Search versions...")

            # 1. Total initial count in list matches entries
            initial_count = dlg.version_combo.count()
            self.assertEqual(list_widget.count(), initial_count)

            # 2. Search for 2.0 (should match 2.0.2, 2.0.1, 2.0.0)
            search_input.setText("2.0")
            self.assertEqual(list_widget.count(), 3)
            for i in range(list_widget.count()):
                self.assertIn("2.0", list_widget.item(i).text())

            # 3. Case-insensitive search for version 1.1
            search_input.setText("VERSION 1.1")
            self.assertEqual(list_widget.count(), 1)
            self.assertIn("1.1", list_widget.item(0).text())
            self.assertIn("(Installed)", list_widget.item(0).text())

            # 4. Search for non-existent version shows "No versions found"
            search_input.setText("99.99")
            self.assertEqual(list_widget.count(), 1)
            self.assertEqual(list_widget.item(0).text(), "No versions found")
            self.assertEqual(list_widget.item(0).flags(), Qt.ItemFlag.NoItemFlags)

            # 5. Clear search input restores all items
            search_input.setText("")
            self.assertEqual(list_widget.count(), initial_count)
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_version_selector_dropdown_selection_updates_release_summary(self):
        """Verify selecting a filtered item in dropdown updates the release summary content and details."""
        dlg = ReleaseSummaryDialog(installed_version="1.1")
        dlg.show()
        try:
            dlg.version_combo.showPopup()
            search_input = dlg.version_combo._search_input
            list_widget = dlg.version_combo._list_widget

            # Search for 2.0.2 and select it
            search_input.setText("2.0.2")
            self.assertEqual(list_widget.count(), 1)
            item_202 = list_widget.item(0)
            self.assertIn("2.0.2", item_202.text())

            # Click the item
            dlg.version_combo._on_item_clicked(item_202)

            # Popup should be hidden
            self.assertFalse(dlg.version_combo._popup_frame.isVisible())

            # Selected version updated
            self.assertEqual(dlg.version_combo.currentData()["version"], "2.0.2")
            self.assertIn("2.0.2", dlg.detail_version_label.text())

            # Release summary content updated with 2.0.2 notes
            self.assertIn("reachability", dlg.summary_text.toPlainText().lower())
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_version_selector_scrolling_and_max_height(self):
        """Verify dropdown list height is capped within 250-300px and vertical scrollbar is accessible."""
        from ui.release_summary_dialog import SearchableVersionComboBox
        combo = SearchableVersionComboBox()
        # Add 15 versions to exceed default height
        for i in range(15):
            combo.addItem(f"Version 3.{i}", {"version": f"3.{i}"})

        combo.show()
        combo.showPopup()
        try:
            list_widget = combo._list_widget
            self.assertLessEqual(list_widget.height(), 260)
            self.assertLessEqual(combo._popup_frame.sizeHint().height(), 300)
            self.assertEqual(list_widget.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            # Search input is above the list widget and stays visible
            self.assertTrue(combo._search_input.isVisible())
        finally:
            combo.hidePopup()
            combo.close()
            combo.deleteLater()
