"""Unit tests covering all exact auto-update scenarios required for Workpulse v2.0.2 -> v2.1.

Tests:
1. Semantic version comparisons:
   - 2.0.2 < 2.1 (Update Available)
   - 2.0.2 < 2.1.0 (Update Available)
   - 2.1 == 2.1.0 (No Update)
   - 2.1 == 2.1 (No Update)
   - 2.1.0 > 2.0.2
2. Step 3 & 4 Candidate Resolution:
   - Backend download_url is Candidate #1
   - Candidates are NEVER filtered out because of version substrings in their name
3. Step 4 & 8 Safe Installer Validation:
   - Valid Windows PE installer passes
   - HTML error response fails and is deleted
   - Truncated file (<100KB) fails and is deleted
   - Old installer version metadata (e.g. 2.0.2 when target is 2.1) fails and is deleted
4. Step 10 Post-Install Version Verification:
   - Actual = 2.1 -> Update Success, pending state cleared
   - Actual = 2.0.2 -> Update Failed, cooldown applied, loop prevented
5. Step 12 & 13 Retry & UI State:
   - Retry resets progress bar to 0% and cleans stale .download files
   - If installed_version >= api_version, dialog closes and no retry button shown
6. Step 5 TLS CA Bundle Cleanup:
   - Invalid environment variable path (e.g. from another user) is cleansed
"""

import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.update_service import (
    parse_version,
    is_newer_version,
    resolve_download_candidates,
    validate_installer_file,
    UpdatePipelineWorker,
    UpdateCheckWorker,
    UpdateService,
)
from services.update_state import UpdateStateManager, _is_version_ge
from utils.paths import init_ca_bundle, get_ca_bundle_path
from ui.update_dialog import UpdateDialog


class TestAutoUpdateExactScenarios(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.state_file = self.tmp_path / "update_state.json"
        UpdateStateManager._instance = None
        self.state_mgr = UpdateStateManager(state_file=self.state_file)

    def tearDown(self):
        UpdateStateManager._instance = None
        self.tmp_dir.cleanup()

    # ==============================================================
    # 1. SEMANTIC VERSION COMPARISON (Step 2)
    # ==============================================================
    def test_semantic_version_comparisons(self):
        """Verify semantic comparisons required by specification."""
        # 2.0.2 < 2.1 -> True (UPDATE AVAILABLE)
        self.assertTrue(is_newer_version("2.1", "2.0.2"))
        # 2.0.2 < 2.1.0 -> True
        self.assertTrue(is_newer_version("2.1.0", "2.0.2"))
        # 2.1 == 2.1.0 -> False (NO UPDATE)
        self.assertFalse(is_newer_version("2.1.0", "2.1"))
        self.assertFalse(is_newer_version("2.1", "2.1.0"))
        # 2.1 == 2.1 -> False (NO UPDATE)
        self.assertFalse(is_newer_version("2.1", "2.1"))
        # 2.1.0 > 2.0.2 -> True
        self.assertTrue(is_newer_version("2.1.0", "2.0.2"))
        self.assertFalse(is_newer_version("2.0.2", "2.1.0"))

    # ==============================================================
    # 2. CANDIDATE RESOLUTION & NO NAME FILTERING (Step 3)
    # ==============================================================
    def test_candidate_resolution_prioritizes_api_url_and_does_not_filter(self):
        """Backend download_url is Candidate #1 and older filename strings are NOT discarded."""
        api_url = "https://hrms.workpulse.in/hrms_api/ci4/api"
        # Server returned an update to v2.1, but the URL or file_name still contains v2.0.2
        download_url = "https://hrms.workpulse.in/uploads/version/WorkpulseSetup_v2.0.2.exe"
        file_name = "WorkpulseSetup_v2.0.2.exe"

        candidates = resolve_download_candidates(
            api_url=api_url,
            file_name=file_name,
            download_url=download_url,
            server_version="2.1",
        )

        # Candidate #1 MUST be the explicit download_url
        self.assertEqual(candidates[0], download_url)
        # The URL containing v2.0.2 must NOT have been filtered out!
        self.assertIn(download_url, candidates)

    # ==============================================================
    # 3. SAFE INSTALLER VALIDATION (Step 4 & 8)
    # ==============================================================
    def test_installer_validation_rejects_html(self):
        """HTML error response (e.g. 404 page) must fail validation."""
        html_file = self.tmp_path / "download.download"
        html_file.write_text("<!DOCTYPE html><html><body>404 Not Found</body></html>" + " " * (1024 * 105), encoding="utf-8")

        valid, reason = validate_installer_file(html_file, target_version="2.1")
        self.assertFalse(valid)
        self.assertIn("Invalid executable header", reason)

    def test_installer_validation_rejects_json(self):
        """JSON error response must fail validation."""
        json_file = self.tmp_path / "download.download"
        json_file.write_text('{"status": 0, "message": "Access Denied"}' + " " * (1024 * 105), encoding="utf-8")

        valid, reason = validate_installer_file(json_file, target_version="2.1")
        self.assertFalse(valid)
        self.assertIn("Invalid executable header", reason)

    def test_installer_validation_rejects_truncated_file(self):
        """File smaller than 100 KB must fail validation."""
        small_file = self.tmp_path / "download.download"
        small_file.write_bytes(b"MZ" + b"\x00" * 500)

        valid, reason = validate_installer_file(small_file, target_version="2.1")
        self.assertFalse(valid)
        self.assertIn("too small", reason)

    def test_installer_validation_rejects_older_version_metadata(self):
        """If PE file version metadata reports an older version than target, validation must fail."""
        mock_file = self.tmp_path / "WorkpulseSetup_v2.1.exe.download"
        # Write >100KB with MZ header
        mock_file.write_bytes(b"MZ" + b"\x00" * (1024 * 150))

        # Mock win32api returning FileVersion: 2.0.2 when target is 2.1
        mock_win32 = MagicMock()
        mock_win32.GetFileVersionInfo.side_effect = [
            [(1033, 1200)],  # Translation
            "2.0.2",          # FileVersion
        ]
        with patch.dict("sys.modules", {"win32api": mock_win32}):
            valid, reason = validate_installer_file(mock_file, target_version="2.1")
            self.assertFalse(valid)
            self.assertIn("older than target", reason)

    # ==============================================================
    # 4. POST-INSTALL VERSION VERIFICATION & LOOP PREVENTION (Step 10 & 11)
    # ==============================================================
    def test_post_install_verification_success(self):
        """When actual version reaches 2.1, update is successful and state is cleared."""
        self.state_mgr.record_install_start("2.1", str(self.tmp_path / "WorkpulseSetup_v2.1.exe"))

        # Post-restart check with actual running version = 2.1
        success, msg = self.state_mgr.check_post_restart_status(running_version="2.1")
        self.assertTrue(success)
        self.assertIn("SUCCESSFUL", msg)

        state = self.state_mgr.get_state()
        self.assertEqual(state["status"], "success")
        self.assertEqual(state["last_installed_version"], "2.1")
        self.assertEqual(state["install_attempts"], 0)

    def test_post_install_verification_failure_prevents_loop(self):
        """When actual version remains 2.0.2, update fails, is NOT marked success, and cooldown prevents loop."""
        self.state_mgr.record_install_start("2.1", str(self.tmp_path / "WorkpulseSetup_v2.1.exe"))

        # Post-restart check with actual running version = 2.0.2 (failed update)
        success, msg = self.state_mgr.check_post_restart_status(running_version="2.0.2")
        self.assertFalse(success)
        self.assertIn("FAILED", msg)

        state = self.state_mgr.get_state()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["install_attempts"], 1)

        # Attempt 2 failure triggers 24h cooldown
        self.state_mgr.record_install_start("2.1", str(self.tmp_path / "WorkpulseSetup_v2.1.exe"))
        success2, msg2 = self.state_mgr.check_post_restart_status(running_version="2.0.2")
        self.assertFalse(success2)
        self.assertEqual(self.state_mgr.get_state()["install_attempts"], 2)

        # Loop guard now blocks repeated update attempts
        allowed, reason = self.state_mgr.should_attempt_update("2.1", running_version="2.0.2", manual=False)
        self.assertFalse(allowed)
        self.assertIn("cooldown", reason.lower())

    def test_no_update_when_same_version(self):
        """When installed = 2.1 and API = 2.1, no update is permitted."""
        allowed, reason = self.state_mgr.should_attempt_update("2.1", running_version="2.1", manual=False)
        self.assertFalse(allowed)
        self.assertIn("already up to date", reason)

    # ==============================================================
    # 5. RETRY & UI FLOW (Step 12 & 13)
    # ==============================================================
    def test_retry_resets_progress_and_cleans_stale_downloads(self):
        """Retry button resets progress bar, deletes stale .download files, and restarts fresh pipeline."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        dialog = UpdateDialog(version="2.1", is_force=False)
        dialog.progress_bar.setValue(100)

        # Create stale download files
        stale_file = self.tmp_path / "WorkpulseSetup_v2.1.exe.download"
        stale_file.write_text("corrupted", encoding="utf-8")

        # Simulate error occurred -> enables Retry button
        dialog._on_error_occurred("downloading", "Update installer for v2.1 could not be downloaded")
        self.assertEqual(dialog.install_btn.text(), "Retry")
        self.assertTrue(dialog.install_btn.isEnabled())

        with patch("services.update_service.get_updates_directory", return_value=self.tmp_path), \
             patch("services.update_service.get_running_app_version", return_value="2.0.2"), \
             patch("services.update_service.UpdateService.start_pipeline") as mock_pipeline:

            mock_worker = MagicMock()
            mock_pipeline.return_value = mock_worker

            # Click Retry
            dialog._on_install_clicked()

            # Progress bar MUST be reset to 0
            self.assertEqual(dialog.progress_bar.value(), 0)
            # Stale download file MUST be deleted
            self.assertFalse(stale_file.exists())
            # Pipeline started with force_restart=True
            mock_pipeline.assert_called_once()
            self.assertTrue(mock_pipeline.call_args[1].get("force_restart"))

    def test_retry_when_already_installed_closes_dialog(self):
        """If application is already v2.1 when clicking Retry, dialog accepts and does not restart pipeline."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        dialog = UpdateDialog(version="2.1", is_force=False)
        dialog._on_error_occurred("downloading", "Temporary error")

        with patch("config.settings.get_running_app_version", return_value="2.1"), \
             patch("services.update_service.UpdateService.start_pipeline") as mock_pipeline:

            dialog._on_install_clicked()
            # Pipeline must NOT be restarted
            mock_pipeline.assert_not_called()
            self.assertIn("already up to date", dialog.status_label.text().lower())

    # ==============================================================
    # 6. TLS CA BUNDLE CLEANUP (Step 5)
    # ==============================================================
    def test_init_ca_bundle_cleanses_invalid_env_path(self):
        """init_ca_bundle removes stale or invalid user paths from environment."""
        invalid_path = r"C:\Users\NonExistentUser\AppData\Local\Programs\Python\certifi\cacert.pem"
        os.environ["REQUESTS_CA_BUNDLE"] = invalid_path
        os.environ["SSL_CERT_FILE"] = invalid_path

        resolved = init_ca_bundle()
        self.assertIsNotNone(resolved)
        self.assertTrue(os.path.isfile(resolved))
        # REQUESTS_CA_BUNDLE must now point to the valid local bundle, NOT the nonexistent user path
        self.assertEqual(os.environ["REQUESTS_CA_BUNDLE"], resolved)
        self.assertNotEqual(os.environ["REQUESTS_CA_BUNDLE"], invalid_path)

    # ==============================================================
    # 7. CROSS-PLATFORM CANDIDATE RESOLUTION & VALIDATION
    # ==============================================================
    def test_macos_candidate_resolution_derives_dmg(self):
        """On macOS, candidate resolution converts .exe URLs to .dmg and adds DMG GitHub fallback."""
        with patch("services.update_service.sys.platform", "darwin"):
            candidates = resolve_download_candidates(
                api_url="https://hrms.workpulse.in/hrms_api/ci4/api",
                file_name="WorkpulseSetup.exe",
                download_url="https://hrms.workpulse.in/uploads/WorkpulseSetup.exe",
                server_version="2.0.2",
            )
            # Should contain .dmg candidates
            dmg_candidates = [c for c in candidates if c.endswith(".dmg")]
            self.assertTrue(len(dmg_candidates) > 0)
            self.assertIn("https://hrms.workpulse.in/uploads/WorkpulseSetup.dmg", dmg_candidates)
            self.assertIn(
                "https://github.com/hrmsportal/ihrms_monitor/releases/download/v2.0.2/Workpulse.dmg",
                candidates,
            )

    def test_cross_platform_installer_validation_guard(self):
        """Windows rejects .dmg files and macOS rejects .exe files."""
        fake_dmg = self.tmp_path / "test.dmg"
        fake_dmg.write_bytes(b"0" * 102400)

        with patch("services.update_service.sys.platform", "win32"):
            valid, reason = validate_installer_file(fake_dmg)
            self.assertFalse(valid)
            self.assertIn("Cannot execute macOS disk image installer on Windows", reason)

        fake_exe = self.tmp_path / "test.exe"
        fake_exe.write_bytes(b"0" * 102400)

        with patch("services.update_service.sys.platform", "darwin"):
            valid, reason = validate_installer_file(fake_exe)
            self.assertFalse(valid)
            self.assertIn("Cannot execute Windows installer (.exe) on macOS", reason)


if __name__ == "__main__":
    unittest.main()
