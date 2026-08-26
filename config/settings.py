"""Static application configuration and default values.

This module holds constants that are not user-editable (app name, poll
intervals, etc). User-editable preferences (idle threshold, start-with-
system, tracking-enabled, track-window-titles) live in the database and are
accessed through ``services.settings_service.SettingsService``.
"""

from __future__ import annotations

APP_NAME = "IHRMS Monitor"
APP_VERSION = "1.0.0"
ORG_NAME = "IHRMSMonitorApp"

# How often (in seconds) the tracker worker polls for the active application.
POLL_INTERVAL_SECONDS = 1.0

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
