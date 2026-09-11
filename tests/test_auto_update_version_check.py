"""Unit tests for auto-update version check and comparison logic."""

import unittest
from unittest.mock import MagicMock, patch

from services.update_service import is_newer_version, parse_version, UpdateCheckWorker


class TestAutoUpdateVersionCheck(unittest.TestCase):
    """Test suite verifying auto-update version comparison behavior."""

    def test_version_parsing(self):
        """Test parse_version produces correct comparable integer tuples."""
        self.assertEqual(parse_version("2.0.1"), (2, 0, 1))
        self.assertEqual(parse_version("2.0.2"), (2, 0, 2))
        self.assertEqual(parse_version("2.1"), (2, 1))
        self.assertEqual(parse_version("v2.0.1"), (2, 0, 1))
        self.assertEqual(parse_version("1.0.0"), (1, 0, 0))
        self.assertEqual(parse_version("NA"), (0,))
        self.assertEqual(parse_version(""), (0,))
        self.assertEqual(parse_version(None), (0,))

    def test_required_version_comparison_cases(self):
        """
        Verify the 4 required version comparison test cases:
        1. Current 2.0.1 + API 2.0.1 -> False (no update message)
        2. Current 2.0.1 + API 2.0.2 -> True (update message shown)
        3. Current 2.0.2 + API 2.0.1 -> False (no update)
        4. Current 2.0.1 + API 2.1   -> True (update shown)
        """
        # Case 1: Same version -> No update
        self.assertFalse(
            is_newer_version(server_version="2.0.1", current_version="2.0.1"),
            "Current 2.0.1 + API 2.0.1 must NOT trigger update",
        )

        # Case 2: Newer patch version -> Update
        self.assertTrue(
            is_newer_version(server_version="2.0.2", current_version="2.0.1"),
            "Current 2.0.1 + API 2.0.2 MUST trigger update",
        )

        # Case 3: Server version is older -> No update
        self.assertFalse(
            is_newer_version(server_version="2.0.1", current_version="2.0.2"),
            "Current 2.0.2 + API 2.0.1 must NOT trigger update",
        )

        # Case 4: Newer minor version -> Update
        self.assertTrue(
            is_newer_version(server_version="2.1", current_version="2.0.1"),
            "Current 2.0.1 + API 2.1 MUST trigger update",
        )

    def test_additional_boundary_version_cases(self):
        """Verify additional edge cases."""
        self.assertFalse(is_newer_version("2.0.0", "2.0.1"))
        self.assertTrue(is_newer_version("3.0.0", "2.0.1"))
        self.assertFalse(is_newer_version("NA", "2.0.1"))
        self.assertFalse(is_newer_version("", "2.0.1"))
        self.assertFalse(is_newer_version(None, "2.0.1"))
        self.assertTrue(is_newer_version("2.0.1.1", "2.0.1"))

    def test_update_check_worker_same_version_does_not_emit_update(self):
        """Verify UpdateCheckWorker emits check_completed(False) and NO update_available signal when versions match."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)

        update_available_called = []
        check_completed_results = []

        worker.update_available.connect(lambda ver, url, force: update_available_called.append(ver))
        worker.check_completed.connect(lambda has_update: check_completed_results.append(has_update))

        # Mock API returning identical version 2.0.1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 1,
            "version_code": "2.0.1",
            "download_url": "https://mock.example.com/setup.exe",
        }

        with patch("services.update_service.get_running_app_version", return_value="2.0.1"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        self.assertEqual(update_available_called, [], "UpdateAvailable MUST NOT be emitted when versions match")
        self.assertEqual(check_completed_results, [False], "CheckCompleted must return False")

    def test_update_check_worker_newer_version_emits_update(self):
        """Verify UpdateCheckWorker emits update_available when server version is newer."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)

        update_available_called = []
        check_completed_results = []

        worker.update_available.connect(lambda ver, url, force: update_available_called.append(ver))
        worker.check_completed.connect(lambda has_update: check_completed_results.append(has_update))

        # Mock API returning newer version 2.0.2
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 1,
            "version_code": "2.0.2",
            "download_url": "https://mock.example.com/setup.exe",
        }

        with patch("services.update_service.get_running_app_version", return_value="2.0.1"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        self.assertEqual(update_available_called, ["2.0.2"], "UpdateAvailable MUST be emitted for 2.0.2")
        self.assertEqual(check_completed_results, [True], "CheckCompleted must return True")


if __name__ == "__main__":
    unittest.main()
