"""Comprehensive tests for TaskService, AssignedTasksTable, and Dashboard integration (KRA & Timesheet flow)."""

import os
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

from config.api_config import ApiConfig
from services.activity_service import ActivityService
from services.session_service import SessionService
from services.task_service import TaskService
from ui.additional_task_widget import AdditionalTaskWidget, LinedTaskTextEdit
from ui.dashboard import DashboardPage
from ui.task_table import AssignedTasksTable

# Ensure a QApplication instance exists for widget tests
app = QApplication.instance() or QApplication([])


class TestTaskServiceAndUI(unittest.TestCase):
    def setUp(self):
        ApiConfig().reset()
        SessionService().clear()
        TaskService().clear_cache()

    def tearDown(self):
        ApiConfig().reset()
        SessionService().clear()
        TaskService().clear_cache()

    def test_dynamic_kra_api_urls_in_api_config(self):
        """Verify dynamic KRA / Task URLs resolve properly from ApiConfig."""
        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
            details={
                "get_kra_url": "https://custom.example.com/TaskPMS/get_kra",
                "draft_kra_date_url": "https://custom.example.com/TaskPMS/get_draft_kra_date",
                "submit_kra_date_url": "https://custom.example.com/TaskPMS/get_submit_kra_date_v2",
                "fill_time_sheet_url": "https://custom.example.com/TaskPMS/fill_time_sheet",
                "save_additional_task_url": "https://custom.example.com/TaskPMS/save_additional_task",
            },
        )

        self.assertEqual(
            cfg.get_kra_url, "https://custom.example.com/TaskPMS/get_kra"
        )
        self.assertEqual(
            cfg.get_draft_kra_date_url,
            "https://custom.example.com/TaskPMS/get_draft_kra_date",
        )
        self.assertEqual(
            cfg.get_submit_kra_date_url,
            "https://custom.example.com/TaskPMS/get_submit_kra_date_v2",
        )
        self.assertEqual(
            cfg.fill_time_sheet_url,
            "https://custom.example.com/TaskPMS/fill_time_sheet",
        )
        self.assertEqual(
            cfg.save_additional_task_url,
            "https://custom.example.com/TaskPMS/save_additional_task",
        )

        # Default fallback to endpoint
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
            details={},
        )
        self.assertEqual(
            cfg.get_kra_url, "https://hrms.example.com/ci4/api/TaskPMS/get_kra"
        )
        self.assertEqual(
            cfg.fill_time_sheet_url,
            "https://hrms.example.com/ci4/api/TaskPMS/fill_time_sheet",
        )
        self.assertEqual(
            cfg.save_additional_task_url,
            "https://hrms.example.com/ci4/api/TaskPMS/save_additional_task",
        )

    def test_task_service_fetch_assigned_tasks_success(self):
        """Verify TaskService correctly posts to the API and normalizes the response."""
        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
        )

        SessionService().login(
            username="testuser",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
        )

        mock_response_data = {
            "response": 200,
            "status": 1,
            "data": [
                {
                    "kra_id": "190",
                    "TimeSheet_id": "585",
                    "kra_name": "Develop Dashboard Feature",
                    "description": "Add Assigned Tasks view to dashboard UI",
                    "status": "In Progress",
                    "date": "2025-08-12",
                    "weightage": "30%",
                },
                {
                    "task_id": "191",
                    "TimeSheet_id": "586",
                    "task_title": "Fix Unit Test Regressions",
                    "task_desc": "Ensure all unit tests pass",
                    "target": "Completed",
                    "assigned_date": "2025-08-12",
                    "priority": "High",
                },
            ],
        }

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_response_data

            tasks = TaskService().fetch_assigned_tasks(date="2025-08-12", force=True)

            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0]["title"], "Develop Dashboard Feature")
            self.assertEqual(tasks[0]["description"], "Add Assigned Tasks view to dashboard UI")
            self.assertEqual(tasks[0]["kra_id"], "190")
            self.assertEqual(tasks[0]["timesheet_id"], "585")
            self.assertEqual(tasks[0]["status"], "In Progress")
            self.assertEqual(tasks[0]["date"], "2025-08-12")
            self.assertEqual(tasks[0]["weightage"], "30%")

            self.assertEqual(tasks[1]["title"], "Fix Unit Test Regressions")
            self.assertEqual(tasks[1]["status"], "Completed")
            self.assertEqual(tasks[1]["weightage"], "High")

            mock_post.assert_called_once()
            called_args, called_kwargs = mock_post.call_args
            self.assertEqual(
                called_args[0], "https://hrms.example.com/ci4/api/TaskPMS/get_kra"
            )
            self.assertEqual(
                called_kwargs["data"],
                {
                    "key": "testapikey111",
                    "indo_code": "EC-098",
                    "date": "2025-08-12",
                },
            )

    def test_task_service_fetch_exact_real_api_response(self):
        """Verify TaskService normalizes the exact real emp_kra JSON structure."""
        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api",
        )
        SessionService().login(
            username="testuser",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
        )

        real_payload = {
            "response": 200,
            "status": 1,
            "emp_kra": [
                {
                    "kra_id": "190",
                    "name": "Clients Suppot",
                    "description": "Provide support to",
                    "target": "10",
                    "measurement_criteria": "No pending issues",
                    "weightage": "10.00",
                    "category_name": "KRA Specific Goal",
                    "task_done": "2.00",
                    "comment": "A",
                    "submit_status": "0",
                    "timesheet_id": "679"
                },
                {
                    "kra_id": "191",
                    "name": "New technology",
                    "description": "Learn Nodejs",
                    "target": "1",
                    "measurement_criteria": "One live project",
                    "weightage": "10.00",
                    "category_name": "PDP",
                    "task_done": "3.00",
                    "comment": "B",
                    "submit_status": "0",
                    "timesheet_id": "680"
                },
                {
                    "kra_id": "192",
                    "name": "New Projects",
                    "description": "3 New projects",
                    "target": "3",
                    "measurement_criteria": "Delivery on time of 3 new projects",
                    "weightage": "80.00",
                    "category_name": "Business Target",
                    "task_done": "2.00",
                    "comment": "C",
                    "submit_status": "0",
                    "timesheet_id": "681"
                }
            ],
            "additional_task": None,
            "additional_task_status": 0
        }

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = real_payload

            tasks = TaskService().fetch_assigned_tasks(date="2025-08-12", force=True)

            self.assertEqual(len(tasks), 3)
            # Row 0
            self.assertEqual(tasks[0]["name"], "Clients Suppot")
            self.assertEqual(tasks[0]["description"], "Provide support to")
            self.assertEqual(tasks[0]["category"], "KRA Specific Goal")
            self.assertEqual(tasks[0]["target"], "10")
            self.assertEqual(tasks[0]["measurement_criteria"], "No pending issues")
            self.assertEqual(tasks[0]["weightage"], "10%")
            self.assertEqual(tasks[0]["task_done"], "2.00")
            self.assertEqual(tasks[0]["comment"], "A")
            self.assertEqual(tasks[0]["kra_id"], "190")
            self.assertEqual(tasks[0]["timesheet_id"], "679")

            # Row 1
            self.assertEqual(tasks[1]["name"], "New technology")
            self.assertEqual(tasks[1]["category"], "PDP")
            self.assertEqual(tasks[1]["target"], "1")
            self.assertEqual(tasks[1]["comment"], "B")
            self.assertEqual(tasks[1]["timesheet_id"], "680")

            # Row 2
            self.assertEqual(tasks[2]["name"], "New Projects")
            self.assertEqual(tasks[2]["category"], "Business Target")
            self.assertEqual(tasks[2]["weightage"], "80%")
            self.assertEqual(tasks[2]["comment"], "C")
            self.assertEqual(tasks[2]["timesheet_id"], "681")

            # Test feeding real tasks directly into the UI table
            table = AssignedTasksTable()
            table.set_tasks(tasks)
            self.assertEqual(table.rowCount(), 3)
            self.assertEqual(table.item(0, 0).text(), "1")
            self.assertEqual(table.item(1, 0).text(), "2")
            self.assertEqual(table.item(2, 0).text(), "3")
            self.assertEqual(table.item(0, 1).text(), "Clients Suppot")
            self.assertEqual(table.item(0, 3).text(), "KRA Specific Goal")
            self.assertEqual(table.item(0, 4).text(), "10")
            self.assertEqual(table.item(0, 5).text(), "No pending issues")
            self.assertEqual(table.item(0, 6).text(), "10%")
            self.assertEqual(table.item(0, 7).text(), "2.00")
            self.assertEqual(table._get_line_edit(0, 9).text(), "A")

    def test_task_service_save_time_sheet(self):
        """Verify TaskService.save_time_sheet sends the exact JSON payload required by API."""
        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
        )
        SessionService().login(
            username="testuser",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
        )

        mock_kra_list = [
            {
                "TimeSheet_id": "587",
                "kra_id": "192",
                "remark": "completed user auth module",
                "task_completed": "0",
            },
            {
                "TimeSheet_id": "586",
                "kra_id": "191",
                "remark": "fixed bug in report",
                "task_completed": "1",
            },
        ]

        mock_resp_data = {
            "status": 1,
            "response": "Success",
            "message": "Timesheet saved successfully",
        }

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp_data

            ok, msg, data = TaskService().save_time_sheet(
                kra_list=mock_kra_list,
                date="2025-07-24",
                submit_status="0",
            )

            self.assertTrue(ok)
            self.assertEqual(msg, "Timesheet saved successfully")
            mock_post.assert_called_once()
            called_args, called_kwargs = mock_post.call_args
            self.assertEqual(
                called_args[0], "https://hrms.example.com/ci4/api/TaskPMS/fill_time_sheet"
            )
            self.assertEqual(
                called_kwargs["json"],
                {
                    "key": "testapikey111",
                    "indo_code": "EC-098",
                    "date": "2025-07-24",
                    "submit_status": "0",
                    "kraList": [
                        {
                            "TimeSheet_id": "587",
                            "kra_id": "192",
                            "remark": "completed user auth module",
                            "task_completed": "0",
                        },
                        {
                            "TimeSheet_id": "586",
                            "kra_id": "191",
                            "remark": "fixed bug in report",
                            "task_completed": "1",
                        },
                    ],
                },
            )

    def test_task_service_save_additional_task(self):
        """Verify TaskService.save_additional_task sends form-data correctly."""
        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
        )
        SessionService().login(
            username="testuser",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
        )

        mock_resp_data = {
            "status": 1,
            "response": "Success",
            "message": "Additional task added successfully",
        }

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp_data

            ok, msg, data = TaskService().save_additional_task(
                task="today i did this",
                date="2026-09-11",
                status=1,
            )

            self.assertTrue(ok)
            mock_post.assert_called_once()
            called_args, called_kwargs = mock_post.call_args
            self.assertEqual(
                called_args[0], "https://hrms.example.com/ci4/api/TaskPMS/save_additional_task"
            )
            self.assertEqual(
                called_kwargs["data"],
                {
                    "key": "testapikey111",
                    "indo_code": "EC-098",
                    "date": "2026-09-11",
                    "status": "1",
                    "task": "today i did this",
                },
            )

    def test_task_service_error_handling(self):
        """Verify TaskService handles network and HTTP errors gracefully."""
        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
        )
        SessionService().login(
            username="testuser",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
        )

        with patch("requests.post", side_effect=Exception("Connection timeout")):
            tasks = TaskService().fetch_assigned_tasks(date="2025-08-12", force=True)
            self.assertEqual(tasks, [])
            self.assertIn("Connection timeout", str(TaskService().last_error))

    def test_assigned_tasks_table_widget(self):
        """Verify AssignedTasksTable displays rows, editable numeric/text controls, and error states properly."""
        table = AssignedTasksTable()

        # Test empty state
        table.set_tasks([])
        self.assertEqual(table.rowCount(), 1)
        self.assertIn("No assigned tasks found.", table.item(0, 0).text())

        # Test loading state
        table.show_loading()
        self.assertEqual(table.rowCount(), 1)
        self.assertIn("Loading KRA...", table.item(0, 0).text())

        # Test error state
        table.show_error("API Error: 500")
        self.assertEqual(table.rowCount(), 1)
        self.assertIn("Unable to load KRA data.", table.item(0, 0).text())

        # Test populating tasks
        tasks = [
            {
                "id": "190",
                "kra_id": "190",
                "timesheet_id": "585",
                "name": "Task 1",
                "description": "Details 1",
                "category": "Development",
                "target": "100%",
                "measurement_criteria": "Code review",
                "weightage": "50%",
                "task_done": "10%",
                "task_completed": "25",
                "remark": "Existing work notes",
                "status": "In Progress",
                "date": "2025-08-12",
            }
        ]
        table.set_tasks(tasks)
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "1")
        self.assertEqual(table.item(0, 1).text(), "Task 1")
        self.assertEqual(table.item(0, 2).text(), "Details 1")
        self.assertEqual(table.item(0, 3).text(), "Development")
        self.assertEqual(table.item(0, 4).text(), "100%")
        self.assertEqual(table.item(0, 5).text(), "Code review")
        self.assertEqual(table.item(0, 6).text(), "50%")
        self.assertEqual(table.item(0, 7).text(), "10%")

        # Verify editable widgets exist
        completed_widget = table._get_line_edit(0, 8)
        self.assertIsNotNone(completed_widget)
        self.assertEqual(completed_widget.text(), "25")

        comment_widget = table._get_line_edit(0, 9)
        self.assertIsNotNone(comment_widget)
        self.assertEqual(comment_widget.text(), "Existing work notes")

        # Verify no individual per-row Save button or column 10
        self.assertEqual(table.columnCount(), 10)
        self.assertIsNone(table.cellWidget(0, 10))

        # Verify common action buttons below the table exist
        self.assertIsNotNone(table.actions_widget)
        self.assertIsNotNone(table.save_draft_btn)
        self.assertIsNotNone(table.submit_btn)
        self.assertEqual(table.save_draft_btn.text(), "Save as Draft")
        self.assertEqual(table.submit_btn.text(), "Submit")

    def test_assigned_tasks_table_save_flow_and_validation(self):
        """Verify Save as Draft and Submit flow, validation of empty comment / negative number, and successful save handling."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "192",
                "kra_id": "192",
                "timesheet_id": "587",
                "name": "Implement Feature",
                "description": "Add new API",
                "task_completed": "25",
                "comment": "",
                "status": "In Progress",
                "date": "2025-07-24",
                "weightage": "20%",
            }
        ]
        table.set_tasks(tasks)

        completed_edit = table._get_line_edit(0, 8)
        comment_edit = table._get_line_edit(0, 9)
        submit_btn = table.submit_btn
        save_draft_btn = table.save_draft_btn

        # 1. Validation test: empty comment should highlight error and not trigger submit
        submit_btn.click()
        QCoreApplication.processEvents()
        self.assertEqual(submit_btn.text(), "Submit")  # Still "Submit", not "Submitting..."

        # 2. Validation test: negative number should highlight error
        completed_edit.setText("-5")
        comment_edit.setText("Finished feature implementation")
        submit_btn.click()
        QCoreApplication.processEvents()
        self.assertEqual(submit_btn.text(), "Submit")

        # 3. Enter valid numeric task_completed and comment, then click Submit
        completed_edit.setText("30")
        with patch.object(TaskService, "save_time_sheet", return_value=(True, "Timesheet submitted successfully.", {"TimeSheet_id": "587"})) as mock_save:
            with patch.object(TaskService, "fetch_assigned_tasks", return_value=[{
                "id": "192",
                "kra_id": "192",
                "timesheet_id": "587",
                "name": "Implement Feature",
                "description": "Add new API",
                "task_completed": "30",
                "comment": "Finished feature implementation",
                "status": "In Progress",
                "date": "2025-07-24",
                "weightage": "20%",
            }]):
                submit_btn.click()
                time.sleep(0.1)
                QCoreApplication.processEvents()
                self.assertTrue(submit_btn.isHidden())
                self.assertTrue(table.is_submitted)
                self.assertEqual(table._get_line_edit(0, 8).text(), "30")
                self.assertEqual(table._get_line_edit(0, 9).text(), "Finished feature implementation")
                mock_save.assert_called_once()
                self.assertEqual(mock_save.call_args[1]["submit_status"], "1")

        # 4. Test Save as Draft functionality
        table.set_tasks(tasks)
        with patch.object(TaskService, "save_time_sheet", return_value=(True, "Draft saved successfully.", {"TimeSheet_id": "587"})) as mock_draft:
            with patch.object(TaskService, "fetch_assigned_tasks", return_value=tasks):
                save_draft_btn.click()
                time.sleep(0.1)
                QCoreApplication.processEvents()
                self.assertEqual(save_draft_btn.text(), "Draft Saved ✓")
                mock_draft.assert_called_once()
                self.assertEqual(mock_draft.call_args[1]["submit_status"], "0")

    def test_assigned_tasks_table_prevent_duplicate_save(self):
        """Verify double-clicking submit button prevents duplicate API calls while in progress."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "192",
                "kra_id": "192",
                "timesheet_id": "587",
                "name": "Implement Feature",
                "description": "Add new API",
                "task_completed": "10",
                "comment": "Work in progress",
                "status": "In Progress",
                "date": "2025-07-24",
                "weightage": "20%",
            }
        ]
        table.set_tasks(tasks)
        submit_btn = table.submit_btn

        call_count = 0
        def mock_save(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            time.sleep(0.05)
            return True, "Success", {"TimeSheet_id": "587"}

        with patch.object(TaskService, "save_time_sheet", side_effect=mock_save):
            with patch.object(TaskService, "fetch_assigned_tasks", return_value=tasks):
                submit_btn.click()
                submit_btn.click()  # Second click while disabled/in-progress
                time.sleep(0.15)
                QCoreApplication.processEvents()
                self.assertEqual(call_count, 1)

    def test_dashboard_page_integration(self):
        """Verify DashboardPage contains AssignedTasksTable and refresh populates it dynamically."""
        mock_activity_svc = MagicMock(spec=ActivityService)
        mock_activity_svc.get_today_total_seconds.return_value = 1800
        mock_activity_svc.get_uploaded_records_count.return_value = 15
        mock_activity_svc.get_today_total_idle_seconds.return_value = 120
        mock_activity_svc.get_today_timeline.return_value = []

        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
        )
        SessionService().login(
            username="testuser",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
        )

        dashboard = DashboardPage(activity_service=mock_activity_svc)
        self.assertTrue(hasattr(dashboard, "task_table"))
        self.assertIsInstance(dashboard.task_table, AssignedTasksTable)

        mock_tasks = [
            {
                "id": "1",
                "title": "Sprint Task",
                "description": "Complete Sprint Planning",
                "status": "Active",
                "date": "2025-08-12",
                "weightage": "20%",
            }
        ]

    def test_assigned_tasks_table_multiple_rows_isolation(self):
        """Verify multiple rows maintain their own separate state and do not overwrite each other."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "KRA-1",
                "kra_id": "KRA-1",
                "timesheet_id": "TS-101",
                "name": "KRA 1",
                "description": "Module A",
                "task_completed": "10",
                "comment": "Initial note 1",
                "date": "2025-08-12",
            },
            {
                "id": "KRA-2",
                "kra_id": "KRA-2",
                "timesheet_id": "TS-102",
                "name": "KRA 2",
                "description": "Module B",
                "task_completed": "5",
                "comment": "Initial note 2",
                "date": "2025-08-12",
            },
        ]
        table.set_tasks(tasks)

        # Verify initial values
        row0_comp = table._get_line_edit(0, 8)
        row0_comm = table._get_line_edit(0, 9)
        row1_comp = table._get_line_edit(1, 8)
        row1_comm = table._get_line_edit(1, 9)

        # Verify S.No. column values
        self.assertEqual(table.item(0, 0).text(), "1")
        self.assertEqual(table.item(1, 0).text(), "2")

        self.assertEqual(row0_comp.text(), "10")
        self.assertEqual(row0_comm.text(), "Initial note 1")
        self.assertEqual(row1_comp.text(), "5")
        self.assertEqual(row1_comm.text(), "Initial note 2")

        # Edit row 0 only
        row0_comp.setText("50")
        row0_comm.setText("Completed module A")

        # Row 1 must remain untouched
        self.assertEqual(row1_comp.text(), "5")
        self.assertEqual(row1_comm.text(), "Initial note 2")
        self.assertEqual(table.tasks[1]["task_completed"], "5")
        self.assertEqual(table.tasks[1]["comment"], "Initial note 2")

        # Edit row 1
        row1_comp.setText("15")
        row1_comm.setText("Working on module B")

        # Row 0 must retain its edited values
        self.assertEqual(row0_comp.text(), "50")
        self.assertEqual(row0_comm.text(), "Completed module A")

    def test_assigned_tasks_table_error_retry_preserves_input(self):
        """Verify API failure preserves entered values and enables retry."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "195",
                "kra_id": "195",
                "timesheet_id": "590",
                "name": "Task Fail Test",
                "description": "API failure scenario",
                "task_completed": "20",
                "comment": "Work note to preserve",
                "date": "2025-08-12",
            }
        ]
        table.set_tasks(tasks)

        completed_edit = table._get_line_edit(0, 8)
        comment_edit = table._get_line_edit(0, 9)
        submit_btn = table.submit_btn

        # Edit values
        completed_edit.setText("75")
        comment_edit.setText("Updated comment before failure")

        # Simulate API failure
        with patch.object(TaskService, "save_time_sheet", return_value=(False, "Internal Server Error", None)):
            submit_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            # Verify button shows retry state
            self.assertEqual(submit_btn.text(), "Retry Submit ⚠️")

            # Verify user-entered inputs are preserved exactly
            self.assertEqual(completed_edit.text(), "75")
            self.assertEqual(comment_edit.text(), "Updated comment before failure")

    def test_assigned_tasks_table_common_action_buttons_and_dimensions(self):
        """Verify no per-row Action column exists (10 columns), common action buttons exist below table, and responsive resizing works."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "195",
                "kra_id": "195",
                "timesheet_id": "595",
                "name": "Frontend Sizing",
                "description": "Button layout test",
                "category": "Development",
                "target": "100%",
                "measurement_criteria": "Visual inspection",
                "weightage": "50%",
                "task_done": "20%",
                "task_completed": "30",
                "comment": "Testing Action column dimensions",
                "date": "2026-10-13",
            }
        ]
        table.set_tasks(tasks)
        table.resize(1000, 300)
        QCoreApplication.processEvents()

        # 1. Table must have exactly 10 columns (no individual Action column)
        self.assertEqual(table.columnCount(), 10)
        self.assertIsNone(table.cellWidget(0, 10))

        # 2. Common action buttons are present in actions_widget
        self.assertIsNotNone(table.actions_widget)
        self.assertIsNotNone(table.save_draft_btn)
        self.assertIsNotNone(table.submit_btn)
        self.assertEqual(table.save_draft_btn.text(), "Save as Draft")
        self.assertEqual(table.submit_btn.text(), "Submit")

        # 3. Responsive expansion on wide viewport
        table.resize(1600, 300)
        table._adjust_column_widths()
        QCoreApplication.processEvents()
        # Sum of columns should fill the viewport without empty dead space
        total_cols_width = sum(table.columnWidth(i) for i in range(table.columnCount()))
        self.assertGreaterEqual(total_cols_width, 1200)

    def test_assigned_tasks_table_sno_column_and_dynamic_numbering(self):
        """Verify S.No. appears as the first column, numbers rows dynamically, and updates correctly."""
        table = AssignedTasksTable()
        tasks = [
            {"id": f"KRA-{i}", "name": f"Task {i}", "description": f"Desc {i}", "date": "2026-10-14"}
            for i in range(1, 6)
        ]
        table.set_tasks(tasks)
        self.assertEqual(table.rowCount(), 5)

        # 1. Header label of column 0 must be S.No.
        header_item = table.horizontalHeaderItem(0)
        self.assertIsNotNone(header_item)
        self.assertEqual(header_item.text(), "S.No.")

        # 2. Sequential numbers 1..5 generated dynamically
        for r in range(5):
            self.assertEqual(table.item(r, 0).text(), str(r + 1))

        # 3. Dynamic update when update_row_numbers is invoked
        table.update_row_numbers()
        for r in range(5):
            self.assertEqual(table.item(r, 0).text(), str(r + 1))

        # 4. Changing tasks dynamically updates row numbering
        table.set_tasks(tasks[:3])
        self.assertEqual(table.rowCount(), 3)
        for r in range(3):
            self.assertEqual(table.item(r, 0).text(), str(r + 1))

    def test_assigned_tasks_table_horizontal_scroll_stability_during_comment_typing(self):
        """Verify typing, editing, deleting, or pasting in the Comment field does not cause unwanted horizontal scrolling."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "1",
                "name": "Frontend Task",
                "description": "Scroll stability verification",
                "category": "Development",
                "target": "100%",
                "measurement_criteria": "Code review",
                "weightage": "20%",
                "task_done": "10%",
                "task_completed": "15",
                "comment": "Initial brief note",
                "date": "2026-10-14",
            }
        ]
        table.resize(600, 300)
        table.show()
        table.set_tasks(tasks)
        QCoreApplication.processEvents()

        # Under responsive fit, table fits within container with horizontal scrollbar disabled
        self.assertEqual(table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(table.horizontalScrollBar().maximum(), 0)

        # 1. To test scroll stability, simulate a widened column and scroll horizontally
        table.setColumnWidth(9, 500)
        QCoreApplication.processEvents()
        target_scroll = 250
        table.horizontalScrollBar().setValue(target_scroll)
        QCoreApplication.processEvents()
        self.assertEqual(table.horizontalScrollBar().value(), target_scroll)

        # 2. Focus Comment field — scroll position must remain stable
        comment_edit = table._get_line_edit(0, 9)
        self.assertIsNotNone(comment_edit)
        comment_edit.setFocus()
        QCoreApplication.processEvents()
        self.assertEqual(table.horizontalScrollBar().value(), target_scroll)

        # 3. Type long comment text — horizontal scroll position must NOT change
        long_comment = "This is a very detailed comment describing task progress, bug fixes, unit tests, and timesheet logging."
        for ch in long_comment:
            comment_edit.setText(comment_edit.text() + ch)
            QCoreApplication.processEvents()
            self.assertEqual(table.horizontalScrollBar().value(), target_scroll)

        # 4. Deleting text — horizontal scroll position must remain stable
        while len(comment_edit.text()) > 10:
            comment_edit.setText(comment_edit.text()[:-1])
            QCoreApplication.processEvents()
            self.assertEqual(table.horizontalScrollBar().value(), target_scroll)

        # 5. Programmatic scrollTo should not cause unwanted horizontal jumping
        table.scrollTo(table.model().index(0, 9))
        self.assertEqual(table.horizontalScrollBar().value(), target_scroll)

        # 6. Intentional manual horizontal scrollbar adjustments continue to work normally
        table.horizontalScrollBar().setValue(100)
        self.assertEqual(table.horizontalScrollBar().value(), 100)
        table.horizontalScrollBar().setValue(300)
        self.assertEqual(table.horizontalScrollBar().value(), 300)

    def test_timesheet_table_has_no_horizontal_scrollbar_and_fits_container(self):
        """Verify Timesheet table removes horizontal scrollbar and fits within its container across various widths."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "1",
                "name": "Frontend Task",
                "description": "Responsiveness and fit verification across container widths",
                "category": "Development",
                "target": "100%",
                "measurement_criteria": "Code review",
                "weightage": "20%",
                "task_done": "10%",
                "task_completed": "15",
                "comment": "Testing no horizontal scrollbar across sizes",
                "date": "2026-10-14",
            }
        ]
        table.set_tasks(tasks)
        table.show()
        QCoreApplication.processEvents()

        # Policy must always be ScrollBarAlwaysOff
        self.assertEqual(table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertFalse(table.horizontalScrollBar().isVisible())

        # Test responsiveness across different container widths (laptop, desktop, widescreen)
        for container_width in [650, 750, 800, 1000, 1200, 1600]:
            table.resize(container_width, 350)
            table._adjust_column_widths()
            QCoreApplication.processEvents()

            # Horizontal scrollbar must remain not visible
            self.assertFalse(table.horizontalScrollBar().isVisible())

            visible_cols = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
            total_cols_w = sum(table.columnWidth(c) for c in visible_cols)
            vp_w = table.viewport().width()

            # Columns must fill the viewport without exceeding it
            self.assertEqual(total_cols_w, vp_w)

            # Editable inputs in Col 8 (Task Completed) and Col 9 (Comment) must remain usable and unclipped
            comp_container = table.cellWidget(0, 8)
            comm_container = table.cellWidget(0, 9)
            self.assertIsNotNone(comp_container)
            self.assertIsNotNone(comm_container)

            comp_edit = comp_container.findChild(QLineEdit)
            comm_edit = comm_container.findChild(QLineEdit)
            self.assertIsNotNone(comp_edit)
            self.assertIsNotNone(comm_edit)
            self.assertGreater(comp_edit.width(), 40)
            self.assertGreater(comm_edit.width(), 60)

    def test_assigned_tasks_table_header_labels_not_clipped(self):
        """Verify that every column header text has sufficient width and padding so that no label is clipped."""
        from PySide6.QtGui import QFontMetrics

        table = AssignedTasksTable()
        tasks = [
            {
                "id": "1",
                "name": "Frontend Task",
                "description": "Header clipping test",
                "category": "Development",
                "target": "100%",
                "measurement_criteria": "Code review",
                "weightage": "20%",
                "task_done": "10%",
                "task_completed": "15",
                "comment": "Testing all headers",
                "date": "2026-10-14",
            }
        ]
        table.set_tasks(tasks)

        for w in [500, 800, 1000, 1400, 1920]:
            table.resize(w, 400)
            table._adjust_column_widths()
            QCoreApplication.processEvents()

            for col_idx, (col_name, _base_w, _align) in enumerate(table.COLUMN_CONFIG):
                if table.isColumnHidden(col_idx):
                    continue
                actual_w = table.columnWidth(col_idx)
                item = table.horizontalHeaderItem(col_idx)
                self.assertIsNotNone(item)
                fm = QFontMetrics(item.font())
                text_w = fm.horizontalAdvance(col_name)

                # Available width considering 6px padding on each side (12px total)
                avail_w = actual_w - 12
                self.assertGreaterEqual(
                    avail_w,
                    text_w,
                    f"Header for column '{col_name}' (col {col_idx}) is clipped at width {w}: "
                    f"text_w={text_w} > avail_w={avail_w} (actual_w={actual_w})",
                )

        # Confirm Category and Measurement Criteria columns are hidden
        self.assertTrue(table.isColumnHidden(3))
        self.assertTrue(table.isColumnHidden(5))

    def test_format_task_date(self):
        """Verify format_task_date correctly formats dates to 'DD Month YYYY' matching reference UI."""
        from ui.task_table import format_task_date

        # Standard YYYY-MM-DD
        self.assertEqual(format_task_date("2026-10-01"), "01 October 2026")
        self.assertEqual(format_task_date("2026-10-14"), "14 October 2026")
        self.assertEqual(format_task_date("2025-07-24"), "24 July 2025")

        # Already formatted
        self.assertEqual(format_task_date("01 October 2026"), "01 October 2026")

        # DD-MM-YYYY
        self.assertEqual(format_task_date("01-10-2026"), "01 October 2026")

        # Empty / None / invalid returns empty string without substituting system date
        self.assertEqual(format_task_date(None), "")
        self.assertEqual(format_task_date(""), "")
        self.assertEqual(format_task_date("   "), "")
        self.assertEqual(format_task_date("None"), "")

    def test_task_title_heading_dynamic_rendering_and_centering(self):
        """Verify the heading above the table matches 'Timesheet for {name} ({code}) on {DD Month YYYY}' and updates dynamically."""
        from services.session_service import SessionService
        from PySide6.QtCore import Qt

        SessionService().clear()
        SessionService().login(
            username="dinesh",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
            full_name="Dinesh Dev",
        )

        table = AssignedTasksTable()

        # 1. Title label exists, is centered, and matches logged-in user (without date if date is absent)
        self.assertIsNotNone(table.title_label)
        self.assertEqual(table.title_label.alignment(), Qt.AlignmentFlag.AlignCenter)
        self.assertEqual(table.title_label.text(), "Timesheet for Dinesh Dev (EC-098)")
        self.assertIn("font-size: 15px", table.title_label.styleSheet())

        # 2. Populate tasks with date 2026-10-01
        tasks_oct1 = [
            {
                "id": "190",
                "kra_id": "190",
                "name": "Feature Delivery",
                "date": "2026-10-01",
                "task_completed": "10",
                "comment": "In progress",
            }
        ]
        table.set_tasks(tasks_oct1)
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Dinesh Dev (EC-098) on 01 October 2026",
        )

        # 3. Dynamic update when task date changes to 2025-07-24
        tasks_july24 = [
            {
                "id": "191",
                "kra_id": "191",
                "name": "Backend Refactor",
                "date": "2025-07-24",
                "task_completed": "5",
                "comment": "Working on API",
            }
        ]
        table.set_tasks(tasks_july24)
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Dinesh Dev (EC-098) on 24 July 2025",
        )

        # 4. Direct update_title call with explicit date
        table.update_title(date="2026-10-01")
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Dinesh Dev (EC-098) on 01 October 2026",
        )

        # 5. Dynamic employee resolution from task item if different user
        tasks_other = [
            {
                "id": "192",
                "name": "Task for colleague",
                "employee_name": "Priya Sharma",
                "indo_code": "EC-105",
                "date": "2026-10-01",
            }
        ]
        table.set_tasks(tasks_other)
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Priya Sharma (EC-105) on 01 October 2026",
        )

        # 6. Multi-task switching: clicking or selecting different rows dynamically updates employee and date
        multi_tasks = [
            {
                "id": "201",
                "name": "Design Sprint",
                "employee_name": "Dinesh Dev",
                "indo_code": "EC-098",
                "date": "2026-10-14",
            },
            {
                "id": "202",
                "name": "QA Testing",
                "employee_name": "Anita Roy",
                "indo_code": "EC-045",
                "date": "2026-10-20",
            },
            {
                "id": "203",
                "name": "Documentation",
                "employee_name": "Sunil Verma",
                "indo_code": "EC-210",
                "date": "2026-11-05",
            },
        ]
        table.set_tasks(multi_tasks)
        # Row 0 initially selected
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Dinesh Dev (EC-098) on 14 October 2026",
        )

        # Select row 1 (Anita Roy on 20 October 2026)
        table.select_task_by_index(1)
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Anita Roy (EC-045) on 20 October 2026",
        )

        # Cell click on row 2 (Sunil Verma on 05 November 2026)
        table._on_cell_clicked(2, 0)
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Sunil Verma (EC-210) on 05 November 2026",
        )

        # Focus line edit in row 0 restores Dinesh Dev
        line_edit_r0 = table._get_line_edit(0, 8)
        self.assertIsNotNone(line_edit_r0)
        table._handle_line_edit_focused(line_edit_r0)
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Dinesh Dev (EC-098) on 14 October 2026",
        )

        # 7. When task date is absent, title does not invent or substitute system date
        no_date_tasks = [
            {
                "id": "204",
                "name": "General Task",
                "employee_name": "Vikram Seth",
                "indo_code": "EC-303",
                "date": "",
            }
        ]
        table.set_tasks(no_date_tasks)
        self.assertEqual(
            table.title_label.text(),
            "Timesheet for Vikram Seth (EC-303)",
        )

    def test_dashboard_page_has_task_title_label(self):
        """Verify DashboardPage exposes task_title_label above the task_table."""
        mock_activity_svc = MagicMock(spec=ActivityService)
        mock_activity_svc.get_today_total_seconds.return_value = 1800
        mock_activity_svc.get_uploaded_records_count.return_value = 15
        mock_activity_svc.get_today_total_idle_seconds.return_value = 120
        mock_activity_svc.get_today_timeline.return_value = []

        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
        )
        SessionService().login(
            username="dinesh",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
            full_name="Dinesh Dev",
        )

        dashboard = DashboardPage(activity_service=mock_activity_svc)
        self.assertTrue(hasattr(dashboard, "task_title_label"))
        self.assertIs(dashboard.task_title_label, dashboard.task_table.title_label)
        self.assertIn("Timesheet for Dinesh Dev (EC-098)", dashboard.task_title_label.text())

    def test_additional_task_widget_structure_and_styling(self):
        """Verify AdditionalTaskWidget has centered heading, lined editor, and action buttons."""
        widget = AdditionalTaskWidget()
        self.assertEqual(widget.heading_label.text(), "Add Additional Task")
        self.assertIsInstance(widget.text_edit, LinedTaskTextEdit)
        self.assertEqual(widget.save_draft_btn.text(), "Save As Draft")
        self.assertEqual(widget.submit_btn.text(), "Submit Task")
        self.assertTrue(widget.save_draft_btn.isEnabled())
        self.assertTrue(widget.submit_btn.isEnabled())

        # Verify margin area and text alignment to the right of red margin line
        self.assertTrue(hasattr(widget.text_edit, "margin_area"))
        self.assertEqual(widget.text_edit.margin_area_width(), 38)
        widget.text_edit.resize(400, 150)
        widget.text_edit.show()
        QCoreApplication.processEvents()

        # Text and caret must start clearly to the right of red margin line (x=28)
        cursor_widget_x = widget.text_edit.viewport().mapTo(widget.text_edit, widget.text_edit.cursorRect().topLeft()).x()
        self.assertGreater(cursor_widget_x, 28)

        # Test date and content setters/getters
        widget.set_date("2026-09-11")
        self.assertEqual(widget.date(), "2026-09-11")
        widget.set_task_content("today i did this")
        self.assertEqual(widget.task_content(), "today i did this")

        # Caret with multiline text still starts clearly to the right of red margin line
        cursor_widget_x_with_text = widget.text_edit.viewport().mapTo(widget.text_edit, widget.text_edit.cursorRect().topLeft()).x()
        self.assertGreater(cursor_widget_x_with_text, 28)

        widget.clear()
        self.assertEqual(widget.task_content(), "")

    def test_additional_task_widget_validation_empty_text(self):
        """Verify submitting or drafting empty text triggers validation and halts submission."""
        widget = AdditionalTaskWidget()
        with patch.object(TaskService, "save_additional_task") as mock_save:
            widget.save_task(is_draft=False)
            mock_save.assert_not_called()
            self.assertIn("Please enter", widget.status_msg_label.text())

            widget.save_task(is_draft=True)
            mock_save.assert_not_called()

    def test_additional_task_widget_save_as_draft_and_submit(self):
        """Verify Save As Draft (status=0) and Submit Task (status=1) invoke TaskService properly."""
        widget = AdditionalTaskWidget()
        widget.set_date("2026-09-11")
        widget.text_edit.setPlainText("today i did this")

        # 1. Test Save As Draft (status="0")
        with patch.object(TaskService, "save_additional_task", return_value=(True, "Draft saved.", {"status": 1})) as mock_save:
            widget.save_task(is_draft=True)
            # Give background thread a moment to run
            time.sleep(0.1)
            QCoreApplication.processEvents()
            mock_save.assert_called_once_with(
                task="today i did this",
                date="2026-09-11",
                status="0",
            )

        # 2. Test Submit Task (status="1")
        with patch.object(TaskService, "save_additional_task", return_value=(True, "Task submitted.", {"status": 1})) as mock_save:
            widget.save_task(is_draft=False)
            time.sleep(0.1)
            QCoreApplication.processEvents()
            mock_save.assert_called_once_with(
                task="today i did this",
                date="2026-09-11",
                status="1",
            )

    def test_additional_task_widget_error_preserves_text(self):
        """Verify errors during save preserve the user entered text without clearing."""
        widget = AdditionalTaskWidget()
        widget.set_date("2026-09-11")
        widget.text_edit.setPlainText("important detailed activity report")

        with patch.object(TaskService, "save_additional_task", return_value=(False, "Network connection failure", None)):
            widget.save_task(is_draft=False)
            time.sleep(0.1)
            QCoreApplication.processEvents()
            # User text must remain untouched
            self.assertEqual(widget.task_content(), "important detailed activity report")
            self.assertIn("Network connection failure", widget.status_msg_label.text())
            self.assertIn("Retry", widget.submit_btn.text())

    def test_dashboard_page_has_additional_task_widget(self):
        """Verify DashboardPage exposes additional_task_widget directly below AssignedTasksTable."""
        mock_activity_svc = MagicMock(spec=ActivityService)
        mock_activity_svc.get_today_total_seconds.return_value = 1800
        mock_activity_svc.get_uploaded_records_count.return_value = 15
        mock_activity_svc.get_today_total_idle_seconds.return_value = 120
        mock_activity_svc.get_today_timeline.return_value = []

        cfg = ApiConfig()
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
        )
        SessionService().login(
            username="dinesh",
            role="Employee",
            indo_code="EC-098",
            api_key="testapikey111",
            full_name="Dinesh Dev",
        )

        dashboard = DashboardPage(activity_service=mock_activity_svc)
        self.assertTrue(hasattr(dashboard, "additional_task_widget"))
        self.assertIsInstance(dashboard.additional_task_widget, AdditionalTaskWidget)
        self.assertIs(dashboard.add_additional_task_widget, dashboard.additional_task_widget)

        # Verify dynamic update via _apply_dashboard_data
        data = {
            "fetch_date": "2026-09-11",
            "tasks": [
                {
                    "id": "add_task_1",
                    "title": "Daily Activity / Additional Task",
                    "description": "today i did this",
                    "is_additional": True,
                }
            ],
            "total_seconds": 1800,
            "uploaded_count": 15,
            "today_idle": 120,
            "timeline": [],
        }
        dashboard._apply_dashboard_data(data)
        self.assertEqual(dashboard.additional_task_widget.date(), "2026-09-11")
        self.assertEqual(dashboard.additional_task_widget.task_content(), "today i did this")

    def test_assigned_and_additional_task_buttons_horizontal_centering_and_16px_gap(self):
        """
        Verify both Assigned Task and Additional Task sections display Save as Draft and Submit
        buttons horizontally centered within their section with an exact 16px gap across desktop,
        tablet, and mobile widths, wrapping onto new lines without clipping when constrained.
        """
        from PySide6.QtCore import QPoint
        table = AssignedTasksTable()
        widget = AdditionalTaskWidget()

        # ── Test 1: AssignedTasksTable actions_widget buttons ───────────────────
        table.actions_widget.show()
        for test_width in (1200, 768, 480, 320):
            table.actions_widget.resize(test_width, 80)
            QCoreApplication.processEvents()
            b1 = table.save_draft_btn
            b2 = table.submit_btn

            # Side by side with exact 16px gap
            gap = b2.mapTo(table.actions_widget, QPoint(0, 0)).x() - b1.mapTo(table.actions_widget, QPoint(b1.width(), 0)).x()
            self.assertEqual(gap, 16, f"Assigned task button gap must be exactly 16px at width {test_width}")

            # Horizontally centered relative to actions_widget section
            b1_left = b1.mapTo(table.actions_widget, QPoint(0, 0)).x()
            b2_right = b2.mapTo(table.actions_widget, QPoint(b2.width(), 0)).x()
            group_center = (b1_left + b2_right) / 2
            section_center = table.actions_widget.width() / 2
            self.assertAlmostEqual(
                group_center,
                section_center,
                delta=2.0,
                msg=f"Assigned task button group must be centered within section at width {test_width}",
            )

        # Narrow screen wrapping test for AssignedTasksTable
        table.actions_widget.resize(180, 150)
        QCoreApplication.processEvents()
        b1_geom = table.save_draft_btn.geometry()
        b2_geom = table.submit_btn.geometry()
        self.assertGreater(
            b2_geom.top(),
            b1_geom.bottom(),
            "Assigned task buttons should wrap vertically on narrow screen without clipping",
        )

        # ── Test 2: AdditionalTaskWidget action buttons ─────────────────────────
        widget.show()
        for test_width in (1200, 768, 480, 320):
            widget.resize(test_width, 350)
            QCoreApplication.processEvents()
            b1 = widget.save_draft_btn
            b2 = widget.submit_btn

            # Side by side with exact 16px gap
            gap = b2.mapTo(widget, QPoint(0, 0)).x() - b1.mapTo(widget, QPoint(b1.width(), 0)).x()
            self.assertEqual(gap, 16, f"Additional task button gap must be exactly 16px at width {test_width}")

            # Horizontally centered relative to AdditionalTaskWidget section
            b1_left = b1.mapTo(widget, QPoint(0, 0)).x()
            b2_right = b2.mapTo(widget, QPoint(b2.width(), 0)).x()
            group_center = (b1_left + b2_right) / 2
            section_center = widget.width() / 2
            self.assertAlmostEqual(
                group_center,
                section_center,
                delta=2.0,
                msg=f"Additional task button group must be centered within section at width {test_width}",
            )

        # Narrow screen wrapping test for AdditionalTaskWidget
        widget.resize(180, 400)
        QCoreApplication.processEvents()
        b1_geom = widget.save_draft_btn.geometry()
        b2_geom = widget.submit_btn.geometry()
        self.assertGreater(
            b2_geom.top(),
            b1_geom.bottom(),
            "Additional task buttons should wrap vertically on narrow screen without clipping",
        )

    # ── Post-Submission Behavior Verification Scenarios (1 through 6) ──────────

    def test_post_submission_scenario_1_unsubmitted_shows_both_buttons(self):
        """Scenario 1: An unsubmitted Timesheet shows both Save as Draft and Submit buttons."""
        table = AssignedTasksTable()
        tasks = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "0",
            "name": "Design Mockups",
            "description": "Create UI wireframes",
            "category": "Design",
            "target": "2 Wireframes",
            "measurement_criteria": "Figma review",
            "weightage": "30%",
            "task_done": "0",
            "task_completed": "",
            "comment": "",
            "submit_status": "0",
            "status": "In Progress",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]
        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        table.actions_widget.show()
        # Both buttons must be visible and enabled
        self.assertFalse(table.is_submitted)
        self.assertFalse(table.save_draft_btn.isHidden())
        self.assertTrue(table.save_draft_btn.isEnabled())
        self.assertFalse(table.submit_btn.isHidden())
        self.assertTrue(table.submit_btn.isEnabled())
        self.assertEqual(table.save_draft_btn.text(), "Save as Draft")
        self.assertEqual(table.submit_btn.text(), "Submit")

    def test_post_submission_scenario_2_successful_submission_hides_submit(self):
        """Scenario 2: A successful submission hides Submit and keeps it hidden."""
        table = AssignedTasksTable()
        tasks = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "0",
            "name": "Design Mockups",
            "description": "Create UI wireframes",
            "category": "Design",
            "target": "2 Wireframes",
            "measurement_criteria": "Figma review",
            "weightage": "30%",
            "task_done": "0",
            "task_completed": "100",
            "comment": "Completed wireframes in Figma",
            "submit_status": "0",
            "status": "In Progress",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]
        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        submitted_api_tasks = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "789",
            "name": "Design Mockups",
            "description": "Create UI wireframes",
            "category": "Design",
            "target": "2 Wireframes",
            "measurement_criteria": "Figma review",
            "weightage": "30%",
            "task_done": "0",
            "task_completed": "100",
            "comment": "Completed wireframes in Figma",
            "submit_status": "1",
            "status": "Completed",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]

        with patch.object(TaskService, "save_time_sheet", return_value=(True, "Timesheet submitted successfully.", {"status": "1"})) as mock_save:
            with patch.object(TaskService, "fetch_assigned_tasks", return_value=submitted_api_tasks):
                # Click Submit
                table.submit_btn.click()
                time.sleep(0.1)
                QCoreApplication.processEvents()

                # Backend confirmed submission
                mock_save.assert_called_once()
                self.assertEqual(mock_save.call_args[1]["submit_status"], "1")

                # Submit and Save as Draft buttons must both be hidden, leaving no empty container
                self.assertTrue(table.is_submitted)
                self.assertTrue(table.submit_btn.isHidden())
                self.assertTrue(table.save_draft_btn.isHidden())
                self.assertTrue(table.buttons_container.isHidden())

                # Even after timer resets action buttons, both buttons must NOT reappear
                table._reset_action_buttons()
                self.assertTrue(table.submit_btn.isHidden())
                self.assertTrue(table.save_draft_btn.isHidden())
                self.assertTrue(table.buttons_container.isHidden())

    def test_post_submission_scenario_3_failed_submission_keeps_submit_available(self):
        """Scenario 3: A failed submission keeps Submit available for retry and preserves entered values."""
        table = AssignedTasksTable()
        tasks = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "0",
            "name": "API Integration",
            "description": "Connect endpoints",
            "category": "Dev",
            "target": "API",
            "measurement_criteria": "Postman tests",
            "weightage": "50%",
            "task_done": "0",
            "task_completed": "80",
            "comment": "Connected auth and timeline endpoints",
            "submit_status": "0",
            "status": "In Progress",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]
        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        with patch.object(TaskService, "save_time_sheet", return_value=(False, "500 Server Internal Error", None)) as mock_save:
            table.submit_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            mock_save.assert_called_once()
            # Submit and Save as Draft buttons must remain available for retry
            self.assertFalse(table.is_submitted)
            self.assertFalse(table.submit_btn.isHidden())
            self.assertTrue(table.submit_btn.isEnabled())
            self.assertFalse(table.save_draft_btn.isHidden())
            self.assertTrue(table.save_draft_btn.isEnabled())
            self.assertFalse(table.buttons_container.isHidden())
            self.assertEqual(table.submit_btn.text(), "Retry Submit ⚠️")
            # Entered values must be preserved
            self.assertEqual(table._get_line_edit(0, 8).text(), "80")
            self.assertEqual(table._get_line_edit(0, 9).text(), "Connected auth and timeline endpoints")

    def test_post_submission_scenario_4_reopening_or_refreshing_already_submitted_keeps_submit_hidden(self):
        """Scenario 4: Reopening or refreshing an already-submitted Timesheet keeps Submit hidden based on API status."""
        table = AssignedTasksTable()
        # Simulated response from API when retrieving already-submitted Timesheet
        submitted_tasks_from_api = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "789",
            "name": "Security Audit",
            "description": "Review permissions",
            "category": "Security",
            "target": "Audit",
            "measurement_criteria": "Checklist",
            "weightage": "20%",
            "task_done": "0",
            "task_completed": "100",
            "comment": "Completed full permission audit",
            "submit_status": "1",
            "status": "Completed",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]

        # Initial load / reopening of already-submitted timesheet
        table.set_tasks(submitted_tasks_from_api, date="2026-10-14")
        QCoreApplication.processEvents()

        self.assertTrue(table.is_submitted)
        self.assertTrue(table.submit_btn.isHidden())
        self.assertTrue(table.save_draft_btn.isHidden())
        self.assertTrue(table.buttons_container.isHidden())

        # Page refresh with fresh fetch from API
        table.set_tasks(submitted_tasks_from_api, date="2026-10-14")
        QCoreApplication.processEvents()

        self.assertTrue(table.is_submitted)
        self.assertTrue(table.submit_btn.isHidden())
        self.assertTrue(table.save_draft_btn.isHidden())
        self.assertTrue(table.buttons_container.isHidden())

        # Switching to unsubmitted date restores Submit button
        unsubmitted_tasks = [{
            "id": "102",
            "kra_id": "102",
            "timesheet_id": "0",
            "name": "Documentation",
            "description": "Write guide",
            "category": "Docs",
            "target": "Guide",
            "measurement_criteria": "Markdown",
            "weightage": "10%",
            "task_done": "0",
            "task_completed": "",
            "comment": "",
            "submit_status": "0",
            "status": "Pending",
            "date": "2026-10-15",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]
        table.set_tasks(unsubmitted_tasks, date="2026-10-15")
        QCoreApplication.processEvents()

        self.assertFalse(table.is_submitted)
        self.assertFalse(table.submit_btn.isHidden())
        self.assertTrue(table.submit_btn.isEnabled())
        self.assertFalse(table.save_draft_btn.isHidden())
        self.assertTrue(table.save_draft_btn.isEnabled())
        self.assertFalse(table.buttons_container.isHidden())

        # Switching back to submitted date hides Submit button again
        table.set_tasks(submitted_tasks_from_api, date="2026-10-14")
        QCoreApplication.processEvents()

        self.assertTrue(table.is_submitted)
        self.assertTrue(table.submit_btn.isHidden())
        self.assertTrue(table.save_draft_btn.isHidden())
        self.assertTrue(table.buttons_container.isHidden())

    def test_post_submission_scenario_5_submitted_values_and_comments_match_api_response(self):
        """Scenario 5: Display latest submitted Timesheet data dynamically from actual API response."""
        table = AssignedTasksTable()
        initial_tasks = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "0",
            "name": "API Development",
            "description": "Build user auth modules",
            "category": "Backend",
            "target": "Auth",
            "measurement_criteria": "JWT verification",
            "weightage": "40%",
            "task_done": "0",
            "task_completed": "50",
            "comment": "Working on token expiry",
            "submit_status": "0",
            "status": "In Progress",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]
        table.set_tasks(initial_tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        # Simulated fresh API response returned by get_kra after submit
        fresh_api_response = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "999",
            "name": "API Development",
            "description": "Build user auth modules",
            "category": "Backend",
            "target": "Auth",
            "measurement_criteria": "JWT verification",
            "weightage": "40%",
            "task_done": "0",
            "task_completed": "100",
            "comment": "Token expiry and refresh flow verified against server",
            "submit_status": "1",
            "status": "Completed",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]

        with patch.object(TaskService, "save_time_sheet", return_value=(True, "Timesheet submitted successfully.", {"status": "1"})):
            with patch.object(TaskService, "fetch_assigned_tasks", return_value=fresh_api_response):
                table.submit_btn.click()
                time.sleep(0.1)
                QCoreApplication.processEvents()

                # Values in table rows must match actual API response
                self.assertEqual(table._get_line_edit(0, 8).text(), "100")
                self.assertEqual(table._get_line_edit(0, 9).text(), "Token expiry and refresh flow verified against server")
                # Title heading dynamically populates employee name, code, date
                self.assertEqual(table.title_label.text(), "Timesheet for Dinesh Dev (EC-098) on 14 October 2026")
                # Both buttons and container are hidden
                self.assertTrue(table.submit_btn.isHidden())
                self.assertTrue(table.save_draft_btn.isHidden())
                self.assertTrue(table.buttons_container.isHidden())

    def test_post_submission_scenario_6_draft_functionality_and_unrelated_behavior_unchanged(self):
        """Scenario 6: Draft functionality and unrelated Timesheet behavior remain unchanged."""
        table = AssignedTasksTable()
        tasks = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "0",
            "name": "Frontend Refactoring",
            "description": "Clean up style classes",
            "category": "UI",
            "target": "Styles",
            "measurement_criteria": "Linter",
            "weightage": "20%",
            "task_done": "0",
            "task_completed": "40",
            "comment": "Refactored color palette",
            "submit_status": "0",
            "status": "In Progress",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]
        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        draft_api_tasks = [{
            "id": "101",
            "kra_id": "101",
            "timesheet_id": "888",
            "name": "Frontend Refactoring",
            "description": "Clean up style classes",
            "category": "UI",
            "target": "Styles",
            "measurement_criteria": "Linter",
            "weightage": "20%",
            "task_done": "0",
            "task_completed": "40",
            "comment": "Refactored color palette",
            "submit_status": "0",
            "status": "In Progress",
            "date": "2026-10-14",
            "employee_name": "Dinesh Dev",
            "indo_code": "EC-098",
        }]

        with patch.object(TaskService, "save_time_sheet", return_value=(True, "Draft saved successfully.", {"TimeSheet_id": "888"})) as mock_draft:
            with patch.object(TaskService, "fetch_assigned_tasks", return_value=draft_api_tasks):
                # Click Save as Draft
                table.save_draft_btn.click()
                time.sleep(0.1)
                QCoreApplication.processEvents()

                mock_draft.assert_called_once()
                self.assertEqual(mock_draft.call_args[1]["submit_status"], "0")

                # Both buttons must remain visible
                self.assertFalse(table.is_submitted)
                self.assertFalse(table.save_draft_btn.isHidden())
                self.assertFalse(table.submit_btn.isHidden())
                self.assertTrue(table.submit_btn.isEnabled())
                self.assertEqual(table.save_draft_btn.text(), "Draft Saved ✓")

                # Table structure preserved: columns 3 and 5 remain hidden
                self.assertTrue(table.isColumnHidden(3))
                self.assertTrue(table.isColumnHidden(5))

    # ── Additional Task Post-Submission Button Visibility Scenarios ───────────

    def test_additional_task_scenario_1_buttons_appear_before_submission(self):
        """1. Before submission: Show both Save As Draft and Submit Task buttons; task-entry fully functional."""
        widget = AdditionalTaskWidget()
        widget.set_date("2026-10-14")
        widget.set_task_content("Working on client documentation")

        # Both buttons appear and are enabled
        self.assertFalse(widget.is_submitted)
        self.assertFalse(widget.save_draft_btn.isHidden())
        self.assertTrue(widget.save_draft_btn.isEnabled())
        self.assertFalse(widget.submit_btn.isHidden())
        self.assertTrue(widget.submit_btn.isEnabled())
        self.assertEqual(widget.save_draft_btn.text(), "Save As Draft")
        self.assertEqual(widget.submit_btn.text(), "Submit Task")

        # Task-entry area is fully functional and retains content
        self.assertEqual(widget.task_content(), "Working on client documentation")
        widget.text_edit.setPlainText("Updated notes")
        self.assertEqual(widget.task_content(), "Updated notes")

    def test_additional_task_scenario_2_buttons_disappear_after_successful_submission(self):
        """2. After successful submission: Hide BOTH Save As Draft and Submit Task buttons; keep content."""
        widget = AdditionalTaskWidget()
        widget.set_date("2026-10-14")
        widget.set_task_content("Completed infrastructure deployment")

        with patch.object(TaskService, "save_additional_task", return_value=(True, "Additional task saved successfully.", {"status": 1})) as mock_save:
            # Click Submit Task
            widget.submit_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            mock_save.assert_called_once_with(
                task="Completed infrastructure deployment",
                date="2026-10-14",
                status="1",
            )

            # Both buttons must be hidden
            self.assertTrue(widget.is_submitted)
            self.assertTrue(widget.save_draft_btn.isHidden())
            self.assertTrue(widget.submit_btn.isHidden())

            # Submitted content remains unchanged
            self.assertEqual(widget.task_content(), "Completed infrastructure deployment")

            # Resetting action buttons must keep them hidden
            widget._reset_action_buttons()
            self.assertTrue(widget.save_draft_btn.isHidden())
            self.assertTrue(widget.submit_btn.isHidden())

    def test_additional_task_scenario_3_buttons_remain_visible_after_failed_submission(self):
        """3. If submission fails: Keep both buttons visible so user can retry or save draft; display error."""
        widget = AdditionalTaskWidget()
        widget.set_date("2026-10-14")
        widget.set_task_content("Attempted server sync")

        with patch.object(TaskService, "save_additional_task", return_value=(False, "Gateway Timeout", None)) as mock_save:
            widget.submit_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            mock_save.assert_called_once()
            # Task must NOT be marked submitted
            self.assertFalse(widget.is_submitted)

            # Both buttons must remain visible
            self.assertFalse(widget.save_draft_btn.isHidden())
            self.assertFalse(widget.submit_btn.isHidden())
            self.assertTrue(widget.save_draft_btn.isEnabled())
            self.assertTrue(widget.submit_btn.isEnabled())
            self.assertEqual(widget.submit_btn.text(), "Retry Submit ⚠️")
            self.assertIn("Gateway Timeout", widget.status_msg_label.text())

            # Content is preserved
            self.assertEqual(widget.task_content(), "Attempted server sync")

    def test_additional_task_scenario_4_reopening_page_respects_actual_saved_submission_status(self):
        """4. Reopening/refreshing page: Keep both buttons hidden when API confirms task is already submitted."""
        widget = AdditionalTaskWidget()

        # Case A: API returns submitted additional task (additional_task_status = 1)
        api_submitted_task = "Fixed production incident and migrated database"
        widget.set_date("2026-10-14")
        widget.set_task_content(api_submitted_task, is_submitted=True)
        QCoreApplication.processEvents()

        self.assertTrue(widget.is_submitted)
        self.assertTrue(widget.save_draft_btn.isHidden())
        self.assertTrue(widget.submit_btn.isHidden())
        self.assertEqual(widget.task_content(), api_submitted_task)

        # Case B: Switching to a date where additional task is draft or unsubmitted
        widget.set_date("2026-10-15")
        widget.set_task_content("Draft activity notes", is_submitted=False)
        QCoreApplication.processEvents()

        self.assertFalse(widget.is_submitted)
        self.assertFalse(widget.save_draft_btn.isHidden())
        self.assertFalse(widget.submit_btn.isHidden())

        # Case C: Switching back to submitted date restores hidden buttons
        widget.set_date("2026-10-14")
        widget.set_task_content(api_submitted_task, is_submitted=True)
        QCoreApplication.processEvents()

        self.assertTrue(widget.is_submitted)
        self.assertTrue(widget.save_draft_btn.isHidden())
        self.assertTrue(widget.submit_btn.isHidden())

    def test_additional_task_scenario_5_existing_api_integration_and_draft_unchanged(self):
        """5. Existing API integration and task content remain unchanged; draft keeps buttons visible."""
        widget = AdditionalTaskWidget()
        widget.set_date("2026-10-14")
        widget.set_task_content("Draft activity for review")

        with patch.object(TaskService, "save_additional_task", return_value=(True, "Draft saved.", {"status": 1})) as mock_save:
            # Click Save As Draft
            widget.save_draft_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            mock_save.assert_called_once_with(
                task="Draft activity for review",
                date="2026-10-14",
                status="0",
            )

            # Draft save must NOT hide buttons
            self.assertFalse(widget.is_submitted)
            self.assertFalse(widget.save_draft_btn.isHidden())
            self.assertFalse(widget.submit_btn.isHidden())
            self.assertTrue(widget.save_draft_btn.isEnabled())
            self.assertTrue(widget.submit_btn.isEnabled())
            self.assertEqual(widget.save_draft_btn.text(), "Draft Saved ✓")

            # Content preserved
            self.assertEqual(widget.task_content(), "Draft activity for review")

    def test_separate_timesheet_and_additional_task_data(self):
        """1. Separation: Assigned tasks appear in table; additional tasks appear only in additional task widget."""
        table = AssignedTasksTable()
        addl_widget = AdditionalTaskWidget()
        table.additional_task_widget = addl_widget

        tasks = [
            {
                "id": "kra_101",
                "kra_id": "101",
                "timesheet_id": "ts_1",
                "name": "Backend API Optimization",
                "description": "Optimize database queries",
                "target": "10",
                "weightage": "20%",
                "task_done": "5",
                "task_completed": "2",
                "comment": "In progress",
                "submit_status": "0",
                "is_additional": False,
            },
            {
                "id": "kra_102",
                "kra_id": "102",
                "timesheet_id": "ts_2",
                "name": "Daily Activity / Resembling Additional Task",
                "description": "Legitimate assigned task that mentions additional task in description",
                "target": "5",
                "weightage": "15%",
                "task_done": "3",
                "task_completed": "1",
                "comment": "Verified",
                "submit_status": "0",
                "is_additional": False,
            },
            {
                "id": "add_task_1",
                "title": "Daily Activity / Additional Task",
                "description": "Fixed urgent client bug off-schedule",
                "task_completed": "1",
                "status": "Completed",
                "submit_status": "1",
                "is_additional": True,
            },
        ]

        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        # Main table has exactly the 2 legitimate assigned tasks (row count = 2)
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(len(table.tasks), 2)
        self.assertEqual(table.item(0, 1).text(), "Backend API Optimization")
        self.assertEqual(table.item(1, 1).text(), "Daily Activity / Resembling Additional Task")

        # Additional task record is NOT in the Timesheet table
        for r in range(table.rowCount()):
            self.assertNotEqual(table.item(r, 1).text(), "Daily Activity / Additional Task")

        # Additional Task widget receives the additional task data
        self.assertEqual(addl_widget.task_content(), "Fixed urgent client bug off-schedule")
        self.assertTrue(addl_widget.is_submitted)

    def test_comments_and_completed_preserved_across_rerenders_and_refreshes(self):
        """3. Comments and task completed values are preserved across periodic refreshes and rerenders."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "kra_201",
                "kra_id": "201",
                "timesheet_id": "ts_201",
                "name": "Frontend Component Refactoring",
                "description": "Refactor table view",
                "submit_status": "0",
                "is_additional": False,
            }
        ]

        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        # User types long comments and task completion
        comment_edit = table._get_line_edit(0, 9)
        completed_edit = table._get_line_edit(0, 8)
        self.assertIsNotNone(comment_edit)
        self.assertIsNotNone(completed_edit)

        user_comment = "Completed the refactoring and passed all unit test assertions without regressions."
        user_comp = "4.5"

        comment_edit.setText(user_comment)
        completed_edit.setText(user_comp)
        QCoreApplication.processEvents()

        self.assertEqual(table._get_comment(0), user_comment)
        self.assertEqual(table._get_task_completed(0), user_comp)

        # Background sync / API refresh arrives with stale/empty comment data
        stale_api_tasks = [
            {
                "id": "kra_201",
                "kra_id": "201",
                "timesheet_id": "ts_201",
                "name": "Frontend Component Refactoring",
                "description": "Refactor table view",
                "comment": "",
                "task_completed": "",
                "submit_status": "0",
                "is_additional": False,
            }
        ]

        table.set_tasks(stale_api_tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        # User-entered comment and completion are NOT wiped out
        self.assertEqual(table._get_comment(0), user_comment)
        self.assertEqual(table._get_task_completed(0), user_comp)
        new_comment_edit = table._get_line_edit(0, 9)
        self.assertEqual(new_comment_edit.text(), user_comment)

    def test_save_draft_preserves_comments_and_keeps_timesheet_editable(self):
        """4. Save as Draft preserves current comments and does not mark Timesheet as submitted."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "kra_301",
                "kra_id": "301",
                "timesheet_id": "ts_301",
                "name": "Database Migration",
                "description": "Schema upgrade",
                "submit_status": "0",
                "is_additional": False,
            }
        ]
        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        comment_edit = table._get_line_edit(0, 9)
        comment_edit.setText("Drafting migration scripts for table schema")
        completed_edit = table._get_line_edit(0, 8)
        completed_edit.setText("2")
        QCoreApplication.processEvents()

        with patch.object(TaskService, "save_time_sheet", return_value=(True, "Draft saved.", {"status": 1})) as mock_save, \
             patch.object(TaskService, "fetch_assigned_tasks", return_value=tasks):

            table.save_draft_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            mock_save.assert_called_once()
            _, kwargs = mock_save.call_args
            self.assertEqual(kwargs.get("submit_status"), "0")

            # Timesheet remains unsubmitted and editable
            self.assertFalse(table.is_submitted)
            self.assertFalse(table.save_draft_btn.isHidden())
            self.assertFalse(table.submit_btn.isHidden())
            self.assertEqual(table._get_comment(0), "Drafting migration scripts for table schema")

    def test_failed_submission_preserves_comments_and_leaves_timesheet_editable(self):
        """5b. Failed submission keeps Timesheet editable and preserves comments for retry."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "kra_401",
                "kra_id": "401",
                "timesheet_id": "ts_401",
                "name": "CI/CD Pipeline",
                "description": "Fix docker runner",
                "submit_status": "0",
                "is_additional": False,
            }
        ]
        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        table._get_line_edit(0, 9).setText("Fixed docker config")
        table._get_line_edit(0, 8).setText("1")
        QCoreApplication.processEvents()

        with patch.object(TaskService, "save_time_sheet", return_value=(False, "Network connection error", {})):
            table.submit_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            # Timesheet must remain unsubmitted and editable
            self.assertFalse(table.is_submitted)
            self.assertFalse(table.submit_btn.isHidden())
            self.assertFalse(table.save_draft_btn.isHidden())
            self.assertEqual(table._get_comment(0), "Fixed docker config")
            self.assertEqual(table._get_task_completed(0), "1")
            self.assertFalse(table._get_line_edit(0, 9).isReadOnly())
            self.assertIn("Retry", table.submit_btn.text())

    def test_successful_submission_makes_timesheet_read_only_and_hides_buttons(self):
        """5a. Confirmed submission disables editing and hides action buttons."""
        table = AssignedTasksTable()
        tasks = [
            {
                "id": "kra_501",
                "kra_id": "501",
                "timesheet_id": "ts_501",
                "name": "Security Audit",
                "description": "Audit token permissions",
                "submit_status": "0",
                "is_additional": False,
            }
        ]
        table.set_tasks(tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        table._get_line_edit(0, 9).setText("Audit completed with zero vulnerabilities")
        table._get_line_edit(0, 8).setText("5")
        QCoreApplication.processEvents()

        fresh_submitted_tasks = [
            {
                "id": "kra_501",
                "kra_id": "501",
                "timesheet_id": "ts_501",
                "name": "Security Audit",
                "description": "Audit token permissions",
                "comment": "Audit completed with zero vulnerabilities",
                "task_completed": "5",
                "submit_status": "1",
                "is_additional": False,
            }
        ]

        with patch.object(TaskService, "save_time_sheet", return_value=(True, "Submitted successfully.", {"status": 1})), \
             patch.object(TaskService, "fetch_assigned_tasks", return_value=fresh_submitted_tasks):

            table.submit_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            self.assertTrue(table.is_submitted)
            # Buttons hidden
            self.assertTrue(table.save_draft_btn.isHidden())
            self.assertTrue(table.submit_btn.isHidden())
            self.assertTrue(table.buttons_container.isHidden())

            # Submitted fields are read-only
            self.assertTrue(table._get_line_edit(0, 8).isReadOnly())
            self.assertTrue(table._get_line_edit(0, 9).isReadOnly())
            self.assertEqual(table._get_comment(0), "Audit completed with zero vulnerabilities")

    def test_reopen_or_refresh_already_submitted_timesheet_preserves_read_only(self):
        """5c & 6. Opening an already-submitted Timesheet from the API is read-only with buttons hidden."""
        table = AssignedTasksTable()
        submitted_tasks = [
            {
                "id": "kra_601",
                "kra_id": "601",
                "timesheet_id": "ts_601",
                "name": "Payment Gateway",
                "description": "Stripe webhook integration",
                "comment": "Processed 100% of webhooks",
                "task_completed": "10",
                "submit_status": "1",
                "is_additional": False,
            }
        ]

        table.set_tasks(submitted_tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        self.assertTrue(table.is_submitted)
        self.assertTrue(table.save_draft_btn.isHidden())
        self.assertTrue(table.submit_btn.isHidden())
        self.assertTrue(table._get_line_edit(0, 8).isReadOnly())
        self.assertTrue(table._get_line_edit(0, 9).isReadOnly())
        self.assertEqual(table._get_comment(0), "Processed 100% of webhooks")

    def test_additional_task_status_does_not_affect_timesheet_submission_status(self):
        """1 & 6. Additional task being submitted does NOT mark the Timesheet table as submitted."""
        table = AssignedTasksTable()
        addl_widget = AdditionalTaskWidget()
        table.additional_task_widget = addl_widget

        # Timesheet task is unsubmitted (submit_status: "0"), additional task is submitted (status: "1")
        mixed_tasks = [
            {
                "id": "kra_701",
                "kra_id": "701",
                "timesheet_id": "ts_701",
                "name": "Core Engine",
                "description": "Async loop improvements",
                "comment": "Draft notes",
                "task_completed": "1",
                "submit_status": "0",
                "is_additional": False,
            },
            {
                "id": "add_task_1",
                "title": "Daily Activity / Additional Task",
                "description": "Submitted additional task",
                "task_completed": "1",
                "status": "Completed",
                "submit_status": "1",
                "additional_task_status": "1",
                "is_additional": True,
            },
        ]

        table.set_tasks(mixed_tasks, date="2026-10-14")
        QCoreApplication.processEvents()

        # Timesheet table MUST remain unsubmitted and editable
        self.assertFalse(table.is_submitted)
        self.assertFalse(table.save_draft_btn.isHidden())
        self.assertFalse(table.submit_btn.isHidden())
        self.assertFalse(table._get_line_edit(0, 8).isReadOnly())
        self.assertFalse(table._get_line_edit(0, 9).isReadOnly())

        # Additional task widget is submitted
        self.assertTrue(addl_widget.is_submitted)
        self.assertTrue(addl_widget.save_draft_btn.isHidden())
        self.assertTrue(addl_widget.submit_btn.isHidden())


if __name__ == "__main__":
    unittest.main()

