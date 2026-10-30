"""Unit and integration tests for Missed Punch and Leave Apply APIs and UI dialogs."""

import os
import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for UI tests
app = QApplication.instance()
if app is None:
    app = QApplication([])

from config.api_config import ApiConfig
from services.attendance_service import AttendanceService
from ui.apply_leave_dialog import ApplyLeaveDialog, DEFAULT_LEAVE_TYPES, DURATION_OPTIONS
from ui.attendance_page import AttendancePage
from ui.leave_balance_dialog import LeaveBalanceDialog
from services.session_service import SessionService, UserSession
from ui.missed_punch_dialog import MissedPunchDialog


class TestApiConfigEndpoints(unittest.TestCase):
    """Verify endpoint property resolution and environment variable overrides."""

    def setUp(self):
        self.cfg = ApiConfig()
        self.cfg.set_cached_configuration(
            company_code="TESTCO",
            base_url="https://hrms.test.com/api",
        )

    def test_mispunch_url_default_and_override(self):
        # Default endpoint
        expected_default = "https://hrms.test.com/api/Punch/mispunch"
        self.assertEqual(self.cfg.mispunch_url, expected_default)

        # Environment variable override
        override_url = "https://custom.server.com/api/v2/Punch/mispunch"
        with patch.dict(os.environ, {"IHRMS_MISPUNCH_API_URL": override_url}):
            self.assertEqual(self.cfg.mispunch_url, override_url)

    def test_apply_leave_url_default_and_override(self):
        # Default endpoint
        expected_default = "https://hrms.test.com/api/leave/apply_leave_v2"
        self.assertEqual(self.cfg.apply_leave_url, expected_default)

        # Environment variable override
        override_url = "https://custom.server.com/api/v2/leave/apply_leave_v2"
        with patch.dict(os.environ, {"IHRMS_APPLY_LEAVE_API_URL": override_url}):
            self.assertEqual(self.cfg.apply_leave_url, override_url)


class TestAttendanceServiceMissedPunch(unittest.TestCase):
    """Verify AttendanceService.submit_missed_punch functionality."""

    def setUp(self):
        self.service = AttendanceService()

    def test_date_normalization(self):
        # datetime object
        dt = datetime(2025, 7, 9, 10, 45, 4)
        self.assertEqual(self.service._normalize_api_date(dt), "09-07-2025")

        # date object
        d = date(2025, 7, 9)
        self.assertEqual(self.service._normalize_api_date(d), "09-07-2025")

        # QDate object
        qd = QDate(2025, 7, 9)
        self.assertEqual(self.service._normalize_api_date(qd), "09-07-2025")

        # YYYY-MM-DD string
        self.assertEqual(self.service._normalize_api_date("2025-07-09"), "09-07-2025")

        # DD-MM-YYYY string (already formatted)
        self.assertEqual(self.service._normalize_api_date("09-07-2025"), "09-07-2025")

    @patch("requests.post")
    def test_submit_missed_punch_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "status": 200,
            "message": "Missed punch request sent for approval.",
        }
        mock_resp.content = b'{"response":"Success"}'
        mock_post.return_value = mock_resp

        result = self.service.submit_missed_punch(
            date="2025-07-09",
            in_time="10:45:04",
            out_time="18:15:08",
            comments="Biometric punch missed due to reader offline",
            atten_id="ATT123",
            indo_code="EC-098",
            key="testapikey111",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], 200)
        self.assertIn("Missed punch request sent", result["message"])

        # Check payload delivered to requests.post
        call_args = mock_post.call_args
        sent_data = call_args[1].get("data")
        self.assertEqual(sent_data["key"], "testapikey111")
        self.assertEqual(sent_data["indo_code"], "EC-098")
        self.assertEqual(sent_data["date"], "09-07-2025")
        self.assertEqual(sent_data["in_time"], "10:45:04")
        self.assertEqual(sent_data["out_time"], "18:15:08")
        self.assertEqual(sent_data["comments"], "Biometric punch missed due to reader offline")
        self.assertEqual(sent_data["atten_id"], "ATT123")

    @patch("requests.post")
    def test_submit_missed_punch_406_retry_with_json(self, mock_post):
        # First call returns 406 Not Acceptable, second call succeeds
        resp_406 = MagicMock()
        resp_406.status_code = 406
        resp_406.content = b"Not acceptable"

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = {"status": 1, "message": "Punch submitted"}
        resp_ok.content = b'{"status": 1}'

        mock_post.side_effect = [resp_406, resp_ok]

        result = self.service.submit_missed_punch(
            date="09-07-2025",
            in_time="10:45:00",
            comments="Test 406 fallback",
            indo_code="EC-098",
            key="testapikey111",
        )

        self.assertTrue(result["success"])
        self.assertEqual(mock_post.call_count, 2)
        # Second call should use json payload
        second_call = mock_post.call_args_list[1]
        self.assertIn("json", second_call[1])

    def test_submit_missed_punch_validation(self):
        # Missing both in_time and out_time
        res = self.service.submit_missed_punch(
            date="09-07-2025",
            in_time="",
            out_time="",
            comments="Reason",
            indo_code="EC-098",
            key="testkey",
        )
        self.assertFalse(res["success"])
        self.assertIn("punch time", res["message"].lower())

        # Missing comments
        res2 = self.service.submit_missed_punch(
            date="09-07-2025",
            in_time="10:00:00",
            comments="   ",
            indo_code="EC-098",
            key="testkey",
        )
        self.assertFalse(res2["success"])
        self.assertIn("comments", res2["message"].lower())


class TestAttendanceServiceApplyLeave(unittest.TestCase):
    """Verify AttendanceService.apply_leave functionality."""

    def setUp(self):
        self.service = AttendanceService()

    @patch("requests.post")
    def test_apply_leave_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": "Success",
            "status": 200,
            "message": "Leave application submitted successfully.",
        }
        mock_resp.content = b'{"response":"Success"}'
        mock_post.return_value = mock_resp

        result = self.service.apply_leave(
            from_date="2026-06-11",
            to_date="2026-06-11",
            leave_type_id="4",
            duration_id="6",
            comments="Test Y-m-d format",
            indo_code="EC-100",
            key="testapikey111",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], 200)

        # Check payload matches screenshot specification
        sent_data = mock_post.call_args[1].get("data")
        self.assertEqual(sent_data["indo_code"], "EC-100")
        self.assertEqual(sent_data["key"], "testapikey111")
        self.assertEqual(sent_data["from_date"], "11-06-2026")
        self.assertEqual(sent_data["to_date"], "11-06-2026")
        self.assertEqual(sent_data["leave_type_id"], "4")
        self.assertEqual(sent_data["duration_id"], "6")
        self.assertEqual(sent_data["comments"], "Test Y-m-d format")

    @patch("requests.post")
    def test_apply_leave_clears_cache_on_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Success", "status": 200}
        mock_resp.content = b'{"response":"Success"}'
        mock_post.return_value = mock_resp

        # Populate fake cache
        self.service._leave_cache["EC-100_testkey"] = {"dummy": "cache"}
        self.service._leave_cache_ts["EC-100_testkey"] = 12345

        self.service.apply_leave(
            from_date="11-06-2026",
            to_date="11-06-2026",
            leave_type_id="4",
            duration_id="6",
            comments="Annual leave",
            indo_code="EC-100",
            key="testkey",
        )

        # Cache should be cleared for EC-100
        self.assertNotIn("EC-100_testkey", self.service._leave_cache)

    def test_apply_leave_validation(self):
        # Missing comments
        res = self.service.apply_leave(
            from_date="11-06-2026",
            to_date="11-06-2026",
            leave_type_id="4",
            comments="",
            indo_code="EC-100",
            key="testkey",
        )
        self.assertFalse(res["success"])
        self.assertIn("comments", res["message"].lower())

        # Missing leave_type_id
        res2 = self.service.apply_leave(
            from_date="11-06-2026",
            to_date="11-06-2026",
            leave_type_id="",
            comments="Vacation",
            indo_code="EC-100",
            key="testkey",
        )
        self.assertFalse(res2["success"])
        self.assertIn("leave type", res2["message"].lower())


class TestDialogUI(unittest.TestCase):
    """Verify MissedPunchDialog and ApplyLeaveDialog UI components."""

    def test_missed_punch_dialog_initialization_and_prefill(self):
        dialog = MissedPunchDialog(prefill_date="2025-07-09", atten_id="ATT-888")
        self.assertEqual(dialog.date_edit.date(), QDate(2025, 7, 9))
        self.assertEqual(dialog._atten_id, "ATT-888")
        self.assertTrue(dialog.in_time_cb.isChecked())
        self.assertTrue(dialog.out_time_cb.isChecked())
        self.assertTrue(dialog.submit_btn.isEnabled())
        self.assertTrue(dialog.close_btn.isEnabled())
        dialog.close()

    def test_missed_punch_dialog_displays_api_response_output(self):
        dialog = MissedPunchDialog(prefill_date="2025-07-09")
        dialog.show()
        # Simulate worker finished with actual API response
        mock_result = {
            "success": True,
            "status": 200,
            "message": "Missed punch request sent for approval.",
            "data": {
                "response": "Success",
                "request_id": "REQ-9988",
            },
        }
        dialog._on_submit_finished(mock_result)

        # Check that the API output section is visible and contains returned information
        self.assertFalse(dialog.api_output_group.isHidden())
        self.assertIn("Success", dialog.api_status_badge.text())
        self.assertEqual(dialog.api_message_label.text(), "Missed punch request sent for approval.")
        self.assertIn("Punch/mispunch", dialog.api_details_text.toPlainText())
        self.assertIn("REQ-9988", dialog.api_details_text.toPlainText())
        self.assertTrue(dialog.close_btn.isEnabled())
        dialog.close()

    def test_missed_punch_button_beside_today_in_attendance_page(self):
        page = AttendancePage()
        # Verify Today button exists
        self.assertTrue(hasattr(page, "today_btn"))
        self.assertEqual(page.today_btn.text(), "Today")

        # Verify Missed Punch button exists immediately beside Today
        self.assertTrue(hasattr(page, "missed_punch_btn"))
        self.assertEqual(page.missed_punch_btn.text(), "Missed Punch")

        # Verify tab order: today_btn -> missed_punch_btn
        self.assertEqual(page.today_btn.nextInFocusChain(), page.missed_punch_btn)
        page.close()

    def test_apply_leave_dialog_initialization_and_quota_binding(self):
        mock_quota_items = [
            {"leave_type_id": "4", "code": "OD", "name": "Business Trip", "available": 5.0},
            {"leave_type_id": "6", "code": "EL", "name": "Paid Leave", "available": 14.0},
        ]
        dialog = ApplyLeaveDialog(prefill_date="2026-06-11", quota_items=mock_quota_items)
        self.assertEqual(dialog.from_date_edit.date(), QDate(2026, 6, 11))
        self.assertEqual(dialog.to_date_edit.date(), QDate(2026, 6, 11))

        # Check combo box items populated from quota items
        self.assertEqual(dialog.leave_type_combo.count(), 2)
        self.assertEqual(dialog.leave_type_combo.itemData(0), "4")
        self.assertIn("Business Trip", dialog.leave_type_combo.itemText(0))

        # Test duration options
        self.assertEqual(dialog.duration_combo.count(), len(DURATION_OPTIONS))
        dialog.close()

    def test_apply_leave_dialog_half_day_locks_to_date(self):
        dialog = ApplyLeaveDialog(prefill_date="2026-06-11")
        # Change duration to First Half (id "1")
        idx = dialog.duration_combo.findData("1")
        dialog.duration_combo.setCurrentIndex(idx)

        # To Date should be synced and disabled
        self.assertEqual(dialog.to_date_edit.date(), dialog.from_date_edit.date())
        self.assertFalse(dialog.to_date_edit.isEnabled())

        # Change back to Full Day (id "6")
        idx_full = dialog.duration_combo.findData("6")
        dialog.duration_combo.setCurrentIndex(idx_full)
        self.assertTrue(dialog.to_date_edit.isEnabled())
        dialog.close()


    def test_apply_leave_button_beside_leave_balance_in_attendance_page(self):
        page = AttendancePage()
        self.assertTrue(hasattr(page, "leave_balance_button"))
        self.assertEqual(page.leave_balance_button.text(), "Leave Balance")
        self.assertTrue(hasattr(page, "apply_leave_button"))
        self.assertIn("Apply Leave", page.apply_leave_button.text())
        page.close()

    def test_apply_leave_header_button_in_leave_balance_dialog(self):
        dialog = LeaveBalanceDialog()
        self.assertTrue(hasattr(dialog, "title_label"))
        self.assertEqual(dialog.title_label.text(), "Leave Balance")
        self.assertTrue(hasattr(dialog, "apply_leave_header_btn"))
        self.assertIn("Apply Leave", dialog.apply_leave_header_btn.text())
        dialog.close()

    def test_apply_leave_dialog_displays_api_response_output(self):
        dialog = ApplyLeaveDialog(prefill_date="2026-06-11")
        dialog.show()
        mock_result = {
            "success": True,
            "status": 200,
            "message": "Leave application submitted successfully.",
            "data": {
                "response": "Success",
                "application_id": "LV-12345",
            },
        }
        dialog._on_submit_finished(mock_result)
        self.assertFalse(dialog.api_output_group.isHidden())
        self.assertIn("Success", dialog.api_status_badge.text())
        self.assertEqual(dialog.api_message_label.text(), "Leave application submitted successfully.")
        self.assertIn("leave/apply_leave_v2", dialog.api_details_text.toPlainText())
        self.assertIn("LV-12345", dialog.api_details_text.toPlainText())
        self.assertTrue(dialog.close_btn.isEnabled())
        dialog.close()


class TestMultiCompanyAndEmployeeIsolation(unittest.TestCase):
    """Verify dynamic multi-company and multi-employee context isolation."""

    def setUp(self):
        self.service = AttendanceService()
        self.session_service = SessionService()

    @patch("requests.post")
    def test_switching_companies_and_employees_updates_context_dynamically(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Success", "status": 200}
        mock_resp.content = b'{"response":"Success"}'
        mock_post.return_value = mock_resp

        # 1. Company Alpha - Employee 1
        user_a = UserSession(
            username="emp1@alpha.com",
            role="Employee",
            indo_code="EMP-ALPHA-01",
            api_key="token_alpha_01",
            company_code="ALPHA",
            base_url="https://alpha.api.ihrms.com/v1",
        )
        self.session_service._current_user = user_a

        self.service.submit_missed_punch(
            date="10-10-2026",
            in_time="09:00:00",
            comments="Alpha meeting",
        )
        call_alpha = mock_post.call_args
        self.assertEqual(call_alpha[0][0], "https://alpha.api.ihrms.com/v1/Punch/mispunch")
        self.assertEqual(call_alpha[1]["data"]["indo_code"], "EMP-ALPHA-01")
        self.assertEqual(call_alpha[1]["data"]["key"], "token_alpha_01")

        # 2. Company Beta - Employee 2 (Different company, different employee)
        user_b = UserSession(
            username="emp2@beta.com",
            role="Employee",
            indo_code="EMP-BETA-02",
            api_key="token_beta_02",
            company_code="BETA",
            base_url="https://beta.api.ihrms.com/v2",
        )
        self.session_service._current_user = user_b

        self.service.apply_leave(
            from_date="15-10-2026",
            to_date="16-10-2026",
            leave_type_id="2",
            duration_id="6",
            comments="Beta sick leave",
        )
        call_beta = mock_post.call_args
        self.assertEqual(call_beta[0][0], "https://beta.api.ihrms.com/v2/leave/apply_leave_v2")
        self.assertEqual(call_beta[1]["data"]["indo_code"], "EMP-BETA-02")
        self.assertEqual(call_beta[1]["data"]["key"], "token_beta_02")
        self.assertEqual(call_beta[1]["data"]["leave_type_id"], "2")

        # Reset session
        self.session_service._current_user = None


if __name__ == "__main__":
    unittest.main()
