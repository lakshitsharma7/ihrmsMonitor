"""macOS implementation of idle-time detection.

Uses Quartz's ``CGEventSourceSecondsSinceLastEventType`` which reports
seconds since the last HID (keyboard/mouse) event, system-wide, and does
not require any special privacy permission.
"""

from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)


def get_idle_seconds() -> float:
    """Return seconds since the last keyboard/mouse input on macOS.

    Returns 0.0 (i.e. "assume active") if the API is unavailable or fails,
    so a transient failure never falsely marks a user idle.
    """
    try:
        from Quartz import (  # type: ignore
            CGEventSourceSecondsSinceLastEventType,
            kCGAnyInputEventType,
            kCGEventSourceStateHIDSystemState,
        )
    except ImportError:
        logger.error("PyObjC (Quartz) is not installed; cannot detect idle time")
        return 0.0

    try:
        idle_seconds = CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateHIDSystemState, kCGAnyInputEventType
        )
        return max(0.0, float(idle_seconds))
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error reading idle time on macOS")
        return 0.0
