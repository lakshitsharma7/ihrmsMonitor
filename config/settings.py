"""Static application configuration and default values.

This module holds constants that are not user-editable (app name, poll
intervals, etc). User-editable preferences (idle threshold, start-with-
system, tracking-enabled, track-window-titles) live in the database and are
accessed through ``services.settings_service.SettingsService``.
"""

from __future__ import annotations


import os
import sys
from pathlib import Path

APP_NAME = "Workpulse"
ORG_NAME = "WorkpulseApp"


def _read_pe_file_version(exe_path: str | Path) -> str | None:
    """Helper to extract FileVersion directly from a Windows PE binary."""
    try:
        import win32api

        info = win32api.GetFileVersionInfo(str(exe_path), "\\")
        ms = info.get("FileVersionMS", 0)
        ls = info.get("FileVersionLS", 0)
        v1, v2 = ms >> 16, ms & 0xFFFF
        v3, v4 = ls >> 16, ls & 0xFFFF
        if v1 == 0 and v2 == 0 and v3 == 0 and v4 == 0:
            return None
        if v4 == 0:
            return f"{v1}.{v2}.{v3}"
        return f"{v1}.{v2}.{v3}.{v4}"
    except Exception:
        return None


def get_running_app_version() -> str:
    """
    Return the authoritative running application version automatically.

    1. If running as a frozen executable (PyInstaller), inspects the embedded
       binary metadata of the current executable via win32api.GetFileVersionInfo.
    2. If running uncompiled (development / test), automatically checks the installed
       binary in %LOCALAPPDATA%\\Programs\\Workpulse\\Workpulse.exe, the local
       dist build, or VERSION / version.txt build descriptors.
    3. Never requires manual version maintenance in code or Settings.
    """
    # 1. Authoritative check on the running executable when frozen
    if getattr(sys, "frozen", False):
        v = _read_pe_file_version(sys.executable)
        if v:
            return v

    project_root = Path(__file__).resolve().parent.parent

    # 2. Check version descriptor files if present (authoritative in source/dev mode)
    for ver_file in ("VERSION", "version.txt"):
        vf = project_root / ver_file
        if vf.exists():
            try:
                txt = vf.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
            except Exception:
                pass

    # 3. Check installed application binary if available
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        for folder, exe_name in (("Workpulse", "Workpulse.exe"), ("iHRMS Monitor", "iHRMS Monitor.exe")):
            installed_exe = Path(local_app_data) / "Programs" / folder / exe_name
            if installed_exe.exists():
                v = _read_pe_file_version(installed_exe)
                if v:
                    return v

    return "2.0.2"


class _DynamicAppVersion(str):
    """String subclass that dynamically evaluates get_running_app_version() so imports never get stale."""

    def __str__(self) -> str:
        return get_running_app_version()

    def __repr__(self) -> str:
        return f"'{get_running_app_version()}'"

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)

    def __hash__(self) -> int:
        return hash(str(self))


# Dynamically resolved application version (never requires manual updates)
APP_VERSION = _DynamicAppVersion("2.0.2")


# How often (in seconds) the tracker worker polls for the active application.
POLL_INTERVAL_SECONDS = 1.0

# How often collected activity logs are sent to the Log API.
# This value is fully dynamic from the API (sync_interval_seconds) and is never hardcoded.
# SyncService and ActivityTracker dynamically respect the server-configured interval.
SYNC_INTERVAL_SECONDS = 300  # Initial fallback before first API configuration load

# Default idle threshold, in seconds, before a user is considered idle.
DEFAULT_IDLE_THRESHOLD_SECONDS = 3 * 60

# Default value for whether window titles are tracked in addition to the
# application name.
DEFAULT_TRACK_WINDOW_TITLES = True

# Default value for whether the app starts tracking automatically on launch.
DEFAULT_TRACKING_ENABLED = True

# Default value for whether the app starts with the OS.
DEFAULT_START_WITH_SYSTEM = True

# Minimum window-title-only change that should update (not replace) the
# current session, in seconds. Prevents rapid title flapping (e.g. browser
# tab titles updating a loading spinner) from being noisy - the session
# update itself is cheap, this is more about being explicit/tunable.
WINDOW_TITLE_UPDATE_DEBOUNCE_SECONDS = 0.0

# Supported OS minimum versions (informational; enforced loosely).
MIN_WINDOWS_VERSION = 10
MIN_MACOS_VERSION = 12
