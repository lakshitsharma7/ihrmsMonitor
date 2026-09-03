"""
Comprehensive tests for local storage, offline tracking, upload synchronization,
server-verified deletion, and cleanup sweeps.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from database.database import Base, get_session
from database.models import ActivitySession
from database.repository import ActivityRepository
from services.session_service import SessionService, UserSession
from services.sync_service import SyncService


class TestLocalStorageAndCleanupFlow(unittest.TestCase):
    """Verify offline storage, sync on reconnection, and server-verified screenshot deletion."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.screenshots_dir = Path(self.temp_dir.name) / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.db_session = get_session()
        # Clean test tables
        for table in reversed(Base.metadata.sorted_tables):
            self.db_session.execute(table.delete())
        self.db_session.commit()

        self.repo = ActivityRepository(self.db_session)
        self.sync_service = SyncService(api_url="https://mock.api/hrms_api/ci4/api")

    def test_dynamic_windows_appdata_paths_structure(self):
        """Verify that paths dynamically resolve under %LOCALAPPDATA%\\iHRMS Monitor with data, screenshots, logs."""
        from utils.paths import (
            get_app_data_directory,
            get_data_directory,
            get_database_path,
            get_screenshots_directory,
            get_logs_directory,
        )
        app_data = get_app_data_directory()
        self.assertTrue(str(app_data).endswith("iHRMS Monitor"))

        data_dir = get_data_directory()
        self.assertEqual(data_dir, app_data / "data")
        self.assertTrue(data_dir.exists())

        db_path = get_database_path()
        self.assertEqual(db_path, data_dir / "activity_tracker.db")

        screenshots_dir = get_screenshots_directory()
        self.assertEqual(screenshots_dir, app_data / "screenshots")
        self.assertTrue(screenshots_dir.exists())

        logs_dir = get_logs_directory()
        self.assertEqual(logs_dir, app_data / "logs")
        self.assertTrue(logs_dir.exists())

    def tearDown(self):
        self.db_session.close()
        self.temp_dir.cleanup()

    def test_offline_tracking_persists_data_safely(self):
        """Verify that offline activity and screenshot are saved locally and not lost."""
        # 1. Simulate offline screenshot creation
        screenshot_file = self.screenshots_dir / "sess_101.png"
        screenshot_file.write_bytes(b"PNG_OFFLINE_IMAGE_DATA_101")
        self.assertTrue(screenshot_file.exists())

        # 2. Simulate offline activity session in SQLite
        sess = self.repo.create_session(
            application_name="VSCode.exe",
            process_id=1234,
            window_title="Project - Offline Work",
            started_at=datetime.now(timezone.utc),
            employee_id="EMP_OFFLINE_01",
        )
        self.repo.update_session_screenshot_path(sess.id, str(screenshot_file))
        self.repo.close_session(sess.id, datetime.now(timezone.utc), 120)

        # 3. Verify session state in local DB
        loaded = self.db_session.get(ActivitySession, sess.id)
        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded.server_session_id)
        self.assertFalse(loaded.screenshot_uploaded)
        self.assertEqual(loaded.screenshot_path, str(screenshot_file))
        self.assertTrue(Path(loaded.screenshot_path).exists())

    def test_reconnect_uploads_and_cleans_local_screenshot_on_server_success(self):
        """
        Verify that on reconnect, session is synced, screenshot is uploaded,
        and local screenshot is deleted ONLY after server confirms success.
        """
        screenshot_file = self.screenshots_dir / "sess_202.png"
        screenshot_file.write_bytes(b"PNG_RECONNECT_DATA_202")
        self.assertTrue(screenshot_file.exists())

        sess = self.repo.create_session(
            application_name="Chrome.exe",
            process_id=5678,
            window_title="HRMS Portal",
            started_at=datetime.now(timezone.utc),
            employee_id="EMP_RECONNECT_01",
        )
        self.repo.update_session_screenshot_path(sess.id, str(screenshot_file))
        self.repo.close_session(sess.id, datetime.now(timezone.utc), 300)

        mock_user = UserSession(
            username="test_user",
            role="employee",
            employee_id="EMP_RECONNECT_01",
            device_token="DEV_TOKEN_VALID",
        )

        # Mock API batch sync and screenshot upload
        batch_response = {
            "response": "Success",
            "data": [
                {
                    "client_session_ref": str(sess.id),
                    "activity_session_id": "SRV_SESS_999",
                }
            ],
        }

        mock_screenshot_resp = MagicMock()
        mock_screenshot_resp.status_code = 200
        mock_screenshot_resp.json.return_value = {
            "response": "Success",
            "message": "Screenshot uploaded successfully.",
            "data": {"screenshot_id": "SRV_SHOT_888"},
        }
        mock_screenshot_resp.text = json.dumps(mock_screenshot_resp.json.return_value)

        session_service = SessionService()
        session_service._current_user = mock_user
        session_service.device_token = "DEV_TOKEN_VALID"

        with patch.object(self.sync_service, "_require_device_token", return_value="DEV_TOKEN_VALID"), \
             patch.object(self.sync_service, "fetch_settings", return_value={}), \
             patch.object(self.sync_service, "_send_request_with_retry", return_value=batch_response), \
             patch("requests.post", return_value=mock_screenshot_resp):

            # Trigger sync
            result = self.sync_service.sync_activity_now()
            self.assertTrue(result)

        # Verify DB states
        self.db_session.expire_all()
        updated_sess = self.db_session.get(ActivitySession, sess.id)
        self.assertEqual(updated_sess.server_session_id, "SRV_SESS_999")
        self.assertTrue(updated_sess.screenshot_uploaded)

        # Verify local screenshot file is cleanly removed
        self.assertFalse(screenshot_file.exists(), "Screenshot should be deleted after successful upload confirmation")

    def test_failed_screenshot_upload_preserves_local_file_for_retry(self):
        """Verify that when screenshot upload fails, the local file is NOT deleted."""
        screenshot_file = self.screenshots_dir / "sess_303.png"
        screenshot_file.write_bytes(b"PNG_FAILED_ATTEMPT_DATA_303")
        self.assertTrue(screenshot_file.exists())

        sess = self.repo.create_session(
            application_name="Excel.exe",
            process_id=9999,
            window_title="Spreadsheet.xlsx",
            started_at=datetime.now(timezone.utc),
            employee_id="EMP_FAIL_01",
        )
        self.repo.update_session_screenshot_path(sess.id, str(screenshot_file))
        self.repo.update_session_server_id(sess.id, "SRV_SESS_FAIL_1")
        self.repo.close_session(sess.id, datetime.now(timezone.utc), 180)

        # Simulate upload error (e.g. 500 Server Error)
        mock_err_resp = MagicMock()
        mock_err_resp.status_code = 500
        mock_err_resp.raise_for_status.side_effect = Exception("HTTP 500 Server Error")

        with patch("services.sync_service.SyncService._require_device_token", return_value="DEV_TOKEN_123"), \
             patch("requests.post", return_value=mock_err_resp):

            success = self.sync_service.upload_screenshot_now(
                screenshot_path=screenshot_file,
                activity_session_id="SRV_SESS_FAIL_1",
                application_name="Excel.exe",
                process_id=9999,
                captured_at=sess.started_at,
                local_session_id=sess.id,
            )
            self.assertFalse(success)

        # Verify DB state & file retention
        self.db_session.expire_all()
        updated_sess = self.db_session.get(ActivitySession, sess.id)
        self.assertFalse(updated_sess.screenshot_uploaded)
        self.assertTrue(screenshot_file.exists(), "Screenshot must NOT be deleted when upload fails")

    def test_cleanup_uploaded_screenshots_sweep(self):
        """Verify that cleanup sweep only deletes confirmed uploaded files and leaves unuploaded files intact."""
        # File 1: Confirmed uploaded
        file_uploaded = self.screenshots_dir / "uploaded_01.png"
        file_uploaded.write_bytes(b"DATA_UPLOADED")

        sess_up = self.repo.create_session(
            application_name="App1.exe",
            process_id=1,
            window_title="Uploaded App",
            started_at=datetime.now(timezone.utc),
            employee_id="EMP_SWEEP_01",
        )
        self.repo.update_session_screenshot_path(sess_up.id, str(file_uploaded))
        self.repo.update_session_screenshot_uploaded(sess_up.id, True)

        # File 2: Unuploaded pending
        file_pending = self.screenshots_dir / "pending_02.png"
        file_pending.write_bytes(b"DATA_PENDING")

        sess_pend = self.repo.create_session(
            application_name="App2.exe",
            process_id=2,
            window_title="Pending App",
            started_at=datetime.now(timezone.utc),
            employee_id="EMP_SWEEP_01",
        )
        self.repo.update_session_screenshot_path(sess_pend.id, str(file_pending))
        self.repo.update_session_screenshot_uploaded(sess_pend.id, False)

        # Run sweep
        cleaned = self.sync_service.cleanup_uploaded_screenshots()
        self.assertEqual(cleaned, 1)

        # Assert file_uploaded is deleted, file_pending is kept
        self.assertFalse(file_uploaded.exists(), "Uploaded file should be removed by sweep")
        self.assertTrue(file_pending.exists(), "Pending file must NOT be touched by sweep")


if __name__ == "__main__":
    unittest.main()
