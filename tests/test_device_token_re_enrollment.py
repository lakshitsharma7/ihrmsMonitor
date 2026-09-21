import unittest
import tempfile
import requests
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch
from services.sync_service import SyncService, _mask_token
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
        SessionService().login(
            username="EMP001",
            role="User",
            employee_id="1001",
            indo_code="INDO123",
            api_key="valid_api_key",
            company_code="COMP123",
            device_token="old_revoked_token",
        )
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
        self.assertEqual(SessionService().current_user.device_token, "new_enrolled_token_999")
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

    def test_require_device_token_from_active_user(self):
        """Verify _require_device_token adopts and synchronizes active user's device token."""
        SessionService().login(
            username="user_active",
            role="User",
            employee_id="EMP_ACT_1",
            device_token="TOKEN_ACTIVE_123",
        )
        token = SyncService._require_device_token()
        self.assertEqual(token, "TOKEN_ACTIVE_123")
        self.assertEqual(SessionService().device_token, "TOKEN_ACTIVE_123")

    @patch("services.sync_service.requests.post")
    def test_network_timeout_does_not_mark_auth_failed(self, mock_post):
        """Verify network timeout marks status as Timeout / Offline rather than Auth Failed."""
        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

        payload = {"device_token": "VALID_TOKEN_123", "activities": []}
        res = self.sync_service._send_request_with_retry(payload, page=1, retries=1)

        self.assertIsNone(res)
        self.assertEqual(SyncService.last_sync_status, "Failed (Timeout)")
        self.assertNotIn("Auth", SyncService.last_sync_status)

    @patch("services.sync_service.requests.post")
    def test_network_connection_error_does_not_mark_auth_failed(self, mock_post):
        """Verify server connection error marks status as Offline rather than Auth Failed."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Failed to establish a new connection")

        payload = {"device_token": "VALID_TOKEN_123", "activities": []}
        res = self.sync_service._send_request_with_retry(payload, page=1, retries=1)

        self.assertIsNone(res)
        self.assertEqual(SyncService.last_sync_status, "Failed (Offline)")
        self.assertNotIn("Auth", SyncService.last_sync_status)

    @patch.object(SyncService, "re_enroll_device", return_value=None)
    @patch("services.sync_service.requests.post")
    def test_unrecoverable_401_marks_auth_failed(self, mock_post, mock_re_enroll):
        """Verify that genuine 401 where re-enrollment returns None sets Auth Failed status."""
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.text = "Unauthorized"
        mock_post.return_value = resp_401

        payload = {"device_token": "REVOKED_TOKEN", "activities": []}
        res = self.sync_service._send_request_with_retry(payload, page=1, retries=1)

        self.assertIsNone(res)
        self.assertEqual(SyncService.last_sync_status, "Failed (Auth Failed)")
        self.assertIn("401", SyncService.last_sync_error)

    def test_mask_token_helper(self):
        """Verify _mask_token masks tokens securely without exposing full value."""
        self.assertEqual(_mask_token(None), "<None>")
        self.assertEqual(_mask_token(""), "<None>")
        self.assertEqual(_mask_token("12345"), "***")
        masked = _mask_token("abcdef1234567890xyz")
        self.assertTrue(masked.startswith("abcd...0xyz"))
        self.assertNotIn("123456789", masked)


if __name__ == "__main__":
    unittest.main()
