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


if __name__ == "__main__":
    unittest.main()
