"""Unit and Integration tests for Leave Balance API and UI."""

import os
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from config.api_config import ApiConfig
from services.attendance_service import AttendanceService
from services.session_service import SessionService, UserSession
from ui.attendance_page import AttendancePage
from ui.leave_balance_dialog import LeaveBalanceDialog

# Ensure single QApplication instance for UI tests
app = QApplication.instance() or QApplication([])


class TestLeaveBalanceApiAndUi(unittest.TestCase):
    """Test Leave Balance API integration and LeaveBalanceDialog UI."""

    def setUp(self):
        self.api_config = ApiConfig()
        self.service = AttendanceService()

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
        """Verify get_leave_quota parses standard list response."""
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
        self.assertEqual(len(res["items"]), 3)

        # Check First Item (CL)
        cl = res["items"][0]
        self.assertEqual(cl["leave_type"], "Casual Leave")
        self.assertEqual(cl["short_name"], "CL")
        self.assertEqual(cl["total_quota"], 12.0)
        self.assertEqual(cl["used"], 4.0)
        self.assertEqual(cl["available"], 8.0)
        self.assertEqual(cl["status_label"], "Available")

        # Check Second Item (SL - Exhausted)
        sl = res["items"][1]
        self.assertEqual(sl["leave_type"], "Sick Leave")
        self.assertEqual(sl["available"], 0.0)
        self.assertEqual(sl["status_label"], "Exhausted")

        # Check Summary
        summary = res["summary"]
        self.assertEqual(summary["total_quota"], 33.0)
        self.assertEqual(summary["total_used"], 15.0)
        self.assertEqual(summary["total_available"], 18.0)
        self.assertEqual(summary["leave_types_count"], 3)

    @patch("requests.post")
    def test_get_leave_quota_dynamic_id_and_name_mapping(self, mock_post):
        """Verify leave_type resolution: API-provided names are used, and unmapped numeric IDs fallback safely to 'Leave Type (ID: <id>)' without hardcoded constants."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_response.json.return_value = {
            "status": 200,
            "response": "Success",
            "data": [
                {"leave_type": 1, "leave_type_name": "Casual Leave", "carry_over": 0, "mar": 1.00},
                {"leave_type": 2, "leave_name": "Sick Leave", "allotted": 6, "used": 2, "available": 4},
                {"leave_type": 3, "name": "Comp Off", "total_quota": 5, "used": 0, "available": 5},
                {"leave_type": 4, "total_quota": 3, "used": 1, "available": 2},  # No name field -> Safe dynamic fallback
                {"leave_type": 99, "total_quota": 4, "used": 0, "available": 4},  # Unknown ID fallback
            ],
        }
        mock_post.return_value = mock_response

        res = self.service.get_leave_quota(
            indo_code="EC-047",
            key="testapikey111",
            force=True,
        )

        self.assertEqual(res["status"], 200)
        items = res["items"]
        self.assertEqual(len(items), 5)

        # 1: Casual Leave (from leave_type_name)
        self.assertEqual(items[0]["leave_type"], "Casual Leave")
        self.assertEqual(items[0]["carry_over"], 0.0)
        self.assertEqual(items[0]["available"], 1.0)
        self.assertEqual(items[0]["total_quota"], 1.0)
        self.assertIn("mar", items[0]["dynamic_fields"])

        # 2: Sick Leave (from leave_name)
        self.assertEqual(items[1]["leave_type"], "Sick Leave")
        self.assertEqual(items[1]["available"], 4.0)

        # 3: Comp Off (from name)
        self.assertEqual(items[2]["leave_type"], "Comp Off")

        # 4: No name field -> Safe fallback "Leave Type (ID: 4)"
        self.assertEqual(items[3]["leave_type"], "Leave Type (ID: 4)")

        # 99: Unknown fallback "Leave Type (ID: 99)"
        self.assertEqual(items[4]["leave_type"], "Leave Type (ID: 99)")

    @patch("requests.post")
    def test_get_leave_quota_dict_format(self, mock_post):
        """Verify get_leave_quota parses nested dictionary format."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_response.json.return_value = {
            "status": 200,
            "response": "Success",
            "leave_quota": {
                "Casual Leave": {
                    "quota": 10,
                    "taken": 3,
                    "available": 7,
                },
                "Sick Leave": {
                    "allotted": 18,
                    "consumed": 6,
                    "remaining": 12,
                },
            },
        }
        mock_post.return_value = mock_response

        res = self.service.get_leave_quota(
            indo_code="EC-047",
            key="testapikey111",
            force=True,
        )

        self.assertEqual(res["status"], 200)
        self.assertEqual(len(res["items"]), 2)
        self.assertEqual(res["items"][0]["leave_type"], "Casual Leave")
        self.assertEqual(res["items"][1]["leave_type"], "Sick Leave")
        self.assertEqual(res["summary"]["total_available"], 19.0)

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

    def test_leave_balance_dialog_ui_rendering_cards(self):
        """Verify LeaveBalanceDialog correctly renders loaded leave data into LeaveSummaryCard widgets."""
        mock_service = MagicMock()
        mock_service.get_leave_quota.return_value = {
            "response": "Success",
            "status": 200,
            "items": [
                {
                    "leave_type": "Casual Leave",
                    "short_name": "CL",
                    "carry_over": 0.0,
                    "carry_over_str": "0",
                    "total_quota": 202.0,
                    "total_quota_str": "202.00",
                    "used": 2.0,
                    "used_str": "2",
                    "available": 200.0,
                    "available_str": "200.00",
                    "unit": "Days",
                    "status_label": "Available",
                    "color": "#16A34A",
                    "bg_color": "#DCFCE7",
                },
                {
                    "leave_type": "Sick Leave",
                    "short_name": "SL",
                    "carry_over": 0.0,
                    "carry_over_str": "0",
                    "total_quota": 100.0,
                    "total_quota_str": "100.00",
                    "used": 0.0,
                    "used_str": "0",
                    "available": 100.0,
                    "available_str": "100.00",
                    "unit": "Days",
                    "status_label": "Available",
                    "color": "#16A34A",
                    "bg_color": "#DCFCE7",
                },
            ],
            "summary": {
                "total_quota": 302.0,
                "total_quota_str": "302.00",
                "total_used": 2.0,
                "total_used_str": "2",
                "total_available": 300.0,
                "total_available_str": "300.00",
                "leave_types_count": 2,
            },
            "error": None,
        }

        dialog = LeaveBalanceDialog(service=mock_service)
        dialog.refresh(async_mode=False)

        # Verify summary stats
        self.assertEqual(dialog.total_quota_val.text(), "302.00 Days")
        self.assertEqual(dialog.total_used_val.text(), "2 Days")
        self.assertEqual(dialog.total_avail_val.text(), "300.00 Days")

        # Verify cards created
        self.assertEqual(len(dialog._cards), 2)
        self.assertFalse(dialog.scroll_area.isHidden())
        self.assertTrue(dialog.empty_state.isHidden())

        # Card 0 (Casual Leave)
        card_0 = dialog._cards[0]
        self.assertEqual(card_0.name_label.text(), "Casual Leave")
        self.assertEqual(card_0._item["total_quota_str"], "202.00")
        self.assertEqual(card_0._item["used_str"], "2")
        self.assertEqual(card_0._item["available_str"], "200.00")

        # Card 1 (Sick Leave)
        card_1 = dialog._cards[1]
        self.assertEqual(card_1.name_label.text(), "Sick Leave")
        self.assertEqual(card_1._item["total_quota_str"], "100.00")
        self.assertEqual(card_1._item["used_str"], "0")
        self.assertEqual(card_1._item["available_str"], "100.00")

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
    def test_get_leave_quota_comma_separated_actual_api_response(self, mock_post):
        """Verify get_leave_quota correctly parses the actual comma-separated API response and maps 7 leave types by index."""
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

        # Index 0: ID 1 -> 202.00 / 2 / 200
        self.assertEqual(items[0]["leave_type_id"], "1")
        self.assertEqual(items[0]["total_quota_str"], "202.00")
        self.assertEqual(items[0]["used_str"], "2")
        self.assertEqual(items[0]["available_str"], "200")
        self.assertEqual(items[0]["short_name"], "LT1")

        # Index 1: ID 2 -> 100.00 / 0 / 100
        self.assertEqual(items[1]["leave_type_id"], "2")
        self.assertEqual(items[1]["total_quota_str"], "100.00")
        self.assertEqual(items[1]["used_str"], "0")
        self.assertEqual(items[1]["available_str"], "100")

        # Index 2: ID 3 -> 0.00 / 0 / 0
        self.assertEqual(items[2]["leave_type_id"], "3")
        self.assertEqual(items[2]["total_quota_str"], "0.00")
        self.assertEqual(items[2]["used_str"], "0")
        self.assertEqual(items[2]["available_str"], "0")

        # Index 3: ID 4 -> 133.34 / 1 / 132.34
        self.assertEqual(items[3]["leave_type_id"], "4")
        self.assertEqual(items[3]["total_quota_str"], "133.34")
        self.assertEqual(items[3]["used_str"], "1")
        self.assertEqual(items[3]["available_str"], "132.34")

        # Index 4: ID 5 -> 233.34 / 0.25 / 233.09
        self.assertEqual(items[4]["leave_type_id"], "5")
        self.assertEqual(items[4]["total_quota_str"], "233.34")
        self.assertEqual(items[4]["used_str"], "0.25")
        self.assertEqual(items[4]["available_str"], "233.09")

        # Index 5: ID 6 -> 203.00 / 3 / 200
        self.assertEqual(items[5]["leave_type_id"], "6")
        self.assertEqual(items[5]["total_quota_str"], "203.00")
        self.assertEqual(items[5]["used_str"], "3")
        self.assertEqual(items[5]["available_str"], "200")

        # Index 6: ID 7 -> 0 / 0 / 0
        self.assertEqual(items[6]["leave_type_id"], "7")
        self.assertEqual(items[6]["total_quota_str"], "0")
        self.assertEqual(items[6]["used_str"], "0")
        self.assertEqual(items[6]["available_str"], "0")

        # Summary check
        summary = res["summary"]
        self.assertAlmostEqual(summary["total_quota"], 871.68, places=2)
        self.assertAlmostEqual(summary["total_used"], 6.25, places=2)
        self.assertAlmostEqual(summary["total_available"], 865.43, places=2)
        self.assertEqual(summary["leave_types_count"], 7)

    def test_leave_balance_dialog_renders_all_7_cards_from_csv(self):
        """Verify LeaveBalanceDialog renders all 7 separate cards dynamically for 7 comma-separated leave types."""
        mock_service = MagicMock()
        mock_service.get_leave_quota.return_value = {
            "response": "Success",
            "status": 200,
            "items": [
                {"leave_type_id": "1", "leave_type": "Leave Type (ID: 1)", "short_name": "LT1", "total_quota": 202.0, "total_quota_str": "202.00", "used": 2.0, "used_str": "2", "available": 200.0, "available_str": "200"},
                {"leave_type_id": "2", "leave_type": "Leave Type (ID: 2)", "short_name": "LT2", "total_quota": 100.0, "total_quota_str": "100.00", "used": 0.0, "used_str": "0", "available": 100.0, "available_str": "100"},
                {"leave_type_id": "3", "leave_type": "Leave Type (ID: 3)", "short_name": "LT3", "total_quota": 0.0, "total_quota_str": "0.00", "used": 0.0, "used_str": "0", "available": 0.0, "available_str": "0"},
                {"leave_type_id": "4", "leave_type": "Leave Type (ID: 4)", "short_name": "LT4", "total_quota": 133.34, "total_quota_str": "133.34", "used": 1.0, "used_str": "1", "available": 132.34, "available_str": "132.34"},
                {"leave_type_id": "5", "leave_type": "Leave Type (ID: 5)", "short_name": "LT5", "total_quota": 233.34, "total_quota_str": "233.34", "used": 0.25, "used_str": "0.25", "available": 233.09, "available_str": "233.09"},
                {"leave_type_id": "6", "leave_type": "Leave Type (ID: 6)", "short_name": "LT6", "total_quota": 203.0, "total_quota_str": "203.00", "used": 3.0, "used_str": "3", "available": 200.0, "available_str": "200"},
                {"leave_type_id": "7", "leave_type": "Leave Type (ID: 7)", "short_name": "LT7", "total_quota": 0.0, "total_quota_str": "0", "used": 0.0, "used_str": "0", "available": 0.0, "available_str": "0"},
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

        # Check card 0 and card 6
        self.assertEqual(dialog._cards[0].name_label.text(), "Leave Type (ID: 1)")
        self.assertEqual(dialog._cards[6].name_label.text(), "Leave Type (ID: 7)")


if __name__ == "__main__":
    unittest.main()

