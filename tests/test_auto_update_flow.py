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
    def setUp(self):
        ApiConfig().reset()
        try:
            from services.update_state import UpdateStateManager
            UpdateStateManager().clear_state()
        except Exception:
            pass

    def tearDown(self):
        ApiConfig().reset()
        try:
            from services.update_state import UpdateStateManager
            UpdateStateManager().clear_state()
        except Exception:
            pass

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
        mock_v_resp.text = '{"status": 1, "version_code": "9.9.9", "download_url": "https://test.api/setup.exe"}'
        mock_v_resp.json.return_value = {
            "status": 1,
            "version_code": "9.9.9",
            "download_url": "https://test.api/setup.exe",
        }

        with patch("requests.post", return_value=mock_v_resp), \
             patch("requests.get", return_value=mock_v_resp), \
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

    def test_pipeline_continues_when_upload_encounters_backend_error(self):
        """Pipeline does not depend forever on pre-flush; pending data remains in DB and update proceeds."""
        from unittest.mock import patch, MagicMock
        from services.update_service import UpdatePipelineWorker

        worker = UpdatePipelineWorker(api_url="https://test.api")
        upload_completed_events = []
        worker.upload_completed.connect(lambda: upload_completed_events.append(True))

        mock_v_resp = MagicMock()
        mock_v_resp.status_code = 200
        mock_v_resp.text = '{"status": 1, "version_code": "9.9.9", "download_url": "https://test.api/setup.exe"}'
        mock_v_resp.json.return_value = {
            "status": 1,
            "version_code": "9.9.9",
            "download_url": "https://test.api/setup.exe",
        }

        mock_session = MagicMock()
        with patch("requests.post", return_value=mock_v_resp), \
             patch("requests.get", return_value=mock_v_resp), \
             patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", return_value=[mock_session]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]), \
             patch("services.sync_service.SyncService.sync_activity_now", return_value=False), \
             patch("services.update_service.install_update_and_restart") as mock_install:

            worker.run()

            # Verify upload_completed was emitted so pipeline progresses to download/install
            self.assertTrue(len(upload_completed_events) > 0)

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

    def test_resolve_download_candidates_filters_html_link(self):
        """Verify non-exe activity_tracker_link is not treated as download URL."""
        from services.update_service import resolve_download_candidates
        candidates = resolve_download_candidates(
            api_url="https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/",
            file_name="ihrms-monitor-v2.exe",
            download_url="",
            activity_tracker_link="https://indovisionservices.in/info/dev/v15/acitivity-tracker",
        )
        self.assertIn("https://softdev.indovisionservices.in/ihrms84/uploads/ihrms-monitor-v2.exe", candidates)
        self.assertNotIn("https://indovisionservices.in/info/dev/v15/acitivity-tracker", candidates)

    def test_flush_pending_data_preserves_tracking_by_default(self):
        """Pre-update flush does not stop active tracking unless stop_tracker=True."""
        from unittest.mock import patch, MagicMock
        from services.update_service import flush_pending_data_before_update

        mock_widget = MagicMock()
        mock_widget.stop_tracking = MagicMock()
        mock_widget._tracker = MagicMock()
        mock_widget._tracker.is_tracking = True

        mock_app = MagicMock()
        mock_app.topLevelWidgets.return_value = [mock_widget]

        with patch("PySide6.QtWidgets.QApplication.instance", return_value=mock_app), \
             patch("database.repository.ActivityRepository.get_unsynced_closed_sessions", return_value=[]), \
             patch("database.repository.ActivityRepository.get_sessions_with_unuploaded_screenshots", return_value=[]):
            
            # Default call: stop_tracker=False
            res = flush_pending_data_before_update(stop_tracker=False)
            self.assertTrue(res)
            mock_widget.stop_tracking.assert_not_called()

            # Final restart call: stop_tracker=True
            res2 = flush_pending_data_before_update(stop_tracker=True)
            self.assertTrue(res2)
            mock_widget.stop_tracking.assert_called_once()


    def test_scenario_1_system_starts_with_internet_auto_updates(self):
        """Scenario 1: System starts with internet -> update automatically in background without button clicks."""
        from unittest.mock import patch, MagicMock
        from services.update_service import UpdatePipelineWorker
        import tempfile
        from pathlib import Path

        worker = UpdatePipelineWorker(api_url="https://test.api")
        phases = []
        worker.phase_changed.connect(lambda p, d: phases.append(p))

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with patch("requests.get") as mock_get, \
                 patch("requests.post") as mock_post, \
                 patch("services.update_service.get_updates_directory", return_value=tmp_path), \
                 patch("services.update_service.flush_pending_data_before_update", return_value=True), \
                 patch("services.update_service.install_update_and_restart", return_value=True) as mock_restart:

                # Mock server returning newer version 3.0.0
                mock_v_resp = MagicMock()
                mock_v_resp.status_code = 200
                mock_v_resp.text = '{"status": 1, "version_code": "3.0.0", "file_name": "Setup.exe", "download_url": "https://test.api/Setup.exe"}'
                mock_v_resp.json.return_value = {"status": 1, "version_code": "3.0.0", "file_name": "Setup.exe", "download_url": "https://test.api/Setup.exe"}
                mock_post.return_value = mock_v_resp
                mock_get.return_value = mock_v_resp

                # Mock valid download stream (>100KB with MZ header)
                mock_dl_resp = MagicMock()
                mock_dl_resp.status_code = 200
                mock_dl_resp.headers = {"content-type": "application/octet-stream", "content-length": "204800"}
                mock_dl_resp.iter_content.return_value = [b"MZ" + b"x" * 102400, b"y" * 102400]
                mock_dl_resp.__enter__.return_value = mock_dl_resp
                mock_dl_resp.__exit__.return_value = None

                def get_mock(url, **kwargs):
                    if "Setup.exe" in str(url):
                        return mock_dl_resp
                    return mock_v_resp

                mock_get.side_effect = get_mock

                worker.run()

                # Verify complete automated progression: checking -> uploading_pending -> downloading -> installing
                self.assertIn("checking", phases)
                self.assertIn("downloading", phases)
                self.assertIn("installing", phases)
                mock_restart.assert_called_once()

    def test_scenario_2_system_starts_offline_auto_updates_when_reconnected(self):
        """Scenario 2: System starts without internet -> update automatically after internet reconnects."""
        from unittest.mock import patch, MagicMock, PropertyMock
        from PySide6.QtWidgets import QApplication
        import sys
        app = QApplication.instance() or QApplication(sys.argv)
        from ui.main_window import MainWindow

        with patch("config.api_config.ApiConfig.base_url", new_callable=PropertyMock, return_value="https://test.api"), \
             patch("ui.main_window.MainWindow._build_tracker"), \
             patch("ui.main_window.MainWindow._build_tray"), \
             patch("ui.main_window.MainWindow._apply_rbac_permissions"), \
             patch("ui.main_window.MainWindow.start_tracking"), \
             patch("services.device_registry_service.DeviceRegistryService.record_heartbeat"), \
             patch("services.device_registry_service.DeviceRegistryService.get_all_devices", return_value=[{"device_identifier": "test", "update_status": "Update Pending"}]):

            window = MainWindow()

            # 1. Startup offline check fails
            with patch("services.update_service.UpdateService.start_pipeline") as mock_pipeline:
                # Trigger update check which fails with network connection error
                window._check_for_updates(manual=False)
                # Extract on_error handler
                on_error_cb = mock_pipeline.call_args.kwargs.get("on_error")
                self.assertIsNotNone(on_error_cb)
                on_error_cb("checking", "Connection refused / Host unreachable (offline)")

                # Verify offline state detected and fast retry timer activated
                self.assertTrue(window._offline_update_pending)
                self.assertEqual(window.dashboard_page.update_status_label.text(), "Status: Update Pending (Offline)")
                self.assertTrue(window._offline_update_retry_timer.isActive())

            # 2. Internet reconnects: SyncService.last_sync_status becomes "Sent"
            with patch("services.sync_service.SyncService.last_sync_status", "Sent"), \
                 patch.object(window, "_check_for_updates") as mock_recheck:
                mock_state = MagicMock()
                mock_state.is_idle = False
                mock_state.is_tracking = True
                mock_state.current_application = "iHRMS Monitor.exe"
                mock_state.current_window_title = "Dashboard"
                mock_state.idle_seconds = 0
                window._on_tracker_state_changed(mock_state)

                # Verify pending update check is automatically initiated upon reconnection
                mock_recheck.assert_called_once_with(manual=False)
                self.assertFalse(window._offline_update_pending)

    def test_scenario_3_no_update_available_status_updated(self):
        """Scenario 3: No update available -> sets status Updated, no update action taken."""
        from unittest.mock import patch, MagicMock
        from services.update_service import UpdatePipelineWorker

        worker = UpdatePipelineWorker(api_url="https://test.api")
        phases = []
        worker.phase_changed.connect(lambda p, d: phases.append(p))

        with patch("requests.get") as mock_get, \
             patch("services.update_service.get_running_app_version", return_value="1.0.0"), \
             patch("services.update_service.install_update_and_restart") as mock_restart:

            # Server returns same version 1.0.0
            mock_v_resp = MagicMock()
            mock_v_resp.status_code = 200
            mock_v_resp.text = '{"version": "1.0.0"}'
            mock_v_resp.json.return_value = {"version": "1.0.0"}
            mock_get.return_value = mock_v_resp

            worker.run()

            # Verify finished cleanly as 'done' without downloading or restarting
            self.assertIn("done", phases)
            self.assertNotIn("downloading", phases)
            self.assertNotIn("installing", phases)
            mock_restart.assert_not_called()

    def test_scenario_4_update_completes_clean_restart_no_freeze(self):
        """Scenario 4: Update completes -> application restarts cleanly without Not Responding hang."""
        from unittest.mock import patch, MagicMock
        from services.update_service import install_update_and_restart
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_installer = tmp_path / "valid_setup.exe"
            with open(fake_installer, "wb") as f:
                f.write(b"MZ" + b"0" * (1024 * 105))

            with patch("services.update_service.get_updates_directory", return_value=tmp_path), \
                 patch("subprocess.Popen") as mock_popen, \
                 patch("PySide6.QtWidgets.QApplication.instance") as mock_app:

                from PySide6.QtCore import QThread
                mock_widget = MagicMock()
                mock_widget._really_quit = False
                mock_app.return_value.thread.return_value = QThread.currentThread()
                mock_app.return_value.topLevelWidgets.return_value = [mock_widget]

                success = install_update_and_restart(str(fake_installer), exit_process=False)
                self.assertTrue(success)
                self.assertTrue(mock_widget._really_quit)
                self.assertTrue(mock_widget.close.called or mock_widget.hide.called)
                mock_popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()

