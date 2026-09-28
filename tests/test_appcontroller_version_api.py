"""Unit tests verifying App Controller Version API integration and auto-update scenarios.

Covers:
Case 1: API version == current version -> No update
Case 2: API version > current version -> Update detected
Case 3: API version < current version -> No downgrade
Case 4: API unavailable -> Application continues normally and logs error
Case 5: Invalid/missing version in response -> No unsafe update; log error
Case 6: Windows platform selection -> Windows API version & download URL used
Case 7: macOS platform selection -> macOS API version & download URL used
"""

import unittest
from unittest.mock import patch, MagicMock

from config.api_config import ApiConfig, APP_CONTROLLER_URL
from config.settings import get_running_app_version
from services.update_service import (
    fetch_app_controller_update_info,
    is_newer_version,
    UpdateCheckWorker,
    UpdatePipelineWorker,
)


class TestAppControllerVersionApi(unittest.TestCase):

    def setUp(self):
        ApiConfig().reset()

    def tearDown(self):
        ApiConfig().reset()

    def test_case_1_api_version_equals_current_version(self):
        """Case 1: When API version == current version (1.0 vs 1), no update is triggered."""
        current = get_running_app_version()  # "1.0"
        server_ver = "1"
        self.assertFalse(is_newer_version(server_ver, current))

        # Test with string equal
        self.assertFalse(is_newer_version("1.0", current))
        self.assertFalse(is_newer_version("v1.0", current))

    def test_case_2_api_version_greater_than_current_version(self):
        """Case 2: When API version > current version (e.g. 1.1 or 2), update is detected."""
        current = get_running_app_version()  # "1.0"
        self.assertTrue(is_newer_version("1.1", current))
        self.assertTrue(is_newer_version("2", current))
        self.assertTrue(is_newer_version("2.0.0", current))
        self.assertTrue(is_newer_version("v1.0.1", current))

    def test_case_3_api_version_less_than_current_version(self):
        """Case 3: When API version < current version, no downgrade occurs."""
        current = "1.1"
        self.assertFalse(is_newer_version("1.0", current))
        self.assertFalse(is_newer_version("1", current))
        self.assertFalse(is_newer_version("0.9", current))

    def test_case_4_api_unavailable(self):
        """Case 4: When App Controller API is unreachable, logs error and returns safe fallback."""
        with patch("requests.post", side_effect=Exception("Connection refused")):
            ver, fn, dl, force = fetch_app_controller_update_info(company_code="INVALID_CC")
            self.assertEqual(ver, "")
            self.assertEqual(fn, "")
            self.assertEqual(dl, "")
            self.assertFalse(force)

    def test_case_5_invalid_or_missing_version_in_response(self):
        """Case 5: When API returns invalid or missing version, no unsafe update is triggered."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "status": 200,
            "data": {
                "apps": {
                    "WINDOWS": {"version_code": "NA", "file_name": "", "force_to_update": "0"}
                }
            }
        }
        with patch("requests.post", return_value=mock_resp):
            ver, fn, dl, force = fetch_app_controller_update_info(company_code="TEST_CODE", platform_name="WINDOWS")
            self.assertFalse(is_newer_version(ver, get_running_app_version()))

    def test_case_6_windows_platform_selection(self):
        """Case 6: On Windows, Windows version_code, file_name, and force_to_update are used."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "status": 200,
            "data": {
                "apps": {
                    "WINDOWS": {
                        "version_code": "2.0",
                        "file_name": "https://indovisionservices.in/workpulse/Workpulse-Installer.exe",
                        "force_to_update": "1"
                    },
                    "MAC": {
                        "version_code": "3.0",
                        "file_name": "https://indovisionservices.in/workpulse/Workpulse.dmg",
                        "force_to_update": "0"
                    }
                }
            }
        }
        with patch("requests.post", return_value=mock_resp):
            ver, fn, dl, force = fetch_app_controller_update_info(company_code="TEST_CODE", platform_name="WINDOWS")
            self.assertEqual(ver, "2.0")
            self.assertEqual(fn, "https://indovisionservices.in/workpulse/Workpulse-Installer.exe")
            self.assertEqual(dl, "https://indovisionservices.in/workpulse/Workpulse-Installer.exe")
            self.assertTrue(force)
            self.assertTrue(is_newer_version(ver, get_running_app_version()))

    def test_case_7_macos_platform_selection(self):
        """Case 7: On macOS, MAC version_code, file_name, and force_to_update are used."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "status": 200,
            "data": {
                "apps": {
                    "WINDOWS": {
                        "version_code": "2.0",
                        "file_name": "https://indovisionservices.in/workpulse/Workpulse-Installer.exe",
                        "force_to_update": "1"
                    },
                    "MAC": {
                        "version_code": "3.0",
                        "file_name": "https://indovisionservices.in/workpulse/Workpulse.dmg",
                        "force_to_update": "0"
                    }
                }
            }
        }
        with patch("requests.post", return_value=mock_resp):
            ver, fn, dl, force = fetch_app_controller_update_info(company_code="TEST_CODE", platform_name="MAC")
            self.assertEqual(ver, "3.0")
            self.assertEqual(fn, "https://indovisionservices.in/workpulse/Workpulse.dmg")
            self.assertEqual(dl, "https://indovisionservices.in/workpulse/Workpulse.dmg")
            self.assertFalse(force)
            self.assertTrue(is_newer_version(ver, get_running_app_version()))


if __name__ == "__main__":
    unittest.main()
