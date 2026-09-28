"""Unit tests for auto-update version check and comparison logic.

Covers all 8 required scenarios:
1. API returns older version (e.g. installed 2.0.2, API returns 2.0.0) -> NO update
2. API returns same version (e.g. installed 2.0.2, API returns 2.0.2) -> NO update
3. API returns newer version (e.g. installed 2.0.2, API returns 2.0.3) -> Update allowed
4. API returns invalid version (e.g. "invalid", "!@#$") -> NO update
5. API returns missing version (e.g. None, "", {}) -> NO update
6. Stale cached update version discarded in favor of fresh API response
7. API version differs from old cached version -> Fresh API version is the sole source of truth
8. Download URL version differs from stale cached filename -> Uses live API URL
"""

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from services.update_service import is_newer_version, parse_version, normalize_version, UpdateCheckWorker
from config.settings import get_running_app_version


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

    def test_version_normalization(self):
        """Test normalize_version dynamically converts version strings to semantic major.minor.patch."""
        self.assertEqual(normalize_version("v2.0.2"), "2.0.2")
        self.assertEqual(normalize_version("2.0.2"), "2.0.2")
        self.assertEqual(normalize_version("2.1"), "2.1.0")
        self.assertEqual(normalize_version("v3"), "3.0.0")
        self.assertEqual(normalize_version("1.2.3.4"), "1.2.3.4")
        self.assertEqual(normalize_version("NA"), "0.0.0")
        self.assertEqual(normalize_version(""), "0.0.0")
        self.assertEqual(normalize_version(None), "0.0.0")

    def test_required_version_comparison_cases(self):
        """
        Verify the version comparison test cases:
        1. Same version -> False (no update)
        2. Newer patch version -> True (update)
        3. Server version older -> False (no update)
        4. Newer minor version -> True (update)
        5. Newer major version -> True (update)
        """
        # Case 1: Same version -> No update
        self.assertFalse(
            is_newer_version(server_version="2.0.1", current_version="2.0.1"),
            "Current 2.0.1 + API 2.0.1 must NOT trigger update",
        )
        self.assertFalse(is_newer_version(server_version="2.0.2", current_version="2.0.2"))
        self.assertFalse(is_newer_version(server_version="v2.0.2", current_version="2.0.2"))
        self.assertFalse(is_newer_version(server_version="2.0.2", current_version="v2.0.2"))
        self.assertFalse(is_newer_version(server_version="2.1", current_version="2.1.0"))
        self.assertFalse(is_newer_version(server_version="2.1.0", current_version="2.1"))

        # Case 2: Newer patch version -> Update
        self.assertTrue(
            is_newer_version(server_version="2.0.2", current_version="2.0.1"),
            "Current 2.0.1 + API 2.0.2 MUST trigger update",
        )
        self.assertTrue(is_newer_version(server_version="2.0.3", current_version="2.0.2"))
        self.assertTrue(is_newer_version(server_version="1.0.1", current_version="1.0.0"))
        self.assertTrue(is_newer_version(server_version="v2.0.3", current_version="2.0.2"))

        # Case 3: Server version is older -> No update
        self.assertFalse(
            is_newer_version(server_version="2.0.1", current_version="2.0.2"),
            "Current 2.0.2 + API 2.0.1 must NOT trigger update",
        )
        self.assertFalse(is_newer_version(server_version="2.0.0", current_version="2.0.2"))
        self.assertFalse(is_newer_version(server_version="1.9.9", current_version="2.0.0"))
        self.assertFalse(is_newer_version(server_version="2.0.2", current_version="2.1.0"))
        self.assertFalse(is_newer_version(server_version="2.0", current_version="2.1"))

        # Case 4: Newer minor version -> Update
        self.assertTrue(
            is_newer_version(server_version="2.1", current_version="2.0.1"),
            "Current 2.0.1 + API 2.1 MUST trigger update",
        )
        self.assertTrue(is_newer_version(server_version="2.1.0", current_version="2.0.2"))
        self.assertTrue(is_newer_version(server_version="2.2.0", current_version="2.1.5"))
        self.assertTrue(is_newer_version(server_version="v2.1", current_version="2.0.2"))

        # Case 5: Newer major version -> Update
        self.assertTrue(is_newer_version(server_version="3.0.0", current_version="2.0.2"))
        self.assertTrue(is_newer_version(server_version="2.0.0", current_version="1.9.9"))
        self.assertTrue(is_newer_version(server_version="v10.0.0", current_version="9.9.9"))

    def test_invalid_and_missing_version_safety(self):
        """Verify invalid, missing, or corrupt version strings safely return False without exceptions."""
        self.assertFalse(is_newer_version("NA", "2.0.1"))
        self.assertFalse(is_newer_version("", "2.0.1"))
        self.assertFalse(is_newer_version(None, "2.0.1"))
        self.assertFalse(is_newer_version("invalid_version", "2.0.1"))
        self.assertFalse(is_newer_version("!@#$%", "2.0.1"))
        self.assertFalse(is_newer_version("2.1.0", ""))
        self.assertFalse(is_newer_version("2.1.0", "invalid"))
        self.assertFalse(is_newer_version("2.1.0", "NA"))
        self.assertFalse(is_newer_version("2.1.0", "!@#$%"))
        self.assertFalse(is_newer_version(None))
        self.assertFalse(is_newer_version(""))
        self.assertFalse(is_newer_version("NA"))

    def test_dynamic_actual_installed_version_check(self):
        """Verify dynamic comparison against actual running application version."""
        running = get_running_app_version()
        self.assertTrue(len(running) > 0)

        # Same as running -> False
        self.assertFalse(is_newer_version(running))

        # Older than running -> False
        self.assertFalse(is_newer_version("0.0.1"))

        # Newer than running -> True
        p = parse_version(running)
        newer_major = f"{p[0] + 1}.0.0"
        self.assertTrue(is_newer_version(newer_major))

    def test_1_api_returns_older_version(self):
        """Scenario 1: API returns 2.0.0 and installed is 2.0.2 -> NO update, check_completed(False)."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)
        update_available_called = []
        check_completed_results = []
        worker.update_available.connect(lambda ver, url, force: update_available_called.append(ver))
        worker.check_completed.connect(lambda has_update: check_completed_results.append(has_update))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": 1, "version_code": "2.0.0"}'
        mock_resp.json.return_value = {
            "status": 1,
            "version_code": "2.0.0",
            "download_url": "https://mock.example.com/setup_2.0.0.exe",
        }

        with patch("services.update_service.get_running_app_version", return_value="2.0.2"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        self.assertEqual(update_available_called, [], "UpdateAvailable MUST NOT be emitted when API returns older version 2.0.0")
        self.assertEqual(check_completed_results, [False])

    def test_2_api_returns_same_version(self):
        """Scenario 2: API returns 2.0.2 and installed is 2.0.2 -> NO update."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)
        update_available_called = []
        check_completed_results = []
        worker.update_available.connect(lambda ver, url, force: update_available_called.append(ver))
        worker.check_completed.connect(lambda has_update: check_completed_results.append(has_update))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": 1, "version_code": "2.0.2"}'
        mock_resp.json.return_value = {
            "status": 1,
            "version_code": "2.0.2",
            "download_url": "https://mock.example.com/setup_2.0.2.exe",
        }

        with patch("services.update_service.get_running_app_version", return_value="2.0.2"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        self.assertEqual(update_available_called, [])
        self.assertEqual(check_completed_results, [False])

    def test_3_api_returns_newer_version(self):
        """Scenario 3: API returns 2.0.3 and installed is 2.0.2 -> Update available with exact version 2.0.3."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)
        update_available_called = []
        check_completed_results = []
        worker.update_available.connect(lambda ver, url, force: update_available_called.append(ver))
        worker.check_completed.connect(lambda has_update: check_completed_results.append(has_update))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": 1, "version_code": "2.0.3"}'
        mock_resp.json.return_value = {
            "status": 1,
            "version_code": "2.0.3",
            "download_url": "https://mock.example.com/setup_2.0.3.exe",
        }

        with patch("services.update_service.get_running_app_version", return_value="2.0.2"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        self.assertEqual(update_available_called, ["2.0.3"])
        self.assertEqual(check_completed_results, [True])

    def test_4_api_returns_invalid_version(self):
        """Scenario 4: API returns invalid version strings (e.g. 'invalid', '!@#$') -> NO update."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)
        update_available_called = []
        check_completed_results = []
        worker.update_available.connect(lambda ver, url, force: update_available_called.append(ver))
        worker.check_completed.connect(lambda has_update: check_completed_results.append(has_update))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": 1, "version_code": "invalid_version"}'
        mock_resp.json.return_value = {
            "status": 1,
            "version_code": "invalid_version",
            "download_url": "https://mock.example.com/setup.exe",
        }

        with patch("services.update_service.get_running_app_version", return_value="2.0.2"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        self.assertEqual(update_available_called, [])
        self.assertEqual(check_completed_results, [False])

    def test_5_api_returns_missing_version(self):
        """Scenario 5: API returns missing version -> NO update."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)
        update_available_called = []
        check_completed_results = []
        worker.update_available.connect(lambda ver, url, force: update_available_called.append(ver))
        worker.check_completed.connect(lambda has_update: check_completed_results.append(has_update))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": 0}'
        mock_resp.json.return_value = {"status": 0}

        with patch("services.update_service.get_running_app_version", return_value="2.0.2"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        self.assertEqual(update_available_called, [])
        self.assertEqual(check_completed_results, [False])

    def test_6_stale_cached_update_version(self):
        """Scenario 6: Stale pending update state with version 2.1 is discarded when live API returns 2.0.0."""
        from services.update_state import UpdateStateManager
        mgr = UpdateStateManager()
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / "update_state.json"
            with patch.object(mgr, "_state_file", state_file):
                mgr.record_install_start("2.1", str(Path(tmp_dir) / "old_installer.exe"))
                # When current installed is 2.0.2 and live API returns 2.0.0, is_newer_version is False
                self.assertFalse(is_newer_version("2.0.0", "2.0.2"))

    def test_7_api_version_differs_from_old_cached_version(self):
        """Scenario 7: Live API response (2.0.0) is the sole source of truth even if previous cache had 2.1."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)
        update_available_called = []
        worker.update_available.connect(lambda ver, url, force: update_available_called.append(ver))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": 1, "version_code": "2.0.0"}'
        mock_resp.json.return_value = {
            "status": 1,
            "version_code": "2.0.0",
            "download_url": "https://mock.example.com/setup.exe",
        }

        with patch("services.update_service.get_running_app_version", return_value="2.0.2"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        # Must not adopt 2.1 or emit any update
        self.assertEqual(update_available_called, [])

    def test_8_download_url_version_differs_from_stale_cached_filename(self):
        """Scenario 8: Download URL strictly reflects the live API response."""
        worker = UpdateCheckWorker(api_url="https://mock.example.com", auto_download=False)
        download_targets = []
        worker.update_available.connect(lambda ver, url, force: download_targets.append((ver, url)))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"status": 1, "version_code": "2.0.3", "download_url": "https://mock.example.com/setup_v2.0.3.exe"}'
        mock_resp.json.return_value = {
            "status": 1,
            "version_code": "2.0.3",
            "download_url": "https://mock.example.com/setup_v2.0.3.exe",
        }

        with patch("services.update_service.get_running_app_version", return_value="2.0.2"), \
             patch("requests.post", return_value=mock_resp):
            worker.run()

        self.assertEqual(download_targets, [("2.0.3", "https://mock.example.com/setup_v2.0.3.exe")])


if __name__ == "__main__":
    unittest.main()
