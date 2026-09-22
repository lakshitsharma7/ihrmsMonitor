"""Tests for Workpulse Dashboard network status card.

Verifies:
1. 'Status: Sync Successful' is completely removed from the dashboard.
2. Status card displays dynamic network status:
   - Connected -> '● Online' and 'Status: Online' (green)
   - Disconnected -> '● Offline' and 'Status: Offline' (red)
3. Status updates automatically when network connectivity changes.
4. Temporary API sync failures do NOT change status to Offline when network is connected.
5. Paused tracking does NOT change network status to Offline.
6. Network reachability monitor works properly with reachability checks and callbacks.
"""

import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication

from services.session_service import SessionService
from services.network_monitor import NetworkReachabilityMonitor
from tracker.activity_tracker import TrackerState
from ui.dashboard import DashboardPage


class TestNetworkStatusCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        SessionService().clear()
        self.mock_service = MagicMock()
        self.mock_service.get_today_total_seconds.return_value = 100
        self.mock_service.get_persisted_daily_active_seconds.return_value = 100

    def tearDown(self):
        SessionService().clear()

    def test_sync_successful_removed_and_initial_online_status(self):
        """Dashboard initializes with dynamic network status Online and no 'Sync Successful'."""
        dashboard = DashboardPage(self.mock_service)
        dashboard.set_tracking_active(True)

        self.assertNotIn("Sync Successful", dashboard.update_status_label.text())
        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertEqual(dashboard.update_status_label.text(), "Status: Online")

    def test_dynamic_network_status_online_to_offline_transition(self):
        """Dashboard updates status label and network status when connectivity changes."""
        dashboard = DashboardPage(self.mock_service)

        # 1. Connected state
        dashboard.set_network_status(True)
        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertEqual(dashboard.update_status_label.text(), "Status: Online")
        self.assertIn("#10b981", dashboard.network_status_label.styleSheet())
        self.assertIn("#10b981", dashboard.update_status_label.styleSheet())

        # 2. Disconnected state
        dashboard.set_network_status(False)
        self.assertEqual(dashboard.network_status_label.text(), "● Offline")
        self.assertEqual(dashboard.update_status_label.text(), "Status: Offline")
        self.assertIn("#ef4444", dashboard.network_status_label.styleSheet())
        self.assertIn("#ef4444", dashboard.update_status_label.styleSheet())

        # 3. Reconnected state
        dashboard.set_network_status(True)
        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertEqual(dashboard.update_status_label.text(), "Status: Online")

    def test_api_sync_failure_does_not_mark_offline_if_network_connected(self):
        """A temporary API sync failure must not change status to Offline when network is connected."""
        dashboard = DashboardPage(self.mock_service)
        dashboard.set_network_status(True)

        # Simulate API refresh data coming back with error
        dashboard.refresh(async_mode=False)
        dashboard.set_sync_status("Sync Error (Timeout)")

        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertNotEqual(dashboard.update_status_label.text(), "Status: Offline")
        self.assertNotIn("Sync Successful", dashboard.update_status_label.text())

    def test_paused_tracking_does_not_show_offline(self):
        """When user pauses tracking, network status card must remain Online."""
        dashboard = DashboardPage(self.mock_service)
        dashboard.set_tracking_active(True)
        dashboard.set_network_status(True)

        # Click pause
        dashboard.tracking_toggle_button.click()
        self.assertTrue(dashboard.is_paused())

        # Network status must still be Online
        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertEqual(dashboard.update_status_label.text(), "Status: Online")

    def test_network_reachability_monitor_singleton_and_probes(self):
        """NetworkReachabilityMonitor singleton checks reachability and notifies listeners."""
        monitor = NetworkReachabilityMonitor()
        self.assertIsNotNone(monitor)

        # Test socket reachability fallback
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = MagicMock()
            is_reachable = monitor.check_reachability(timeout=1.0)
            self.assertTrue(is_reachable)

        # Test failure when all connections fail
        with patch("socket.create_connection", side_effect=OSError("Network unreachable")):
            is_reachable = monitor.check_reachability(timeout=1.0)
            self.assertFalse(is_reachable)

        # Test callback notification
        received = []
        listener = lambda state: received.append(state)
        monitor.register_listener(listener)
        monitor._notify_listeners(False)
        self.assertIn(False, received)
        monitor.unregister_listener(listener)


if __name__ == "__main__":
    unittest.main()
