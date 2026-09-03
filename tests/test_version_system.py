"""Unit tests for authoritative application versioning, dynamic dashboard display, and cache-busting update checks."""

import unittest
from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QApplication

from config.settings import APP_VERSION, get_running_app_version
from services.update_service import (
    parse_version,
    is_newer_version,
    UpdateCheckWorker,
    UpdatePipelineWorker,
    CACHE_BUST_HEADERS,
    DEFAULT_CENTRAL_VERSION_URL,
)
from scripts.generate_version_info import parse_version_tuple, generate_version_info


class TestVersionSystem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_get_running_app_version(self):
        """Verify get_running_app_version returns the configured APP_VERSION when not frozen."""
        v = get_running_app_version()
        self.assertEqual(v, APP_VERSION)
        self.assertIsInstance(v, str)
        self.assertTrue(len(v) > 0)

    def test_dashboard_version_label_dynamic(self):
        """Verify DashboardPage initializes with get_running_app_version and set_version updates label."""
        from ui.dashboard import DashboardPage
        mock_svc = MagicMock()
        mock_svc.get_idle_seconds.return_value = 0
        mock_svc.get_today_timeline.return_value = []
        mock_svc.get_today_total_duration.return_value = 0

        dashboard = DashboardPage(mock_svc)
        self.assertEqual(dashboard.version_label.text(), f"Version: {get_running_app_version()}")

        # Dynamically update version
        dashboard.set_version("1.0.5")
        self.assertEqual(dashboard.version_label.text(), "Version: 1.0.5")

        dashboard.set_version("Version: 2.1.0")
        self.assertEqual(dashboard.version_label.text(), "Version: 2.1.0")

    def test_version_comparisons(self):
        """Verify version comparison semantics."""
        self.assertTrue(is_newer_version("1.0.1", "1.0.0"))
        self.assertTrue(is_newer_version("1.1.0", "1.0.0"))
        self.assertTrue(is_newer_version("2.0.0", "1.9.9"))
        self.assertTrue(is_newer_version("v1.0.5", "1.0.4"))

        # Same or older versions should NOT trigger update
        self.assertFalse(is_newer_version("1.0.0", "1.0.0"))
        self.assertFalse(is_newer_version("0.9.9", "1.0.0"))
        self.assertFalse(is_newer_version("1.0", "1.0.0"))
        self.assertFalse(is_newer_version("", "1.0.0"))
        self.assertFalse(is_newer_version("NA", "1.0.0"))

    def test_cache_busting_headers_in_update_check(self):
        """Verify UpdateCheckWorker uses cache-busting headers and query parameters."""
        worker = UpdateCheckWorker(
            api_url="https://mock.api/ihrms",
            indo_code="TEST_USER",
            api_key="TEST_KEY",
            auto_download=False,
        )

        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "version": "1.0.1",
                "download_url": "https://mock.api/setup.exe",
            }
            mock_get.return_value = mock_resp

            with patch("config.api_config.ApiConfig") as mock_cfg_cls:
                mock_cfg = MagicMock()
                mock_cfg.version_url = "https://indovisionservices.in/info/dev/v15/acitivity-tracker"
                mock_cfg.activity_tracker_version = None
                mock_cfg.activity_tracker_link = None
                mock_cfg_cls.return_value = mock_cfg

                # Run worker check
                worker.run()

                # Verify requests.get called with cache busting
                mock_get.assert_called_once()
                call_args, call_kwargs = mock_get.call_args
                url_called = call_args[0]
                self.assertIn("_t=", url_called)
                self.assertEqual(call_kwargs.get("headers"), CACHE_BUST_HEADERS)

    def test_central_version_url_fallback(self):
        """Verify that when no custom company version URL is set, worker falls back to central update URL."""
        worker = UpdateCheckWorker(
            api_url="https://mock.api/ihrms",
            auto_download=False,
        )

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"version": "1.0.0"}
            mock_get.return_value = mock_resp

            with patch("config.api_config.ApiConfig") as mock_cfg_cls:
                mock_cfg = MagicMock()
                mock_cfg.version_url = None
                mock_cfg.activity_tracker_link = None
                mock_cfg.activity_tracker_version = None
                mock_cfg_cls.return_value = mock_cfg

                worker.run()

                mock_get.assert_called_once()
                url_called = mock_get.call_args[0][0]
                self.assertTrue(url_called.startswith(DEFAULT_CENTRAL_VERSION_URL))

    def test_generate_version_info_parser(self):
        """Verify version parser converts strings to 4-tuples for Windows PE resources."""
        self.assertEqual(parse_version_tuple("1.0.0"), (1, 0, 0, 0))
        self.assertEqual(parse_version_tuple("1.2.3.4"), (1, 2, 3, 4))
        self.assertEqual(parse_version_tuple("v2.1"), (2, 1, 0, 0))
        self.assertEqual(parse_version_tuple("3.0.15"), (3, 0, 15, 0))

    def test_login_window_version_label_removed_below_login_section(self):
        """Verify that the version text below the Login section has been removed."""
        from ui.login_window import LoginWindow
        login_window = LoginWindow()
        # Assert version_label is not present below login form
        self.assertFalse(hasattr(login_window, "version_label"))
        # Update status label is still present for download/install feedback
        self.assertTrue(hasattr(login_window, "update_status_label"))

    def test_version_check_prioritizes_punch_api_over_stale_appcontroller_tracker_version(self):
        """
        Verify that when AppController returns stale activity_tracker_version ('1.00'),
        the pipeline/worker correctly queries punch/check_new_version and adopts the latest released version (e.g. '1.0.2').
        """
        from pathlib import Path
        import tempfile

        worker = UpdatePipelineWorker(
            api_url="https://mock.api/hrms_api/ci4/api",
            indo_code="EMP_TEST",
            api_key="KEY_TEST",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_inst = tmp_path / "iHRMSMonitorSetup_v1.0.2.exe"
            with open(fake_inst, "wb") as f:
                f.write(b"x" * (1024 * 200))

            with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
                # 1. External version URL returns empty body (as observed in production)
                mock_url_resp = MagicMock()
                mock_url_resp.status_code = 200
                mock_url_resp.text = ""
                mock_get.return_value = mock_url_resp

                # 2. Company endpoint (/punch/check_new_version) returns released version 1.0.2
                mock_punch_resp = MagicMock()
                mock_punch_resp.status_code = 200
                mock_punch_resp.text = '{"status": 1, "version_code": "1.0.2", "file_name": "iHRMSMonitorSetup_v1.0.2.exe"}'
                mock_punch_resp.json.return_value = {
                    "status": 1,
                    "version_code": "1.0.2",
                    "file_name": "iHRMSMonitorSetup_v1.0.2.exe",
                    "download_url": "https://mock.api/setup_1.0.2.exe",
                    "force_update": 0,
                }
                mock_post.return_value = mock_punch_resp

                with patch("config.api_config.ApiConfig") as mock_cfg_cls:
                    mock_cfg = MagicMock()
                    mock_cfg.version_url = "https://indovisionservices.in/info/dev/v15/acitivity-tracker"
                    mock_cfg.activity_tracker_link = "https://indovisionservices.in/info/dev/v15/acitivity-tracker"
                    # Stale version in AppController
                    mock_cfg.activity_tracker_version = "1.00"
                    mock_cfg_cls.return_value = mock_cfg

                    with patch("services.update_service.get_running_app_version", return_value="1.0.0"), \
                         patch("services.update_service.get_updates_directory", return_value=tmp_path), \
                         patch("services.update_service.flush_pending_data_before_update", return_value=True), \
                         patch("services.update_service.install_update_and_restart", return_value=True):

                        available_versions = []
                        worker.update_available.connect(lambda v, u, f: available_versions.append(v))

                        worker.run()

                        # Must have called punch/check_new_version and adopted 1.0.2 (NOT blocked by 1.00)
                        mock_post.assert_called_once()
                        self.assertIn("1.0.2", available_versions)

    def test_silent_update_bat_script_generation(self):
        """Verify silent_update.bat generation includes process termination, unattended flags, and target executable restart."""
        from services.update_service import install_update_and_restart
        from pathlib import Path
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_installer = tmp_path / "fake_setup.exe"
            with open(fake_installer, "wb") as f:
                f.write(b"x" * (1024 * 101))  # > 100KB

            with patch("services.update_service.get_updates_directory", return_value=tmp_path), \
                 patch("subprocess.Popen") as mock_popen, \
                 patch("PySide6.QtWidgets.QApplication.instance") as mock_app:
                mock_app.return_value = MagicMock()

                success = install_update_and_restart(str(fake_installer))
                self.assertTrue(success)

                bat_file = tmp_path / "silent_update.bat"
                self.assertTrue(bat_file.exists())
                with open(bat_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Verify critical reliability elements
                self.assertIn('taskkill /F /IM "iHRMS Monitor.exe"', content)
                self.assertIn("/VERYSILENT", content)
                self.assertIn("/SUPPRESSMSGBOXES", content)
                self.assertIn("/FORCECLOSEAPPLICATIONS", content)
                self.assertIn("/SP-", content)
                self.assertIn("iHRMS Monitor.exe", content)
                self.assertIn("/VERYSILENT", content)
                self.assertIn("/SUPPRESSMSGBOXES", content)
                self.assertIn("/FORCECLOSEAPPLICATIONS", content)
                self.assertIn("/SP-", content)
                self.assertIn("iHRMS Monitor.exe", content)


if __name__ == "__main__":
    unittest.main()

