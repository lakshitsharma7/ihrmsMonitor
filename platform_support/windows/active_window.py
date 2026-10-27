"""Windows implementation of active-application detection.

Uses ``win32gui``/``win32process`` (pywin32) plus ``psutil`` to resolve the
foreground window into an :class:`~platform_support.base.ActiveApplication`.
"""

from __future__ import annotations

import psutil

from platform_support.base import ActiveApplication
from utils.logger import get_logger

logger = get_logger(__name__)


def is_workstation_locked() -> bool:
    """Return True if the Windows workstation is currently locked or secure desktop is active.

    Uses OpenInputDesktop + SwitchDesktop. When the workstation is locked (Win + L)
    or UAC secure desktop is active, SwitchDesktop fails because the user desktop
    is not the active input desktop.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hDesk = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP = 0x0100
        if not hDesk:
            return True
        is_switchable = user32.SwitchDesktop(hDesk)
        user32.CloseDesktop(hDesk)
        return not bool(is_switchable)
    except Exception:
        return False


def get_active_application() -> ActiveApplication | None:
    """Return the foreground application on Windows, or ``None`` on failure.

    Never raises - any pywin32/psutil error is logged and swallowed so a
    single failed API call can never take down the tracker loop.
    """
    if is_workstation_locked():
        return None

    hwnd = 0
    window_title = None
    pid = None

    try:
        import win32gui  # type: ignore
        import win32process  # type: ignore

        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            window_title = win32gui.GetWindowText(hwnd) or None
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = None
    except Exception:
        # Fallback to ctypes Win32 API if pywin32 is missing or has DLL errors
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    window_title = buff.value or None
                dw_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dw_pid))
                pid = dw_pid.value if dw_pid.value > 0 else None
        except Exception as ct_err:
            logger.debug("ctypes active window detection error: %s", ct_err)

    if not hwnd:
        return None

    try:
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

        # Do not track Windows lock screen, logon UI, or screensaver as user application
        lock_binaries = ("lockapp.exe", "logonui.exe", "screensaver.exe")
        if application_name and application_name.lower() in lock_binaries:
            return None

        return ActiveApplication(
            application_name=application_name,
            process_id=pid,
            window_title=window_title,
            window_handle=hwnd,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error detecting active window on Windows")
        return None
