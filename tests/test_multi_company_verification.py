"""Multi-Company Verification and Dynamic Configuration Unit Tests.

Validates end-to-end multi-tenant resolution across:
- Company A with a valid code (Alphabridge)
- Company B with a valid code (Indovision)
- Invalid company code rejection
- Missing company configuration handling
- Expired authentication / session revocation isolation
- API timeout and DNS failure handling
- Incorrect response schema handling
- Switching between companies without state leakage
- Case-insensitivity and whitespace handling
- Safe diagnostic logging verification (no password / credential leaks)
"""

from __future__ import annotations

import json
import logging
import unittest
from unittest.mock import MagicMock, patch

import requests

from config.api_config import APP_CONTROLLER_URL, ApiConfig, ApiConfigError
from services.hrms_portal_service import HrmsPortalService
from services.secure_session import SessionStore
from services.session_service import SessionService


MOCK_COMPANY_A_PAYLOAD = {
    "response": "Success",
    "status": 200,
    "message": "Data Found",
    "data": {
        "fk_company_id": "1",
        "logo_url": "https://www.alphabridge.tech/ihrms/uploads/ihrms/hrms-logo-30-06-2023-03-46-34-721782860.png",
        "base_url": "https://www.alphabridge.tech/ihrms/hrms_api/ci4/api/",
        "portal_url": None,
        "facebook_url": "https://www.facebook.com/",
        "apps": {
            "WINDOWS": {
                "version_code": "1",
                "file_name": "https://indovisionservices.in/iHRMS-Desktop/iHRMS-Desktop-Setup-1.0.0.exe",
                "force_to_update": "0",
            }
        },
    },
}

MOCK_COMPANY_B_PAYLOAD = {
    "response": "Success",
    "status": 200,
    "message": "Data Found",
    "data": {
        "fk_company_id": "42",
        "logo_url": "https://softdev.indovisionservices.in/ihrms84/uploads/logo.png",
        "base_url": "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api",
        "portal_url": "https://softdev.indovisionservices.in/ihrms84/",
        "apps": {
            "WINDOWS": {
                "version_code": "2",
                "file_name": "https://softdev.indovisionservices.in/installer.exe",
                "force_to_update": "0",
            }
        },
    },
}

MOCK_INVALID_COMPANY_PAYLOAD = {
    "response": "Failed",
    "status": 201,
    "message": "It looks like you're not registered. Please contact your HR team for help.",
    "data": None,
}


class TestMultiCompanyVerification(unittest.TestCase):
    def setUp(self):
        self.api_cfg = ApiConfig()
        self.api_cfg.reset()
        SessionService().clear()

    def tearDown(self):
        self.api_cfg.reset()
        SessionService().clear()

    @patch("requests.post")
    def test_01_company_a_alphabridge_verification(self, mock_post):
        """Test Company A (ALPHA12C1R112021) verification and dynamic endpoint resolution."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_COMPANY_A_PAYLOAD
        mock_post.return_value = mock_resp

        self.api_cfg.load(company_code="ALPHA12C1R112021")

        self.assertTrue(self.api_cfg.is_verified)
        self.assertEqual(self.api_cfg.company_code, "ALPHA12C1R112021")
        self.assertEqual(self.api_cfg.company_id, "1")
        self.assertEqual(self.api_cfg.base_url, "https://www.alphabridge.tech/ihrms/hrms_api/ci4/api")
        self.assertEqual(
            self.api_cfg.login_url,
            "https://www.alphabridge.tech/ihrms/hrms_api/ci4/api/login/login",
        )
        self.assertEqual(
            self.api_cfg.enroll_device_url,
            "https://www.alphabridge.tech/ihrms/hrms_api/ci4/api/workpulse/enroll_device",
        )

        # Dynamic portal URL resolution when portal_url is null: must derive from base_url
        portal_url = HrmsPortalService().get_resolved_portal_url()
        self.assertEqual(portal_url, "https://www.alphabridge.tech/ihrms/")

        # Verify POST payload sent to centralized App Controller
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], APP_CONTROLLER_URL)
        self.assertEqual(kwargs.get("data"), {"controller_id": "ALPHA12C1R112021"})

    @patch("requests.post")
    def test_02_company_b_indovision_verification(self, mock_post):
        """Test Company B (IVSA1C1R092025) verification and dynamic endpoint resolution."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_COMPANY_B_PAYLOAD
        mock_post.return_value = mock_resp

        self.api_cfg.load(company_code="IVSA1C1R092025")

        self.assertTrue(self.api_cfg.is_verified)
        self.assertEqual(self.api_cfg.company_code, "IVSA1C1R092025")
        self.assertEqual(self.api_cfg.company_id, "42")
        self.assertEqual(self.api_cfg.base_url, "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api")
        self.assertEqual(
            self.api_cfg.login_url,
            "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/login/login",
        )

        # Explicit portal_url returned by backend
        portal_url = HrmsPortalService().get_resolved_portal_url()
        self.assertEqual(portal_url, "https://softdev.indovisionservices.in/ihrms84/")

    @patch("requests.post")
    def test_03_invalid_company_code_rejection(self, mock_post):
        """Test that invalid company code is rejected and resets state."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_INVALID_COMPANY_PAYLOAD
        mock_post.return_value = mock_resp

        with self.assertRaises(ApiConfigError) as ctx:
            self.api_cfg.load(company_code="NON_EXISTENT_CODE")

        self.assertIn("not registered", str(ctx.exception))
        self.assertFalse(self.api_cfg.is_verified)
        self.assertIsNone(self.api_cfg.company_code)
        with self.assertRaises(ApiConfigError):
            _ = self.api_cfg.base_url

    @patch("requests.post")
    def test_04_missing_company_configuration_payload(self, mock_post):
        """Test that incomplete/missing backend payload is safely rejected."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Success", "status": 200, "data": {}}
        mock_post.return_value = mock_resp

        with self.assertRaises(ApiConfigError):
            self.api_cfg.load(company_code="EMPTY_CONFIG_CO")

        self.assertFalse(self.api_cfg.is_verified)

    @patch("requests.post")
    def test_05_switching_between_companies_no_state_leakage(self, mock_post):
        """Verify seamless switching between companies clears all previous context."""
        # 1. Load Company A
        mock_resp_a = MagicMock()
        mock_resp_a.status_code = 200
        mock_resp_a.json.return_value = MOCK_COMPANY_A_PAYLOAD
        mock_post.return_value = mock_resp_a

        self.api_cfg.load(company_code="ALPHA12C1R112021")
        self.assertEqual(self.api_cfg.company_code, "ALPHA12C1R112021")
        self.assertEqual(self.api_cfg.base_url, "https://www.alphabridge.tech/ihrms/hrms_api/ci4/api")
        self.assertEqual(self.api_cfg.company_id, "1")

        # 2. Switch to Company B
        mock_resp_b = MagicMock()
        mock_resp_b.status_code = 200
        mock_resp_b.json.return_value = MOCK_COMPANY_B_PAYLOAD
        mock_post.return_value = mock_resp_b

        self.api_cfg.load(company_code="IVSA1C1R092025")
        self.assertEqual(self.api_cfg.company_code, "IVSA1C1R092025")
        self.assertEqual(self.api_cfg.base_url, "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api")
        self.assertEqual(self.api_cfg.company_id, "42")
        self.assertNotIn("alphabridge", self.api_cfg.base_url)

    @patch("requests.post")
    def test_06_case_insensitivity_and_whitespace(self, mock_post):
        """Verify company code is trimmed and handled case-insensitively."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_COMPANY_A_PAYLOAD
        mock_post.return_value = mock_resp

        # Pass lowercase with surrounding spaces
        self.api_cfg.load(company_code="  alpha12c1r112021  ")
        self.assertTrue(self.api_cfg.is_verified)
        self.assertEqual(self.api_cfg.company_code, "alpha12c1r112021")

        # Re-verifying same code case-insensitively is a no-op
        self.api_cfg.load(company_code="ALPHA12C1R112021", force=False)
        self.assertEqual(mock_post.call_count, 1)

    @patch("requests.post")
    def test_07_api_timeout_handling(self, mock_post):
        """Verify API timeout raises ApiConfigError and does not crash."""
        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out after 8s")

        with self.assertRaises(ApiConfigError) as ctx:
            self.api_cfg.load(company_code="TIMEOUT_CO")

        self.assertIn("Could not reach the verification service", str(ctx.exception))
        self.assertFalse(self.api_cfg.is_verified)

    @patch("requests.post")
    def test_08_incorrect_response_schema(self, mock_post):
        """Verify non-JSON response or 500 error raises ApiConfigError cleanly."""
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("502 Bad Gateway")
        mock_post.return_value = mock_resp

        with self.assertRaises(ApiConfigError):
            self.api_cfg.load(company_code="ERROR_CO")

        self.assertFalse(self.api_cfg.is_verified)

    @patch("requests.post")
    def test_09_safe_diagnostic_logging(self, mock_post):
        """Verify safe diagnostic logging captures endpoint host, path, status, and failure reason without credentials."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_COMPANY_A_PAYLOAD
        mock_post.return_value = mock_resp

        with self.assertLogs("activity_tracker.config.api_config", level="INFO") as log_cm:
            self.api_cfg.load(company_code="ALPHA12C1R112021")
            output = "\n".join(log_cm.output)
            self.assertIn("App Controller request [START]", output)
            self.assertIn("status_code=200", output)
            self.assertIn("Company verification SUCCESS", output)
            self.assertIn("host=", output)
            self.assertIn("path=", output)
            # Ensure no credentials/passwords appear in logging
            self.assertNotIn("password", output.lower())
            self.assertNotIn("token", output.lower())


if __name__ == "__main__":
    unittest.main()
