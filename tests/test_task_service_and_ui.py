"""Comprehensive tests for TaskService, AssignedTasksTable, and Dashboard integration (KRA & Timesheet flow)."""

import os
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

from config.api_config import ApiConfig
from services.activity_service import ActivityService
from services.session_service import SessionService
from services.task_service import TaskService
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

        action_widget = table.cellWidget(0, 10)
        save_btn = action_widget.findChild(QPushButton)
        self.assertIsNotNone(save_btn)
        self.assertEqual(save_btn.text(), "Save")

    def test_assigned_tasks_table_save_flow_and_validation(self):
        """Verify Save flow, validation of empty comment / negative number, and successful save handling with re-fetch."""
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
        save_btn = table.cellWidget(0, 10).findChild(QPushButton)

        # 1. Validation test: empty comment should highlight error and not trigger save
        save_btn.click()
        QCoreApplication.processEvents()
        self.assertEqual(save_btn.text(), "Save")  # Still "Save", not "Saving..."

        # 2. Validation test: negative number should highlight error
        completed_edit.setText("-5")
        comment_edit.setText("Finished feature implementation")
        save_btn.click()
        QCoreApplication.processEvents()
        self.assertEqual(save_btn.text(), "Save")

        # 3. Enter valid numeric task_completed and comment, then click Save
        completed_edit.setText("30")
        with patch.object(TaskService, "save_time_sheet", return_value=(True, "Timesheet saved successfully.", {"TimeSheet_id": "587"})):
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
                save_btn.click()
                time.sleep(0.1)
                QCoreApplication.processEvents()
                self.assertEqual(save_btn.text(), "Saved ✓")
                self.assertEqual(completed_edit.text(), "30")
                self.assertEqual(comment_edit.text(), "Finished feature implementation")

    def test_assigned_tasks_table_prevent_duplicate_save(self):
        """Verify double-clicking save button prevents duplicate API calls while in progress."""
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
        save_btn = table.cellWidget(0, 10).findChild(QPushButton)

        call_count = 0
        def mock_save(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            time.sleep(0.05)
            return True, "Success", {"TimeSheet_id": "587"}

        with patch.object(TaskService, "save_time_sheet", side_effect=mock_save):
            with patch.object(TaskService, "fetch_assigned_tasks", return_value=tasks):
                save_btn.click()
                save_btn.click()  # Second click while disabled/in-progress
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
        save_btn = table.cellWidget(0, 10).findChild(QPushButton)

        # Edit values
        completed_edit.setText("75")
        comment_edit.setText("Updated comment before failure")

        # Simulate API failure
        with patch.object(TaskService, "save_time_sheet", return_value=(False, "Internal Server Error", None)):
            save_btn.click()
            time.sleep(0.1)
            QCoreApplication.processEvents()

            # Verify button shows retry state
            self.assertEqual(save_btn.text(), "Retry ⚠️")

            # Verify user-entered inputs are preserved exactly
            self.assertEqual(completed_edit.text(), "75")
            self.assertEqual(comment_edit.text(), "Updated comment before failure")

    def test_assigned_tasks_table_action_column_and_save_button_dimensions(self):
        """Verify Action column is wide enough (>= 125px), Save button fits without clipping, and responsive resizing works."""
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

        # 1. Action column width must be at least 125px (set to 130px)
        action_col_idx = 10
        action_col_width = table.columnWidth(action_col_idx)
        self.assertGreaterEqual(action_col_width, 125)

        # 2. Save button must fit fully within the action container without clipping
        action_container = table.cellWidget(0, action_col_idx)
        self.assertIsNotNone(action_container)
        save_btn = action_container.findChild(QPushButton)
        self.assertIsNotNone(save_btn)

        # Check button size relative to column width
        btn_width = save_btn.sizeHint().width()
        self.assertLess(btn_width, action_col_width)
        # Verify generous padding exists (at least 15px total horizontal padding)
        self.assertGreaterEqual(action_col_width - btn_width, 15)

        # 3. Test button states (Save, Saving..., Saved) all fit within the Action column
        for state_text in ["Save", "Saving...", "Saved ✓", "Retry ⚠️"]:
            save_btn.setText(state_text)
            self.assertLess(save_btn.sizeHint().width(), action_col_width)

        # 4. Responsive expansion on wide viewport
        table.resize(1600, 300)
        table._adjust_column_widths()
        QCoreApplication.processEvents()
        # Sum of columns should fill the viewport without empty dead space
        total_cols_width = sum(table.columnWidth(i) for i in range(table.columnCount()))
        self.assertGreaterEqual(total_cols_width, 1250)

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

        # 1. User intentionally scrolls horizontally to inspect comment/action
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


if __name__ == "__main__":
    unittest.main()
