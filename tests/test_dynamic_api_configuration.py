"""Unit tests verifying that all application APIs are dynamically configurable."""

import os
import unittest
from unittest.mock import patch

from config.api_config import ApiConfig, APP_CONTROLLER_URL
from services.sync_service import SyncService
from services.error_report_service import ErrorReportService


class TestDynamicApiConfiguration(unittest.TestCase):
    def setUp(self):
        self.api_cfg = ApiConfig()
        self.api_cfg.reset()
        self.api_cfg._base_url = "https://default.company.com/hrms_api/ci4/api"
        self.api_cfg._company_code = "COMP_TEST"

    def tearDown(self):
        self.api_cfg.reset()

    def test_01_app_controller_url_remains_unchanged(self):
        """Verify AppController URL is fixed and explicitly excluded from modifications."""
        self.assertEqual(
            APP_CONTROLLER_URL,
            "https://info.indovisionservices.in/dev/v15/hrms_api/v7/api/appcontroller/appcontroller",
        )

    def test_02_default_dynamic_endpoint_resolution(self):
        """Verify all APIs dynamically resolve using current base_url."""
        self.assertEqual(
            self.api_cfg.login_url,
            "https://default.company.com/hrms_api/ci4/api/login/login",
        )
        self.assertEqual(
            self.api_cfg.enroll_device_url,
            "https://default.company.com/hrms_api/ci4/api/tracking/enroll_device",
        )
        self.assertEqual(
            self.api_cfg.get_settings_url,
            "https://default.company.com/hrms_api/ci4/api/tracking/get_settings",
        )
        self.assertEqual(
            self.api_cfg.save_activity_batch_url,
            "https://default.company.com/hrms_api/ci4/api/tracking/save_activity_batch",
        )
        self.assertEqual(
            self.api_cfg.upload_screenshot_url,
            "https://default.company.com/hrms_api/ci4/api/tracking/upload_screenshot",
        )
        self.assertEqual(
            self.api_cfg.check_version_url,
            "https://info.indovisionservices.in/dev/v15/hrms_api/v7/api/appcontroller/appcontroller",
        )
        self.assertEqual(
            self.api_cfg.report_error_url,
            "https://default.company.com/hrms_api/ci4/api/tracking/report_error",
        )
        self.assertEqual(
            self.api_cfg.punch_url,
            "https://default.company.com/hrms_api/ci4/api/punch/get_punch_time",
        )

    def test_03_base_url_change_dynamically_propagates_to_all_apis(self):
        """Verify that changing base_url instantly changes all endpoints."""
        self.api_cfg._base_url = "https://new-server.internal.org/api/v2"
        self.assertEqual(
            self.api_cfg.login_url,
            "https://new-server.internal.org/api/v2/login/login",
        )
        self.assertEqual(
            self.api_cfg.enroll_device_url,
            "https://new-server.internal.org/api/v2/tracking/enroll_device",
        )
        self.assertEqual(
            self.api_cfg.get_settings_url,
            "https://new-server.internal.org/api/v2/tracking/get_settings",
        )
        self.assertEqual(
            self.api_cfg.save_activity_batch_url,
            "https://new-server.internal.org/api/v2/tracking/save_activity_batch",
        )
        self.assertEqual(
            self.api_cfg.upload_screenshot_url,
            "https://new-server.internal.org/api/v2/tracking/upload_screenshot",
        )
        self.assertEqual(
            self.api_cfg.check_version_url,
            "https://info.indovisionservices.in/dev/v15/hrms_api/v7/api/appcontroller/appcontroller",
        )
        self.assertEqual(
            self.api_cfg.report_error_url,
            "https://new-server.internal.org/api/v2/tracking/report_error",
        )
        self.assertEqual(
            self.api_cfg.punch_url,
            "https://new-server.internal.org/api/v2/punch/get_punch_time",
        )

    def test_04_individual_environment_variable_overrides(self):
        """Verify individual API endpoints can be dynamically overridden via environment variables."""
        env_overrides = {
            "IHRMS_LOGIN_API_URL": "https://auth.gateway.com/custom_login",
            "IHRMS_ENROLL_DEVICE_API_URL": "https://auth.gateway.com/custom_enroll",
            "IHRMS_GET_SETTINGS_API_URL": "https://settings.gateway.com/config",
            "IHRMS_SAVE_ACTIVITY_BATCH_API_URL": "https://stream.gateway.com/activities",
            "IHRMS_UPLOAD_SCREENSHOT_API_URL": "https://storage.gateway.com/screenshots",
            "IHRMS_CHECK_VERSION_API_URL": "https://updates.gateway.com/check_version",
            "IHRMS_REPORT_ERROR_API_URL": "https://logs.gateway.com/errors",
            "IHRMS_PUNCH_API_URL": "https://punch.gateway.com/get_punch_time",
        }
        with patch.dict(os.environ, env_overrides):
            self.assertEqual(self.api_cfg.login_url, "https://auth.gateway.com/custom_login")
            self.assertEqual(self.api_cfg.enroll_device_url, "https://auth.gateway.com/custom_enroll")
            self.assertEqual(self.api_cfg.get_settings_url, "https://settings.gateway.com/config")
            self.assertEqual(self.api_cfg.save_activity_batch_url, "https://stream.gateway.com/activities")
            self.assertEqual(self.api_cfg.upload_screenshot_url, "https://storage.gateway.com/screenshots")
            self.assertEqual(self.api_cfg.check_version_url, "https://updates.gateway.com/check_version")
            self.assertEqual(self.api_cfg.report_error_url, "https://logs.gateway.com/errors")
            self.assertEqual(self.api_cfg.punch_url, "https://punch.gateway.com/get_punch_time")

    def test_05_sync_service_uses_dynamic_urls(self):
        """Verify SyncService routes requests through dynamic ApiConfig properties."""
        sync_svc = SyncService(api_url="https://fallback.com")
        self.assertEqual(sync_svc.get_settings_url, "https://default.company.com/hrms_api/ci4/api/tracking/get_settings")
        self.assertEqual(sync_svc.save_activity_batch_url, "https://default.company.com/hrms_api/ci4/api/tracking/save_activity_batch")
        self.assertEqual(sync_svc.upload_screenshot_url, "https://default.company.com/hrms_api/ci4/api/tracking/upload_screenshot")


if __name__ == "__main__":
    unittest.main()
