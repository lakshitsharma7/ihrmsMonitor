import unittest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch
from services.sync_service import SyncService
from services.secure_session import SessionStore
from services.session_service import SessionService

class TestDeviceTokenReEnrollment(unittest.TestCase):
    def setUp(self):
        SessionService().clear()
        self.sync_service = SyncService(
            api_url="https://test.api"
        )

    @patch("services.sync_service.requests.post")
    @patch.object(SessionStore, "load_session")
    @patch.object(SessionStore, "update_device_token")
    def test_re_enroll_device_success(self, mock_update_token, mock_load_session, mock_post):
        mock_load_session.return_value = {
            "indo_code": "INDO123",
            "api_key": "valid_api_key",
            "username": "EMP001",
            "device_token": "old_revoked_token",
            "base_url": "https://test.api",
        }
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "data": {
                "device_token": "new_enrolled_token_999"
            }
        }
        mock_post.return_value = mock_resp

        new_token = self.sync_service.re_enroll_device()
        self.assertEqual(new_token, "new_enrolled_token_999")
        self.assertEqual(SessionService().device_token, "new_enrolled_token_999")
        mock_update_token.assert_called_once_with("new_enrolled_token_999")

    @patch.object(SyncService, "re_enroll_device")
    @patch("services.sync_service.requests.post")
    def test_activity_batch_401_triggers_re_enroll_and_retry(self, mock_post, mock_re_enroll):
        mock_re_enroll.return_value = "new_token_123"

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.text = '{"response": "Failed", "message": "Device not recognized or has been revoked."}'
        resp_401.json.return_value = {"response": "Failed", "message": "Device not recognized or has been revoked."}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"response": "Success", "status": "success", "data": {"saved": 1}}

        mock_post.side_effect = [resp_401, resp_200]

        payload = {"device_token": "old_revoked_token", "activities": [{"id": 1}]}
        res = self.sync_service._send_request_with_retry(payload, page=1)

        self.assertEqual(res, {"response": "Success", "status": "success", "data": {"saved": 1}})
        mock_re_enroll.assert_called_once()
        self.assertEqual(mock_post.call_args_list[1][1]["data"]["device_token"], "new_token_123")

    @patch.object(SessionStore, "load_session")
    @patch.object(SyncService, "re_enroll_device")
    @patch("services.sync_service.requests.post")
    def test_screenshot_401_triggers_re_enroll_and_retry(self, mock_post, mock_re_enroll, mock_load_session):
        mock_load_session.return_value = {
            "indo_code": "INDO123",
            "api_key": "valid_api_key",
            "username": "EMP001",
            "device_token": "old_revoked_token",
            "base_url": "https://test.api",
        }
        mock_re_enroll.return_value = "new_token_123"

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.text = '{"response": "Failed", "message": "Device not recognized or has been revoked."}'
        resp_401.json.return_value = {"response": "Failed", "message": "Device not recognized or has been revoked."}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"response": "Success", "status": "success"}

        mock_post.side_effect = [resp_401, resp_200]

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            tmp_file.write(b"fake_png_data")
            tmp_path = tmp_file.name

        try:
            success = self.sync_service.upload_screenshot_now(
                screenshot_path=tmp_path,
                activity_session_id=1,
                application_name="TestApp.exe",
                process_id=1234,
                captured_at=datetime.now()
            )

            self.assertTrue(success)
            mock_re_enroll.assert_called_once()
            self.assertEqual(mock_post.call_args_list[1][1]["data"]["device_token"], "new_token_123")
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()


if __name__ == "__main__":
    unittest.main()
