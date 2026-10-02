"""Windows implementation of idle-time detection.

Uses the ``GetLastInputInfo`` Win32 API (via ``ctypes``), augmented with
active mouse cursor workpulse, mouse button state verification, and
system resume/wake synchronization.
"""

from __future__ import annotations

import ctypes
import time

from utils.logger import get_logger

logger = get_logger(__name__)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


# Configure ctypes function prototypes
try:
    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint
    if hasattr(ctypes.windll.kernel32, "GetTickCount64"):
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
except Exception as _proto_err:
    logger.debug("Could not set GetTickCount prototype: %s", _proto_err)


# Internal state for workpulse active interactions across sleep/resume
_last_cursor_pos: tuple[int, int] | None = None
_last_interaction_mono: float = 0.0
_last_input_dw_time: int = 0
_resume_mono: float = 0.0


def reset_after_resume() -> None:
    """Reinitialize idle baseline when Windows resumes from sleep/hibernate.

    Ensures that pre-sleep idle tick counts are discarded, capturing a fresh
    baseline so the user's immediate interactions switch status to Active.
    """
    global _last_cursor_pos, _last_interaction_mono, _last_input_dw_time, _resume_mono
    now_mono = time.monotonic()
    _resume_mono = now_mono
    _last_interaction_mono = now_mono
    _last_input_dw_time = 0

    try:
        pt = _POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            _last_cursor_pos = (pt.x, pt.y)
        else:
            _last_cursor_pos = None
    except Exception:
        _last_cursor_pos = None

    logger.info("Windows idle detector reinitialized after system resume.")


def get_idle_seconds() -> float:
    """Return seconds since the last keyboard/mouse input on Windows.

    Returns 0.0 (i.e. 'assume active') if an API call fails or when user
    interaction is detected, ensuring normal user interaction immediately
    resumes active status.
    """
    global _last_cursor_pos, _last_interaction_mono, _last_input_dw_time, _resume_mono
    now_mono = time.monotonic()

    # 1. Direct mouse cursor position workpulse
    mouse_moved = False
    try:
        pt = _POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            curr_pos = (pt.x, pt.y)
            if _last_cursor_pos is not None and curr_pos != _last_cursor_pos:
                mouse_moved = True
            _last_cursor_pos = curr_pos
    except Exception:
        pass

    # 2. Direct mouse button state checks (VK_LBUTTON=0x01, VK_RBUTTON=0x02, VK_MBUTTON=0x04)
    button_pressed = False
    try:
        for vk in (0x01, 0x02, 0x04):
            if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                button_pressed = True
                break
    except Exception:
        pass

    # If physical mouse movement or button press is detected, user is active now
    if mouse_moved or button_pressed:
        _last_interaction_mono = now_mono
        return 0.0

    # 3. Query Win32 GetLastInputInfo
    try:
        last_input_info = _LASTINPUTINFO()
        last_input_info.cbSize = ctypes.sizeof(_LASTINPUTINFO)

        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input_info)):
            logger.warning("GetLastInputInfo failed")
            return 0.0

        curr_dw = ctypes.c_uint(ctypes.windll.kernel32.GetTickCount()).value
        input_dw = last_input_info.dwTime

        # If dwTime advanced since last check, user interacted with keyboard/mouse
        if _last_input_dw_time != 0 and input_dw != _last_input_dw_time:
            _last_interaction_mono = now_mono
        _last_input_dw_time = input_dw

        # Calculate difference using 32-bit unsigned wrapping arithmetic
        diff_ms = (curr_dw - input_dw) & 0xFFFFFFFF
        raw_idle_seconds = max(0.0, diff_ms / 1000.0)

        # 4. If system recently resumed from sleep, cap idle time to time since resume
        # Sleep duration must NEVER be counted as active or idle time
        if _resume_mono > 0:
            time_since_resume = max(0.0, now_mono - _resume_mono)
            if raw_idle_seconds > time_since_resume:
                raw_idle_seconds = time_since_resume

        # Also account for direct mouse cursor/button interaction timestamp
        if _last_interaction_mono > 0:
            time_since_interaction = max(0.0, now_mono - _last_interaction_mono)
            return min(raw_idle_seconds, time_since_interaction)

        return raw_idle_seconds

    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error reading idle time on Windows")
        return 0.0
