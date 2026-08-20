"""macOS implementation of active-application detection.

Uses ``NSWorkspace`` (PyObjC) to find the frontmost application and its PID,
and the Quartz window-list APIs to try to resolve that application's
frontmost window title. Reading window titles requires the "Screen
Recording" or "Accessibility" privacy permission on modern macOS - when that
permission has not been granted, Quartz simply omits the title, and we must
still return the application name/PID rather than fail outright.
"""

from __future__ import annotations

from platform_support.base import ActiveApplication
from utils.logger import get_logger

logger = get_logger(__name__)


def _get_frontmost_application() -> tuple[str, int | None] | None:
    """Return (application_name, process_id) for the frontmost app, or None."""
    try:
        from AppKit import NSWorkspace  # type: ignore
    except ImportError:
        logger.error("PyObjC (AppKit) is not installed; cannot detect active app")
        return None

    try:
        workspace = NSWorkspace.sharedWorkspace()
        app = workspace.frontmostApplication()
        if app is None:
            return None
        name = str(app.localizedName()) if app.localizedName() else "Unknown"
        pid = int(app.processIdentifier()) if app.processIdentifier() else None
        return name, pid
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error reading frontmost application on macOS")
        return None


def _get_window_title_for_pid(pid: int | None) -> str | None:
    """Best-effort lookup of the frontmost window title for a process.

    Returns None if the Screen Recording / Accessibility permission has not
    been granted, Quartz is unavailable, or no matching window is found -
    all of which are expected, non-fatal conditions on macOS.
    """
    if pid is None:
        return None

    try:
        from Quartz import (  # type: ignore
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
        )
    except ImportError:
        logger.debug("Quartz is not installed; window titles unavailable")
        return None

    try:
        window_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        if not window_list:
            return None

        for window in window_list:
            owner_pid = window.get("kCGWindowOwnerPID")
            if owner_pid != pid:
                continue
            title = window.get("kCGWindowName")
            if title:
                return str(title)
        return None
    except Exception:  # noqa: BLE001
        # Most commonly this means the Screen Recording permission has not
        # been granted. This is expected and must not crash the tracker.
        logger.debug("Could not read window title for pid=%s (likely missing permission)", pid)
        return None


def get_active_application() -> ActiveApplication | None:
    """Return the frontmost application on macOS, or ``None`` on failure.

    Never raises. Window title may legitimately be ``None`` when macOS
    privacy permissions have not been granted - the application name and
    PID are still returned so the tracker keeps working.
    """
    result = _get_frontmost_application()
    if result is None:
        return None

    application_name, pid = result
    window_title = _get_window_title_for_pid(pid)

    return ActiveApplication(
        application_name=application_name,
        process_id=pid,
        window_title=window_title,
    )
