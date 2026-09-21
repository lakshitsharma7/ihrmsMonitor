"""Cross-platform filesystem path helpers.

This module is the ONLY place in the application that knows about the
operating-system-specific rules for where application data and logs live.
Every other module (database, logging, settings) asks this module for a
path and never hardcodes an OS-specific location itself.

Notes:
    We intentionally use ``sys.platform`` rather than the standard-library
    ``platform`` module. Because this project ships its own top-level
    package named ``platform`` (see ``platform/``), importing the stdlib
    ``platform`` module from inside this project directory is fragile
    (Python may resolve ``platform`` to our local package instead of the
    standard library, since the script directory is placed on ``sys.path``).
    ``sys.platform`` is a simple string attribute on the ``sys`` module and
    has no such ambiguity, so it's used everywhere in this codebase instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Workpulse"


def is_windows() -> bool:
    """Return True when running on Windows."""
    return sys.platform.startswith("win")


def is_macos() -> bool:
    """Return True when running on macOS."""
    return sys.platform == "darwin"


def is_supported_platform() -> bool:
    """Return True if the current OS is one this application supports."""
    return is_windows() or is_macos()


def get_app_data_directory() -> Path:
    """Return the per-user application data directory, creating it if needed.

    Windows:
        %LOCALAPPDATA%\\Workpulse
    macOS:
        ~/Library/Application Support/Workpulse

    Raises:
        RuntimeError: if called on an unsupported operating system.
    """
    if is_windows():
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            # Fallback in case the environment variable is missing.
            base = str(Path.home() / "AppData" / "Local")
        directory = Path(base) / APP_NAME
    elif is_macos():
        directory = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        raise RuntimeError(
            "This version of Workpulse supports Windows and macOS."
        )

    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_data_directory() -> Path:
    """Return the data directory for pending activity/log database, creating it if needed."""
    directory = get_app_data_directory() / "data"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_database_path() -> Path:
    """Return the full path to the SQLite database file in data directory."""
    target = get_data_directory() / "activity_tracker.db"

    # Smooth automatic migration from legacy locations if target doesn't exist yet
    if not target.exists():
        local_base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        legacy_candidates = [
            get_app_data_directory() / "activity_tracker.db",
            local_base / "iHRMS Monitor" / "data" / "activity_tracker.db",
            local_base / "iHRMS Monitor" / "activity_tracker.db",
            local_base / "ActivityTracker" / "activity_tracker.db",
        ]
        for leg in legacy_candidates:
            if leg.exists():
                try:
                    import shutil
                    shutil.copy2(leg, target)
                    break
                except Exception:
                    pass

    return target


def get_logs_directory() -> Path:
    """Return the logs directory, creating it if needed."""
    directory = get_app_data_directory() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_log_file_path() -> Path:
    """Return the full path to the application log file."""
    return get_logs_directory() / "activity_tracker.log"


def get_screenshots_directory() -> Path:
    """Return the per-user screenshots directory, creating it if needed."""
    directory = get_app_data_directory() / "screenshots"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_updates_directory() -> Path:
    """Return the per-user updates download directory, creating it if needed."""
    directory = get_app_data_directory() / "updates"
    directory.mkdir(parents=True, exist_ok=True)
    return directory

