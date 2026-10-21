"""macOS Screen Recording permission management via CoreGraphics ctypes binding.

This module is the ONLY place that calls CGPreflightScreenCaptureAccess()
and CGRequestScreenCaptureAccess(). It is completely isolated from the
auto-update pipeline (UpdateService, UpdateStateManager, UpdatePipelineWorker).

On Windows / Linux this module is a no-op — all public functions return True
so the rest of the codebase needs zero platform guards.

macOS TCC relaunch requirement
--------------------------------
When a user grants Screen Recording permission for the first time, macOS
requires the app to quit and reopen before the permission is effective in the
existing process. This module coordinates that relaunch:

  1. ``request_and_prompt()`` opens the System Settings Privacy pane and
     shows the user an instruction dialog.
  2. The user enables iHRMS Desktop in System Settings.
  3. Clicking "Quit & Reopen" calls ``relaunch_application()``.
  4. On reopen, ``has_screen_recording_permission()`` returns True.
  5. Screenshot tracking starts automatically.

A persistent restart-counter in AppData prevents infinite relaunch loops
if the user never actually enables the permission.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Tuple

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_RELAUNCHES = 2            # Give up relaunch loop after this many attempts
_RELAUNCH_COOLDOWN_SECONDS = 90  # Window within which MAX_RELAUNCHES applies

_PRIVACY_PANEL_URL = (
    "x-apple.systempreferences:"
    "com.apple.preference.security?Privacy_ScreenCapture"
)
_STATE_FILENAME = "permission_relaunch_state.json"


# ── Persistent relaunch-loop guard ────────────────────────────────────────────

def _get_state_path() -> Path:
    """Return path to the persistent relaunch state JSON file."""
    try:
        from utils.paths import get_app_data_directory
        p = get_app_data_directory() / _STATE_FILENAME
    except Exception:
        p = Path.home() / ".workpulse" / _STATE_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_state() -> dict:
    """Load the persistent relaunch state, returning defaults on error."""
    try:
        data = json.loads(_get_state_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"count": 0, "first_ts": 0.0}


def _save_state(state: dict) -> None:
    try:
        _get_state_path().write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass


def reset_relaunch_state() -> None:
    """Call once permission is confirmed to clear the restart counter."""
    _save_state({"count": 0, "first_ts": 0.0})


def can_relaunch() -> Tuple[bool, str]:
    """Check whether a permission-triggered relaunch is safe.

    Returns (True, "") when a relaunch may proceed.
    Returns (False, reason) when the relaunch counter is exhausted.
    """
    if sys.platform != "darwin":
        return True, ""
    state = _load_state()
    count: int = state.get("count", 0)
    first_ts: float = state.get("first_ts", 0.0)
    now = time.monotonic()
    if count == 0 or (now - first_ts) >= _RELAUNCH_COOLDOWN_SECONDS:
        # Counter expired or first time – safe to relaunch
        return True, ""
    if count >= _MAX_RELAUNCHES:
        return (
            False,
            f"Screen Recording permission relaunch attempted {count} times "
            f"without success. Please manually enable iHRMS Desktop in "
            f"System Settings > Privacy & Security > Screen Recording, "
            f"then reopen the app.",
        )
    return True, ""


def _record_relaunch() -> None:
    state = _load_state()
    count: int = state.get("count", 0)
    first_ts: float = state.get("first_ts", 0.0)
    now = time.monotonic()
    if count == 0 or (now - first_ts) >= _RELAUNCH_COOLDOWN_SECONDS:
        _save_state({"count": 1, "first_ts": now})
    else:
        _save_state({"count": count + 1, "first_ts": first_ts})


# ── CoreGraphics ctypes binding ───────────────────────────────────────────────

_cg_lib = None


def _get_cg_lib():
    """Lazily load CoreGraphics.framework via ctypes (macOS only)."""
    global _cg_lib  # noqa: PLW0603
    if _cg_lib is not None:
        return _cg_lib
    if sys.platform != "darwin":
        return None
    import ctypes
    try:
        _cg_lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        # CGPreflightScreenCaptureAccess() -> bool (macOS 10.15+)
        _cg_lib.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        _cg_lib.CGPreflightScreenCaptureAccess.argtypes = []
        # CGRequestScreenCaptureAccess() -> bool (macOS 10.15+)
        _cg_lib.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        _cg_lib.CGRequestScreenCaptureAccess.argtypes = []
    except Exception as exc:
        logger.warning("Could not load CoreGraphics for permission check: %s", exc)
        _cg_lib = None
    return _cg_lib


# ── Public API ────────────────────────────────────────────────────────────────

def has_screen_recording_permission() -> bool:
    """Return True if the process already has Screen Recording permission.

    On Windows / Linux always returns True.
    On macOS uses CGPreflightScreenCaptureAccess() (does NOT prompt the user).
    """
    if sys.platform != "darwin":
        return True
    lib = _get_cg_lib()
    if lib is None:
        # Cannot determine – assume granted to avoid blocking Windows builds
        logger.debug("CoreGraphics unavailable; assuming Screen Recording permission granted")
        return True
    try:
        result: bool = bool(lib.CGPreflightScreenCaptureAccess())
        logger.debug("CGPreflightScreenCaptureAccess() -> %s", result)
        return result
    except Exception as exc:
        logger.warning("CGPreflightScreenCaptureAccess() raised: %s", exc)
        return True  # Fail-open so capture is attempted


def request_screen_recording_permission() -> bool:
    """Trigger the system TCC permission prompt.

    This registers the app with macOS TCC and returns True if granted.
    On macOS Catalina+ the permission usually does NOT take effect in the
    running process – the user must quit & reopen the app after granting.
    """
    if sys.platform != "darwin":
        return True
    lib = _get_cg_lib()
    if lib is None:
        return True
    try:
        result: bool = bool(lib.CGRequestScreenCaptureAccess())
        logger.info("CGRequestScreenCaptureAccess() -> %s", result)
        return result
    except Exception as exc:
        logger.warning("CGRequestScreenCaptureAccess() raised: %s", exc)
        return False


def open_screen_recording_settings() -> bool:
    """Open macOS System Settings › Privacy & Security › Screen Recording.

    Returns True if the open command succeeded.
    """
    if sys.platform != "darwin":
        return False
    try:
        subprocess.Popen(["open", _PRIVACY_PANEL_URL])
        return True
    except Exception as exc:
        logger.warning("Could not open Screen Recording settings: %s", exc)
        return False


def relaunch_application() -> None:
    """Cleanly stop all background workers and relaunch iHRMS Desktop.

    This is called by the UI after the user enables Screen Recording in
    System Settings and clicks "Quit & Reopen". It must NEVER touch
    UpdateService, UpdateStateManager, UpdatePipelineWorker, or the
    update_button label – those are exclusively auto-update concerns.
    """
    _record_relaunch()
    logger.info("MacPermissionService: launching new iHRMS Desktop instance before quitting")

    try:
        # Prefer the running bundle (.app) so the correct macOS process
        # identity (bundle ID, entitlements, TCC record) is preserved.
        if getattr(sys, "frozen", False):
            # Inside a PyInstaller .app bundle: sys.executable is
            # Contents/MacOS/Workpulse; the bundle root is three levels up
            bundle = Path(sys.executable).resolve()
            # Traverse up to .app
            for _ in range(5):
                bundle = bundle.parent
                if bundle.name.endswith(".app"):
                    break
            if bundle.name.endswith(".app"):
                logger.info("Relaunching bundle: %s", bundle)
                subprocess.Popen(["open", "-n", str(bundle)])
            else:
                # Fallback: re-exec the binary directly
                subprocess.Popen([sys.executable] + sys.argv[1:])
        else:
            # Development mode: re-exec python interpreter
            subprocess.Popen([sys.executable] + sys.argv)
    except Exception as exc:
        logger.error("Could not launch new iHRMS Desktop instance: %s", exc)

    # Release QLockFile so the new instance is not blocked by the instance guard
    try:
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is not None:
            lf = getattr(app, "_instance_lock", None)
            if lf is not None:
                lf.unlock()
    except Exception:
        pass

    # Stop the QApplication event loop cleanly; this triggers aboutToQuit
    # which calls MainWindow._shutdown() ensuring the tracker QThread exits
    # properly and avoids QThreadStorage warnings.
    try:
        from PySide6.QtWidgets import QApplication
        qapp = QApplication.instance()
        if qapp is not None:
            qapp.quit()
            return
    except Exception:
        pass

    # Hard exit only as final fallback
    sys.exit(0)
