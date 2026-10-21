"""Real-time network connectivity and reachability monitor.

Provides dynamic, real-time detection of network/Internet reachability:
- Probes configured backend/API endpoints using direct TCP socket connections.
- Fast, short timeout to keep UI completely responsive.
- Signals / callbacks on connectivity state change (Online <-> Offline).
- Decoupled from sync/activity tracking, authentication, or running state.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

from utils.logger import get_logger

logger = get_logger(__name__)


class NetworkReachabilityMonitor:
    """Monitors active internet and backend network connectivity."""

    _instance: Optional[NetworkReachabilityMonitor] = None
    _lock = threading.Lock()

    def __new__(cls) -> NetworkReachabilityMonitor:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._is_online: bool = True
        self._listeners: List[Callable[[bool], None]] = []
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._check_interval: float = 2.0
        self._check_lock = threading.Lock()

    @property
    def is_online(self) -> bool:
        """Return the last known network reachability state."""
        return self._is_online

    def report_online(self) -> None:
        """Explicitly notify monitor that a network/API operation succeeded."""
        was_online = self._is_online
        self._is_online = True
        if not was_online:
            logger.info("Network connectivity confirmed active (reported Online)")
        self._notify_listeners(True)

    def report_offline(self) -> None:
        """Explicitly notify monitor that network connectivity was lost."""
        was_online = self._is_online
        self._is_online = False
        if was_online:
            logger.info("Network connectivity lost (reported Offline)")
        self._notify_listeners(False)

    def report_api_failure(self) -> None:
        """Called when an API request fails; quickly confirms reachability before marking offline."""
        if "unittest" in sys.modules or "pytest" in sys.modules:
            return
        if self._check_lock.locked():
            return

        def _check() -> None:
            self._perform_check(timeout=1.0)

        threading.Thread(target=_check, daemon=True).start()

    def register_listener(self, callback: Callable[[bool], None]) -> None:
        """Register a callback to be notified whenever connectivity state changes."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)
                try:
                    callback(self._is_online)
                except Exception:
                    pass

    def unregister_listener(self, callback: Callable[[bool], None]) -> None:
        """Remove a registered callback."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _get_targets(self) -> List[Tuple[str, int]]:
        """Collect target (host, port) endpoints from the configured backend."""
        targets: List[Tuple[str, int]] = []

        # 1. Configured backend API endpoint
        try:
            from config.api_config import ApiConfig
            base_url = None
            try:
                base_url = ApiConfig().base_url
            except Exception:
                pass
            if not base_url:
                try:
                    from PySide6.QtCore import QSettings
                    st = QSettings("Indovision", "iHRMSMonitor")
                    cached = st.value("ApiConfig/last_base_url")
                    if not cached:
                        cached = QSettings("iHRMS", "WorkPulse").value("ApiConfig/last_base_url")
                    if cached:
                        base_url = str(cached)
                except Exception:
                    pass
            if not base_url:
                try:
                    from services.secure_session import SessionStore
                    sess = SessionStore().load_session()
                    if sess and sess.get("base_url"):
                        base_url = sess.get("base_url")
                except Exception:
                    pass

            if base_url:
                parsed = urlparse(base_url)
                api_host = parsed.hostname
                api_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if api_host:
                    targets.append((api_host, api_port))
        except Exception:
            pass

        # 2. Configured verification / app controller URL
        try:
            from config.api_config import APP_CONTROLLER_URL
            if APP_CONTROLLER_URL:
                parsed = urlparse(APP_CONTROLLER_URL)
                ctrl_host = parsed.hostname
                ctrl_port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if ctrl_host and (ctrl_host, ctrl_port) not in targets:
                    targets.append((ctrl_host, ctrl_port))
        except Exception:
            pass

        if not targets:
            targets = [("info.indovisionservices.in", 443)]

        return targets

    @staticmethod
    def _probe_socket_target(host: str, port: int, timeout: float = 1.2) -> bool:
        """Attempt a direct TCP socket connection to a single (host, port)."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    def check_reachability(self, timeout: float = 1.2) -> bool:
        """
        Perform a reachability check against the configured backend endpoint.
        Returns True if the backend server is reachable, False otherwise.
        """
        targets = self._get_targets()
        for host, port in targets:
            if self._probe_socket_target(host, port, timeout=timeout):
                return True
        return False

    def _perform_check(self, timeout: float = 1.2) -> bool:
        """Internal helper to execute a check, update state, and notify listeners."""
        with self._check_lock:
            try:
                current_state = self.check_reachability(timeout=timeout)
                if current_state != self._is_online:
                    self._is_online = current_state
                    self._notify_listeners(current_state)
                return current_state
            except Exception as e:
                logger.debug("NetworkReachabilityMonitor check error: %s", e)
                if self._is_online:
                    self._is_online = False
                    self._notify_listeners(False)
                return False

    def start_monitoring(self, interval: float = 2.0) -> None:
        """Start background polling monitor if not already running."""
        if "unittest" in sys.modules or "pytest" in sys.modules:
            return

        self._check_interval = max(1.0, interval)
        if self._running:
            return

        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self) -> None:
        """Stop the background polling loop."""
        self._running = False

    def _monitor_loop(self) -> None:
        """Background thread loop polling network reachability."""
        while self._running:
            try:
                self._perform_check(timeout=1.5)
            except Exception as e:
                logger.debug("NetworkReachabilityMonitor loop error: %s", e)
            time.sleep(self._check_interval)

    def _notify_listeners(self, state: bool) -> None:
        """Notify all registered listeners."""
        for cb in list(self._listeners):
            try:
                cb(state)
            except Exception:
                pass
