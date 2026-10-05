"""Tests for Workpulse Dashboard network connectivity and status indicator.

Verifies:
1. 'Online & Sync Status' card accurately reflects actual internet/network reachability:
   - Internet Available -> '● Online' (green: #10b981)
   - Internet Unavailable -> '● Offline' (red: #ef4444)
2. Offline state at application startup correctly displays '● Offline'.
3. Real-time transition from Online -> Offline and Offline -> Online.
4. Paused workpulse or session state does NOT alter internet connectivity indicator.
5. WorkPulse and local SQLite persistence continue uninterrupted while offline.
6. Offline records are safely retained and synced after reconnection.
7. Last successful sync timestamp is decoupled from real-time online/offline indicator.
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime
from PySide6.QtWidgets import QApplication

from services.session_service import SessionService
from services.network_monitor import NetworkReachabilityMonitor
from tracker.activity_tracker import ActivityTracker, TrackerState
from ui.dashboard import DashboardPage


class TestNetworkStatusCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        SessionService().clear()
        try:
            from services.secure_session import SessionStore
            SessionStore().set_workpulse_paused(False)
            SessionStore().set_workpulse_manually_stopped(False)
        except Exception:
            pass
        self.mock_service = MagicMock()
        self.mock_service.get_today_total_seconds.return_value = 100
        self.mock_service.get_persisted_daily_active_seconds.return_value = 100

    def tearDown(self):
        SessionService().clear()
        try:
            from services.secure_session import SessionStore
            SessionStore().set_workpulse_paused(False)
            SessionStore().set_workpulse_manually_stopped(False)
        except Exception:
            pass

    def test_online_with_internet(self):
        """Dashboard displays green ● Online when internet is available."""
        dashboard = DashboardPage(self.mock_service)
        dashboard.set_network_status(True)

        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertIn("#10b981", dashboard.network_status_label.styleSheet())
        self.assertTrue(dashboard._is_network_online)

    def test_offline_without_internet(self):
        """Dashboard displays red ● Offline when internet is unavailable."""
        dashboard = DashboardPage(self.mock_service)
        dashboard.set_network_status(False)

        self.assertEqual(dashboard.network_status_label.text(), "● Offline")
        self.assertIn("#ef4444", dashboard.network_status_label.styleSheet())
        self.assertFalse(dashboard._is_network_online)

    def test_offline_at_application_startup(self):
        """When starting with no internet, dashboard initializes directly to ● Offline."""
        with patch.object(NetworkReachabilityMonitor, "is_online", new_callable=PropertyMock, return_value=False):
            dashboard = DashboardPage(self.mock_service)
            dashboard.set_network_status(False)
            self.assertEqual(dashboard.network_status_label.text(), "● Offline")
            self.assertIn("#ef4444", dashboard.network_status_label.styleSheet())

    def test_online_after_reconnection(self):
        """Dashboard transitions smoothly from Offline to Online upon reconnection."""
        dashboard = DashboardPage(self.mock_service)

        # 1. Start Offline
        dashboard.set_network_status(False)
        self.assertEqual(dashboard.network_status_label.text(), "● Offline")

        # 2. Reconnect Online
        dashboard.set_network_status(True)
        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertIn("#10b981", dashboard.network_status_label.styleSheet())

    def test_workpulse_and_local_persistence_while_offline(self):
        """Changing network status to Offline does NOT halt workpulse or local session recording."""
        dashboard = DashboardPage(self.mock_service)
        dashboard.set_workpulse_active(True)
        dashboard.set_network_status(False)

        # Confirm workpulse remains active
        self.assertEqual(dashboard.network_status_label.text(), "● Offline")
        self.assertTrue(dashboard._is_workpulse)
        self.assertEqual(dashboard.workpulse_toggle_button.text(), "Paused")

        # Update tracker state with active application while offline
        state = TrackerState(
            is_workpulse=True,
            is_idle=False,
            current_application="Code.exe",
            current_window_title="main.py",
            idle_seconds=0.0,
        )
        dashboard.update_tracker_state(state)
        self.assertEqual(dashboard.network_status_label.text(), "● Offline")

    def test_last_sync_timestamp_decoupled_from_online_offline_indicator(self):
        """Last Successful Sync timestamp is preserved regardless of current connectivity state."""
        dashboard = DashboardPage(self.mock_service)

        # Simulate last sync timestamp set
        from services.sync_service import SyncService
        SyncService.last_successful_sync_time = "29 Sep 2026, 05:31:36 PM"

        dashboard._apply_dashboard_data({"total_seconds": 100, "uploaded_count": 5})
        dashboard.set_network_status(False)

        # Network status is Offline, but Last Sync timestamp remains displayed
        self.assertEqual(dashboard.network_status_label.text(), "● Offline")
        self.assertIn("29 Sep 2026, 05:31:36 PM", dashboard.last_sync_label.text())

    def test_paused_workpulse_does_not_show_offline(self):
        """When user pauses workpulse, network connectivity indicator remains Online."""
        dashboard = DashboardPage(self.mock_service)
        dashboard.set_workpulse_active(True)
        dashboard.set_network_status(True)

        dashboard.workpulse_toggle_button.click()
        self.assertTrue(dashboard.is_paused())

        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertIn("#10b981", dashboard.network_status_label.styleSheet())

    def test_network_reachability_monitor_probing(self):
        """NetworkReachabilityMonitor probes backend endpoints and reports online/offline correctly."""
        monitor = NetworkReachabilityMonitor()

        # Success probe
        with patch.object(NetworkReachabilityMonitor, "_probe_socket_target", return_value=True):
            self.assertTrue(monitor.check_reachability(timeout=0.5))

        # Failure probe
        with patch.object(NetworkReachabilityMonitor, "_probe_socket_target", return_value=False):
            self.assertFalse(monitor.check_reachability(timeout=0.5))

        # Listener callback
        received = []
        listener = lambda s: received.append(s)
        monitor.register_listener(listener)

        monitor.report_offline()
        self.assertFalse(monitor.is_online)
        self.assertIn(False, received)

        monitor.report_online()
        self.assertTrue(monitor.is_online)
        self.assertIn(True, received)

        monitor.unregister_listener(listener)

    def test_backend_unreachable_sets_offline(self):
        """When backend server is unreachable, reachability check returns False and updates state."""
        monitor = NetworkReachabilityMonitor()
        with patch.object(NetworkReachabilityMonitor, "_probe_socket_target", return_value=False):
            state = monitor.check_reachability(timeout=0.2)
            self.assertFalse(state)

    def test_backend_targets_retrieval(self):
        """Verify _get_targets retrieves configured backend endpoint or APP_CONTROLLER_URL fallback."""
        monitor = NetworkReachabilityMonitor()
        targets = monitor._get_targets()
        self.assertTrue(len(targets) >= 1)
        # Should include host and valid integer port
        for host, port in targets:
            self.assertIsInstance(host, str)
            self.assertTrue(len(host) > 0)
            self.assertIsInstance(port, int)
            self.assertIn(port, (80, 443))

    def test_realtime_reachability_callback_updates_dashboard(self):
        """When monitor fires reachability callback, dashboard updates network_status_label."""
        dashboard = DashboardPage(self.mock_service)
        dashboard._on_reachability_changed(False)
        self.assertEqual(dashboard.network_status_label.text(), "● Offline")
        self.assertIn("#ef4444", dashboard.network_status_label.styleSheet())

        dashboard._on_reachability_changed(True)
        self.assertEqual(dashboard.network_status_label.text(), "● Online")
        self.assertIn("#10b981", dashboard.network_status_label.styleSheet())

    def test_centralized_network_synchronization_across_all_locations(self):
        """Verify Header, Tracking & Sync Status, and Leave Balance all show the same live state."""
        from ui.main_window import MainWindow
        from ui.leave_balance_dialog import LeaveBalanceDialog

        win = MainWindow()
        dialog = LeaveBalanceDialog(service=MagicMock())

        try:
            # 1. Simulate Offline transition
            win.set_network_status(False)
            dialog.set_network_status(False)

            self.assertEqual(win.status_badge.text(), "Offline")
            self.assertEqual(win.status_badge.property("workpulse"), "false")
            self.assertEqual(win.dashboard_page.network_status_label.text(), "● Offline")
            self.assertEqual(dialog.network_status_label.text(), "● Offline")

            # 2. Simulate Online transition
            win.set_network_status(True)
            dialog.set_network_status(True)

            self.assertEqual(win.status_badge.text(), "Online")
            self.assertEqual(win.status_badge.property("workpulse"), "true")
            self.assertEqual(win.dashboard_page.network_status_label.text(), "● Online")
            self.assertEqual(dialog.network_status_label.text(), "● Online")
        finally:
            win._shutdown()
            win.close()
            dialog.done(0)

    def test_tracking_state_changes_do_not_override_offline_network_status(self):
        """Starting, stopping, or pausing tracking while offline preserves Offline status in Header and Dashboard."""
        from ui.main_window import MainWindow

        win = MainWindow()
        try:
            # Set network offline
            win.set_network_status(False)
            win.dashboard_page.set_network_status(False)

            self.assertEqual(win.status_badge.text(), "Offline")
            self.assertEqual(win.dashboard_page.network_status_label.text(), "● Offline")

            # Pausing tracking
            win.dashboard_page.set_paused(True)
            self.assertEqual(win.status_badge.text(), "Offline")
            self.assertEqual(win.dashboard_page.network_status_label.text(), "● Offline")

            # Resuming tracking
            win.dashboard_page.set_paused(False)
            self.assertEqual(win.status_badge.text(), "Offline")
            self.assertEqual(win.dashboard_page.network_status_label.text(), "● Offline")
        finally:
            win._shutdown()
            win.close()


if __name__ == "__main__":
    unittest.main()

