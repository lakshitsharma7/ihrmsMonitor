"""Unit and Integration tests for Leave Balance API and UI."""

import os
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from config.api_config import ApiConfig
from services.attendance_service import AttendanceService
from services.session_service import SessionService, UserSession
from ui.attendance_page import AttendancePage
from ui.leave_balance_dialog import FIXED_LEAVE_TYPES, LeaveBalanceDialog, LeaveSummaryCard

# Ensure single QApplication instance for UI tests
app = QApplication.instance() or QApplication([])


class TestLeaveBalanceApiAndUi(unittest.TestCase):
    """Test Leave Balance API integration and LeaveBalanceDialog UI."""

    def setUp(self):
        self.api_config = ApiConfig()
        self.service = AttendanceService()
        from services.network_monitor import NetworkReachabilityMonitor
        NetworkReachabilityMonitor()._is_online = True

    def tearDown(self):
        from services.network_monitor import NetworkReachabilityMonitor
        NetworkReachabilityMonitor()._is_online = True

    def test_leave_quota_url_resolution(self):
        """Verify leave_quota_url returns correct endpoint."""
        with patch.object(self.api_config, "_base_url", "https://test.api/ci4/api"):
            url = self.api_config.leave_quota_url
            self.assertEqual(url, "https://test.api/ci4/api/leave/leave_quota")

    def test_leave_quota_url_env_override(self):
        """Verify environment variable overrides leave_quota_url."""
        override = "https://custom.api/ci4/api/leave/leave_quota_custom"
        with patch.dict(os.environ, {"IHRMS_LEAVE_QUOTA_API_URL": override}):
            url = self.api_config.leave_quota_url
            self.assertEqual(url, override)

    @patch("requests.post")
    def test_get_leave_quota_standard_list_success(self, mock_post):
        """Verify get_leave_quota parses standard list response and maps to 7 fixed leave types."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_response.json.return_value = {
            "status": 200,
            "response": "Success",
            "data": [
                {
                    "leave_type": "Casual Leave",
                    "short_name": "CL",
                    "total_quota": 12,
                    "used": 4,
                    "available": 8,
                },
                {
                    "leave_type": "Sick Leave",
                    "short_name": "SL",
                    "total_quota": 6,
                    "used": 6,
                    "available": 0,
                },
                {
                    "leave_type": "Earned Leave",
                    "short_name": "EL",
                    "total_quota": 15,
                    "used": 5,
                    "available": 10,
                },
            ],
        }
        mock_post.return_value = mock_response

        res = self.service.get_leave_quota(
            indo_code="EC-047",
            key="testapikey111",
            force=True,
        )

        self.assertEqual(res["status"], 200)
        self.assertIsNone(res["error"])
        self.assertEqual(len(res["items"]), 7)

        # 1. Check Item 0 (CL)
        cl = res["items"][0]
        self.assertEqual(cl["leave_type"], "Casual Leave")
        self.assertEqual(cl["short_name"], "CL")
        self.assertEqual(cl["total_quota"], 12.0)
        self.assertEqual(cl["used"], 4.0)
        self.assertEqual(cl["available"], 8.0)
        self.assertEqual(cl["status_label"], "Available")

        # 2. Check Item 1 (SL - Exhausted)
        sl = res["items"][1]
        self.assertEqual(sl["leave_type"], "Sick Leave")
        self.assertEqual(sl["short_name"], "SL")
        self.assertEqual(sl["available"], 0.0)
        self.assertEqual(sl["status_label"], "Exhausted")

        # 3. Check Item 5 (EL - Paid Leave mapped from Earned Leave)
        el = res["items"][5]
        self.assertEqual(el["leave_type"], "Paid Leave")
        self.assertEqual(el["short_name"], "EL")
        self.assertEqual(el["total_quota"], 15.0)
        self.assertEqual(el["used"], 5.0)
        self.assertEqual(el["available"], 10.0)

        # 4. Check Unmatched Items (e.g. CO, OD, LWP, RH fallback to 0)
        co = res["items"][2]
        self.assertEqual(co["short_name"], "CO")
        self.assertEqual(co["name"], "Comp Off")
        self.assertEqual(co["total_quota"], 0.0)

        # Summary check
        summary = res["summary"]
        self.assertEqual(summary["total_quota"], 33.0)
        self.assertEqual(summary["total_used"], 15.0)
        self.assertEqual(summary["total_available"], 18.0)
        self.assertEqual(summary["leave_types_count"], 7)

    @patch("requests.post")
    def test_get_leave_quota_comma_separated_actual_api_response(self, mock_post):
        """Verify get_leave_quota correctly parses the actual comma-separated API response and maps 7 fixed leave types in exact order."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_response.json.return_value = {
            "response": "Success",
            "status": 200,
            "data": {
                "lt_id": "1,2,3,4,5,6,7",
                "leaves": "202.00,100.00,0.00,133.34,233.34,203.00,0",
                "leavesTaked": "2,0,0,1,0.25,3,0",
                "remaining": "200,100,0,132.34,233.09,200,0",
            },
        }
        mock_post.return_value = mock_response

        res = self.service.get_leave_quota(
            indo_code="EC-047",
            key="testapikey111",
            force=True,
        )

        self.assertEqual(res["status"], 200)
        items = res["items"]
        self.assertEqual(len(items), 7)

        expected_sequence = [
            ("CL", "Casual Leave", 202.0, 2.0, 200.0),
            ("SL", "Sick Leave", 100.0, 0.0, 100.0),
            ("CO", "Comp Off", 0.0, 0.0, 0.0),
            ("OD", "Business Trip", 133.34, 1.0, 132.34),
            ("LWP", "Leave Without Pay", 233.34, 0.25, 233.09),
            ("EL", "Paid Leave", 203.0, 3.0, 200.0),
            ("RH", "Restricted/Floating", 0.0, 0.0, 0.0),
        ]

        for i, (code, name, total, used, left) in enumerate(expected_sequence):
            self.assertEqual(items[i]["short_name"], code)
            self.assertEqual(items[i]["code"], code)
            self.assertEqual(items[i]["leave_type"], name)
            self.assertEqual(items[i]["name"], name)
            self.assertAlmostEqual(items[i]["total_quota"], total, places=2)
            self.assertAlmostEqual(items[i]["used"], used, places=2)
            self.assertAlmostEqual(items[i]["available"], left, places=2)

        # Summary check
        summary = res["summary"]
        self.assertAlmostEqual(summary["total_quota"], 871.68, places=2)
        self.assertAlmostEqual(summary["total_used"], 6.25, places=2)
        self.assertAlmostEqual(summary["total_available"], 865.43, places=2)
        self.assertEqual(summary["leave_types_count"], 7)

    @patch("requests.post")
    def test_get_leave_quota_dynamic_session_auth(self, mock_post):
        """Verify get_leave_quota picks up indo_code and key from SessionService."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_response.json.return_value = {"status": 200, "data": []}
        mock_post.return_value = mock_response

        fake_user = UserSession(
            username="test.user",
            role="user",
            indo_code="EC-999",
            api_key="dynamic_session_key",
            company_code="COMP1",
            full_name="Test User",
        )

        with patch.object(SessionService(), "_current_user", fake_user):
            self.service.get_leave_quota(force=True)
            mock_post.assert_called_once()
            req_data = mock_post.call_args[1]["data"]
            self.assertEqual(req_data["indo_code"], "EC-999")
            self.assertEqual(req_data["key"], "dynamic_session_key")

    @patch("requests.post")
    def test_get_leave_quota_error_handling(self, mock_post):
        """Verify get_leave_quota handles API 400 error payload gracefully."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.content = b"Error"
        mock_response.json.return_value = {
            "status": 400,
            "error": 400,
            "messages": {
                "response": "Failed",
                "message": "Invalid API KEY",
            },
        }
        mock_post.return_value = mock_response

        res = self.service.get_leave_quota(
            indo_code="EC-047",
            key="badkey",
            force=True,
        )

        self.assertEqual(res["response"], "Failed")
        self.assertIn("Invalid API KEY", res["error"])
        self.assertEqual(len(res["items"]), 0)

    def test_leave_balance_dialog_renders_all_7_fixed_cards_in_exact_sequence(self):
        """Verify LeaveBalanceDialog always renders exactly 7 fixed cards with accurate sequence and names."""
        mock_service = MagicMock()
        mock_service.get_leave_quota.return_value = {
            "response": "Success",
            "status": 200,
            "items": [
                {"code": "CL", "name": "Casual Leave", "total_quota": 202.0, "total_quota_str": "202.00", "used": 2.0, "used_str": "2", "available": 200.0, "available_str": "200"},
                {"code": "SL", "name": "Sick Leave", "total_quota": 100.0, "total_quota_str": "100.00", "used": 0.0, "used_str": "0", "available": 100.0, "available_str": "100"},
                {"code": "CO", "name": "Comp Off", "total_quota": 0.0, "total_quota_str": "0.00", "used": 0.0, "used_str": "0", "available": 0.0, "available_str": "0"},
                {"code": "OD", "name": "Business Trip", "total_quota": 133.34, "total_quota_str": "133.34", "used": 1.0, "used_str": "1", "available": 132.34, "available_str": "132.34"},
                {"code": "LWP", "name": "Leave Without Pay", "total_quota": 233.34, "total_quota_str": "233.34", "used": 0.25, "used_str": "0.25", "available": 233.09, "available_str": "233.09"},
                {"code": "EL", "name": "Paid Leave", "total_quota": 203.0, "total_quota_str": "203.00", "used": 3.0, "used_str": "3", "available": 200.0, "available_str": "200"},
                {"code": "RH", "name": "Restricted/Floating", "total_quota": 0.0, "total_quota_str": "0", "used": 0.0, "used_str": "0", "available": 0.0, "available_str": "0"},
            ],
            "summary": {
                "total_quota": 871.68,
                "total_quota_str": "871.68",
                "total_used": 6.25,
                "total_used_str": "6.25",
                "total_available": 865.43,
                "total_available_str": "865.43",
                "leave_types_count": 7,
            },
            "error": None,
        }

        dialog = LeaveBalanceDialog(service=mock_service)
        dialog.refresh(async_mode=False)

        # 7 distinct cards rendered
        self.assertEqual(len(dialog._cards), 7)
        self.assertEqual(dialog.total_quota_val.text(), "871.68 Days")
        self.assertEqual(dialog.total_used_val.text(), "6.25 Days")
        self.assertEqual(dialog.total_avail_val.text(), "865.43 Days")

        # Verify all 7 card names and codes
        expected_cards = [
            ("CL", "Casual Leave"),
            ("SL", "Sick Leave"),
            ("CO", "Comp Off"),
            ("OD", "Business Trip"),
            ("LWP", "Leave Without Pay"),
            ("EL", "Paid Leave"),
            ("RH", "Restricted/Floating"),
        ]

        for idx, (exp_code, exp_name) in enumerate(expected_cards):
            card = dialog._cards[idx]
            self.assertEqual(card.code_badge.text(), exp_code)
            self.assertEqual(card.name_label.text(), exp_name)

        # Verify card 0 progress bar: 2 / 202 * 100 = ~0.99% -> 0%
        self.assertEqual(dialog._cards[0].usage_bar.value(), 0)
        # Verify card 4 progress bar: 0.25 / 233.34 * 100 = ~0.1% -> 0%
        self.assertEqual(dialog._cards[4].usage_bar.value(), 0)

    def test_leave_summary_card_progress_bar_calculation(self):
        """Verify LeaveSummaryCard correctly computes clamped progress bar percentage."""
        item = {
            "code": "CL",
            "name": "Casual Leave",
            "total": 10.0,
            "used": 4.0,
            "left": 6.0,
        }
        card = LeaveSummaryCard(item=item)
        self.assertEqual(card.code_badge.text(), "CL")
        self.assertEqual(card.name_label.text(), "Casual Leave")
        self.assertEqual(card.usage_bar.value(), 40)

        # Test zero total edge case
        item_zero = {
            "code": "RH",
            "name": "Restricted/Floating",
            "total": 0.0,
            "used": 0.0,
            "left": 0.0,
        }
        card_zero = LeaveSummaryCard(item=item_zero)
        self.assertEqual(card_zero.usage_bar.value(), 0)

    def test_leave_balance_dialog_error_state(self):
        """Verify LeaveBalanceDialog handles error state with banner."""
        mock_service = MagicMock()
        mock_service.get_leave_quota.return_value = {
            "response": "Failed",
            "status": 400,
            "items": [],
            "summary": {},
            "error": "Unable to load leave balance. Please try again.",
        }

        dialog = LeaveBalanceDialog(service=mock_service)
        dialog.refresh(async_mode=False)

        self.assertFalse(dialog.error_container.isHidden())
        self.assertEqual(dialog.error_label.text(), "Unable to load leave balance. Please try again.")
        self.assertTrue(dialog.scroll_area.isHidden())
        self.assertFalse(dialog.empty_state.isHidden())

    def test_attendance_page_has_leave_balance_button(self):
        """Verify AttendancePage header bar contains Leave Balance button."""
        mock_service = MagicMock()
        mock_service.get_monthly_attendance_record.return_value = {
            "response": "Success",
            "status": 200,
            "days": [],
            "summary": {},
            "error": None,
        }

        page = AttendancePage(service=mock_service)
        self.assertTrue(hasattr(page, "leave_balance_button"))
        self.assertEqual(page.leave_balance_button.text(), "Leave Balance")

        with patch.object(page, "_open_leave_balance_modal") as mock_open:
            page.leave_balance_button.click()
            mock_open.assert_called_once()

    @patch("requests.post")
    def test_actual_api_response_from_screenshot_parses_and_renders_ui(self, mock_post):
        """Verify the exact API response from user screenshot parses correctly and updates UI with real values."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        # Exact payload structure from screenshot:
        mock_response.json.return_value = {
            "response": 200,
            "status": 1,
            "leave_quota": [
                {
                    "indo_code": "EC-098",
                    "lt_id": "1,2,3,4,5,6,7",
                    "leaves": "202.00,100.00,0.00,133.34,233.34,203.00,0",
                    "leavesTaked": "2,0,0,1,0.25,3,0",
                    "remaining": "200,100,0,132.34,233.09,200,0",
                }
            ],
        }
        mock_post.return_value = mock_response

        # 1. Test Service Parsing
        res = self.service.get_leave_quota(indo_code="EC-098", key="testapikey111", force=True)
        self.assertIsNone(res["error"])
        self.assertEqual(len(res["items"]), 7)

        # Verify summary in API service output
        self.assertAlmostEqual(res["summary"]["total_quota"], 871.68, places=2)
        self.assertAlmostEqual(res["summary"]["total_used"], 6.25, places=2)
        self.assertAlmostEqual(res["summary"]["total_available"], 865.43, places=2)

        # 2. Test Dialog Integration
        mock_service = MagicMock()
        mock_service.get_leave_quota.return_value = res

        dialog = LeaveBalanceDialog(service=mock_service)
        dialog.refresh(async_mode=False)

        self.assertEqual(dialog.total_quota_val.text(), "871.68 Days")
        self.assertEqual(dialog.total_used_val.text(), "6.25 Days")
        self.assertEqual(dialog.total_avail_val.text(), "865.43 Days")

        # Verify all 7 cards in dialog
        self.assertEqual(len(dialog._cards), 7)
        # CL: 202 Total / 2 Used / 200 Left
        self.assertEqual(dialog._cards[0].code_badge.text(), "CL")
        # SL: 100 Total / 0 Used / 100 Left
        self.assertEqual(dialog._cards[1].code_badge.text(), "SL")
        # CO: 0 Total / 0 Used / 0 Left
        self.assertEqual(dialog._cards[2].code_badge.text(), "CO")
        # OD: 133.34 Total / 1 Used / 132.34 Left
        self.assertEqual(dialog._cards[3].code_badge.text(), "OD")
        # LWP: 233.34 Total / 0.25 Used / 233.09 Left
        self.assertEqual(dialog._cards[4].code_badge.text(), "LWP")
        # EL: 203 Total / 3 Used / 200 Left
        self.assertEqual(dialog._cards[5].code_badge.text(), "EL")
        # RH: 0 Total / 0 Used / 0 Left
        self.assertEqual(dialog._cards[6].code_badge.text(), "RH")

    @patch("requests.post")
    def test_dynamic_custom_leave_types(self, mock_post):
        """Verify dynamic leave types beyond standard 7 are parsed and rendered without code change."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_response.json.return_value = {
            "response": 200,
            "status": 1,
            "leave_quota": [
                {
                    "indo_code": "EC-098",
                    "lt_id": "1,2,8",
                    "leaves": "10,5,3",
                    "leavesTaked": "2,1,0",
                    "remaining": "8,4,3",
                }
            ],
        }
        mock_post.return_value = mock_response

        res = self.service.get_leave_quota(indo_code="EC-098", key="testapikey111", force=True)
        self.assertEqual(len(res["items"]), 7)
        self.assertEqual(res["items"][0]["code"], "CL")
        self.assertEqual(res["items"][1]["code"], "SL")
        self.assertEqual(res["items"][2]["code"], "LT8")
    def test_offline_suppresses_technical_error_box_and_shows_clean_offline(self):
        """Verify that when network is offline or connection fails with HTTPSConnectionPool, no red error box is shown."""
        mock_service = MagicMock()
        mock_service.get_leave_quota.return_value = {
            "response": "Failed",
            "status": 400,
            "items": [],
            "summary": {"total_quota": 0.0, "total_used": 0.0, "total_available": 0.0, "leave_types_count": 0},
            "error": "Network/Connection error: HTTPSConnectionPool(host='softdev.indovisionservices.in', port=443): Max retries exceeded with url: /ihrms84/hrms_api/ci4/api/leave/leave_quota",
        }

        dialog = LeaveBalanceDialog(service=mock_service)
        dialog.refresh(async_mode=False)

        # 1. Error container (red box) must NOT be visible when offline / connection error
        self.assertFalse(dialog.error_container.isVisible())

        # 2. Network status indicator should be Offline
        self.assertEqual(dialog.network_status_label.text(), "● Offline")

        # 3. No technical error strings or hostnames in error label
        self.assertNotIn("HTTPSConnectionPool", dialog.error_label.text())
        self.assertNotIn("softdev.indovisionservices.in", dialog.error_label.text())
        self.assertNotIn("Max retries", dialog.error_label.text())

        # 4. Old sync footer text must not exist
        self.assertFalse(hasattr(dialog, "status_hint"))

    def test_realtime_reachability_listener_updates_network_status(self):
        """Verify that reachability changes dynamically update network status label."""
        dialog = LeaveBalanceDialog(service=MagicMock())
        dialog.set_network_status(False)
        self.assertEqual(dialog.network_status_label.text(), "● Offline")

        dialog.set_network_status(True)
        self.assertEqual(dialog.network_status_label.text(), "● Online")

    def test_legitimate_application_error_is_sanitized(self):
        """Verify that genuine non-network application errors are displayed cleanly."""
        mock_service = MagicMock()
        mock_service.get_leave_quota.return_value = {
            "response": "Failed",
            "status": 400,
            "items": [],
            "summary": {"total_quota": 0.0, "total_used": 0.0, "total_available": 0.0, "leave_types_count": 0},
            "error": "Invalid API KEY",
        }

        from services.network_monitor import NetworkReachabilityMonitor
        NetworkReachabilityMonitor().report_online()

        dialog = LeaveBalanceDialog(service=mock_service)
        dialog.set_network_status(True)
        dialog.refresh(async_mode=False)

        self.assertFalse(dialog.error_container.isHidden())
        self.assertEqual(dialog.error_label.text(), "Invalid API KEY")


if __name__ == "__main__":
    unittest.main()
