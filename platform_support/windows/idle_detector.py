"""Windows implementation of idle-time detection.

Uses the ``GetLastInputInfo`` Win32 API (via ``ctypes``) which returns the
tick count of the last keyboard/mouse input, system-wide.
"""

from __future__ import annotations

import ctypes

from utils.logger import get_logger

logger = get_logger(__name__)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]


def get_idle_seconds() -> float:
    """Return seconds since the last keyboard/mouse input on Windows.

    Returns 0.0 (i.e. "assume active") if the API call fails, so a
    transient failure never falsely marks a user idle.
    """
    try:
        last_input_info = _LASTINPUTINFO()
        last_input_info.cbSize = ctypes.sizeof(_LASTINPUTINFO)

        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input_info)):  # type: ignore[attr-defined]
            logger.warning("GetLastInputInfo failed")
            return 0.0

        millis_since_last_input = ctypes.windll.kernel32.GetTickCount() - last_input_info.dwTime  # type: ignore[attr-defined]
        return max(0.0, millis_since_last_input / 1000.0)
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error reading idle time on Windows")
        return 0.0
