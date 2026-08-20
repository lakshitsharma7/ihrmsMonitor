"""Windows implementation of active-application detection.

Uses ``win32gui``/``win32process`` (pywin32) plus ``psutil`` to resolve the
foreground window into an :class:`~platform_support.base.ActiveApplication`.
"""

from __future__ import annotations

import psutil

from platform_support.base import ActiveApplication
from utils.logger import get_logger

logger = get_logger(__name__)


def get_active_application() -> ActiveApplication | None:
    """Return the foreground application on Windows, or ``None`` on failure.

    Never raises - any pywin32/psutil error is logged and swallowed so a
    single failed API call can never take down the tracker loop.
    """
    try:
        import win32gui  # type: ignore
        import win32process  # type: ignore
    except ImportError:
        logger.error("pywin32 is not installed; cannot detect active window")
        return None

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None

        window_title = win32gui.GetWindowText(hwnd) or None

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            logger.debug("Could not resolve PID for hwnd=%s", hwnd, exc_info=True)
            pid = None

        application_name = "Unknown"
        if pid:
            try:
                process = psutil.Process(pid)
                application_name = process.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                # The process may have exited between GetForegroundWindow and
                # here, or we may lack permission to inspect it. Fall back to
                # the window title so we still record *something* useful.
                logger.debug("Process %s vanished or is inaccessible", pid, exc_info=True)
                application_name = window_title or "Unknown"

        return ActiveApplication(
            application_name=application_name,
            process_id=pid,
            window_title=window_title,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error detecting active window on Windows")
        return None
