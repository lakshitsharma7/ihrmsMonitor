"""Unit tests for TaskService, AssignedTasksTable, and Dashboard integration."""

import os
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

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

        # Default fallback to endpoint
        cfg.set_cached_configuration(
            company_code="COMP123",
            base_url="https://hrms.example.com/ci4/api",
            details={},
        )
        self.assertEqual(
            cfg.get_kra_url, "https://hrms.example.com/ci4/api/TaskPMS/get_kra"
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
                    "id": "101",
                    "kra_name": "Develop Dashboard Feature",
                    "description": "Add Assigned Tasks view to dashboard UI",
                    "status": "In Progress",
                    "date": "2025-08-12",
                    "weightage": "30%",
                },
                {
                    "task_id": "102",
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
        """Verify AssignedTasksTable displays rows, empty state, and error state properly."""
        table = AssignedTasksTable()

        # Test empty state
        table.set_tasks([])
        self.assertEqual(table.rowCount(), 1)
        self.assertIn("No assigned tasks found", table.item(0, 1).text())

        # Test loading state
        table.show_loading()
        self.assertEqual(table.rowCount(), 1)
        self.assertIn("Loading", table.item(0, 1).text())

        # Test error state
        table.show_error("API Error: 500")
        self.assertEqual(table.rowCount(), 1)
        self.assertIn("Could not load tasks", table.item(0, 1).text())

        # Test populating tasks
        tasks = [
            {
                "id": "1",
                "title": "Task 1",
                "description": "Details 1",
                "status": "Pending",
                "date": "2025-08-12",
                "weightage": "50%",
            }
        ]
        table.set_tasks(tasks)
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "Task 1")
        self.assertEqual(table.item(0, 1).text(), "Details 1")
        self.assertEqual(table.item(0, 2).text(), "Pending")
        self.assertEqual(table.item(0, 3).text(), "2025-08-12")
        self.assertEqual(table.item(0, 4).text(), "50%")

    def test_dashboard_page_integration(self):
        """Verify DashboardPage contains AssignedTasksTable and refresh populates it."""
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

        with patch.object(TaskService, "fetch_assigned_tasks", return_value=mock_tasks):
            dashboard.refresh(async_mode=False)
            self.assertEqual(dashboard.task_table.rowCount(), 1)
            self.assertEqual(dashboard.task_table.item(0, 0).text(), "Sprint Task")


if __name__ == "__main__":
    unittest.main()
