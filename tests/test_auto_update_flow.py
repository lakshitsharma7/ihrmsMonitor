"""Unit tests for Auto-Update logic and pre-update data flush.

Verifies:
1. Version parsing and comparison between installed and server versions.
2. ApiConfig properties for AppController version URL and version string.
3. Pre-update data flush mechanism.
"""

import unittest
from services.update_service import is_newer_version, flush_pending_data_before_update
from config.api_config import ApiConfig


class TestAutoUpdateFlow(unittest.TestCase):

    def test_version_comparisons(self):
        # Current version 1.0.0
        self.assertFalse(is_newer_version("1.0.0", "1.0.0"))
        self.assertFalse(is_newer_version("1.0", "1.0.0"))
        self.assertFalse(is_newer_version("1.00", "1.0.0"))
        self.assertFalse(is_newer_version("0.9.9", "1.0.0"))

        # Newer versions
        self.assertTrue(is_newer_version("1.0.1", "1.0.0"))
        self.assertTrue(is_newer_version("1.1.0", "1.0.0"))
        self.assertTrue(is_newer_version("2.0.0", "1.0.0"))
        self.assertTrue(is_newer_version("v1.0.5", "1.0.0"))
        self.assertTrue(is_newer_version("1.01", "1.00"))

    def test_api_config_appcontroller_properties(self):
        cfg = ApiConfig()
        # Mock details dictionary as returned by AppController
        cfg._details = {
            "activity_tracker_link": "https://indovisionservices.in/info/dev/v15/acitivity-tracker",
            "activity_tracker_version": "1.00",
            "base_url": "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/",
        }

        self.assertEqual(cfg.activity_tracker_link, "https://indovisionservices.in/info/dev/v15/acitivity-tracker")
        self.assertEqual(cfg.activity_tracker_version, "1.00")
        self.assertEqual(cfg.version_url, "https://indovisionservices.in/info/dev/v15/acitivity-tracker")

    def test_flush_pending_data_when_clean(self):
        from unittest.mock import patch
        # When local DB has no unsynced data, flush_pending_data_before_update should return True immediately
        with patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", return_value=[]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]):
            result = flush_pending_data_before_update(max_retries=1)
            self.assertTrue(result)

    def test_flush_pending_data_blocks_update_when_upload_fails(self):
        from unittest.mock import patch, MagicMock
        # When unsynced data exists and cannot be uploaded, it must abort the update (return False)
        mock_session = MagicMock()
        with patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", return_value=[mock_session]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]), \
             patch("services.sync_service.SyncService.sync_activity_now", return_value=False):
            result = flush_pending_data_before_update(max_retries=1)
            self.assertFalse(result)

    def test_pipeline_skips_flush_when_no_pending(self):
        """Pipeline skips directly to download when 0 pending records."""
        from unittest.mock import patch, MagicMock
        from services.update_service import UpdatePipelineWorker

        worker = UpdatePipelineWorker(api_url="https://test.api")
        upload_completed_events = []
        worker.upload_completed.connect(lambda: upload_completed_events.append(True))

        mock_v_resp = MagicMock()
        mock_v_resp.status_code = 200
        mock_v_resp.json.return_value = {
            "version": "9.9.9",
            "download_url": "https://test.api/setup.exe",
        }

        with patch("requests.get", return_value=mock_v_resp), \
             patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", return_value=[]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]), \
             patch("services.update_service.get_updates_directory") as mock_get_dir, \
             patch("services.update_service.install_update_and_restart", return_value=True):
            
            mock_installer = MagicMock()
            mock_installer.exists.return_value = True
            mock_installer.stat.return_value.st_size = 2 * 1024 * 1024
            mock_installer.__str__.return_value = "/fake/iHRMSMonitorSetup_v9.9.9.exe"
            mock_dir = MagicMock()
            mock_dir.__truediv__.return_value = mock_installer
            mock_get_dir.return_value = mock_dir

            # Run the worker synchronously for testing
            worker.run()

            self.assertTrue(len(upload_completed_events) > 0)

    def test_pipeline_halts_and_emits_error_when_upload_fails(self):
        """Pipeline halts before download/install if pre-flush fails."""
        from unittest.mock import patch, MagicMock
        from services.update_service import UpdatePipelineWorker

        worker = UpdatePipelineWorker(api_url="https://test.api")
        error_events = []
        worker.error_occurred.connect(lambda phase, err: error_events.append((phase, err)))

        mock_v_resp = MagicMock()
        mock_v_resp.status_code = 200
        mock_v_resp.json.return_value = {
            "version": "9.9.9",
            "download_url": "https://test.api/setup.exe",
        }

        mock_session = MagicMock()
        with patch("requests.get", return_value=mock_v_resp), \
             patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", return_value=[mock_session]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]), \
             patch("services.sync_service.SyncService.sync_activity_now", return_value=False), \
             patch("services.update_service.install_update_and_restart") as mock_install:

            worker.run()

            # Verify error occurred in uploading_pending phase
            self.assertTrue(any(e[0] == "uploading_pending" for e in error_events))
            # Verify install was NEVER called
            mock_install.assert_not_called()

    def test_update_dialog_auto_advance(self):
        """UpdateDialog automatically transitions states and auto-initiates install."""
        from PySide6.QtWidgets import QApplication
        import sys
        app = QApplication.instance() or QApplication(sys.argv)

        from ui.update_dialog import UpdateDialog
        dialog = UpdateDialog(version="2.0.0", is_force=False)

        # 1. Phase change to uploading_pending
        dialog._on_phase_changed("uploading_pending", "Uploading pending records...")
        self.assertEqual(dialog.install_btn.text(), "Uploading...")
        self.assertFalse(dialog.install_btn.isEnabled())

        # 2. Upload completes
        dialog._on_upload_completed()
        self.assertEqual(dialog.progress_bar.value(), 100)

        # 3. Phase change to downloading
        dialog._on_phase_changed("downloading", "Downloading update...")
        self.assertEqual(dialog.install_btn.text(), "Downloading...")
        self.assertFalse(dialog.install_btn.isEnabled())

        # 4. Download completes - automatically transitions to Restarting
        dialog._on_download_completed("/fake/Setup.exe", "2.0.0")
        self.assertEqual(dialog.progress_bar.value(), 100)
        self.assertEqual(dialog.install_btn.text(), "Restarting...")
        self.assertFalse(dialog.install_btn.isEnabled())

        # 5. Error handling sets Retry button and enables it
        dialog._on_error_occurred("uploading_pending", "Upload timed out")
        self.assertEqual(dialog.install_btn.text(), "Retry")
        self.assertTrue(dialog.install_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
