"""Screenshot capture and compression configuration.

Provides a modular, isolated configuration mechanism for screenshot capture
behavior and compression parameters in iHRMS Desktop.

Default local configuration:
{
  "screenshot_settings": {
    "enabled": true,
    "capture_mode": "both",
    "capture_on_window_change": true,
    "interval_minutes": 30,
    "max_size_kb": 100
  }
}

This module is designed to be self-contained so that a future backend API
endpoint can dynamically supply settings via ``apply_api_screenshot_config()``
without requiring any changes to capture, compression, or tracking logic.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)


# Valid capture modes
VALID_CAPTURE_MODES = ("window_change", "interval", "both")


def _coerce_bool(val: Any, default: bool) -> bool:
    """Coerce various boolean representations (strings, ints) safely."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        cleaned = val.strip().lower()
        if cleaned in ("true", "1", "yes", "t", "y", "enable", "enabled", "on"):
            return True
        if cleaned in ("false", "0", "no", "f", "n", "disable", "disabled", "off"):
            return False
    return default


def _coerce_float(val: Any, default: float, min_val: float = 0.0) -> float:
    """Coerce numeric values to float with validation."""
    if val is None:
        return default
    try:
        f = float(val)
        return max(min_val, f)
    except (ValueError, TypeError):
        return default


def _coerce_int(val: Any, default: int, min_val: int = 1) -> int:
    """Coerce numeric values to integer with validation."""
    if val is None:
        return default
    try:
        i = int(val)
        return max(min_val, i)
    except (ValueError, TypeError):
        return default


@dataclass
class ScreenshotConfig:
    """Configuration settings for screenshot capture and compression.

    Attributes:
        enabled: Master switch for screenshot capture. Default True.
        capture_mode: Trigger mode: 'window_change', 'interval', or 'both'. Default 'both'.
        capture_on_window_change: Enable capture when the active window changes. Default True.
        interval_minutes: Interval in minutes between periodic captures
            of the same active window. Default 30.0 minutes.
        max_size_kb: Strict ceiling for screenshot size in KB. Default 100 KB.
        compression_enabled: Enable screenshot compression. Default True.
        delete_if_compression_fails: Delete local screenshot if compression cannot
            reach <= max_size_kb. Default True.
    """

    enabled: bool = True
    capture_mode: str = "both"
    capture_on_window_change: bool = True
    interval_minutes: float = 30.0
    max_size_kb: int = 100
    compression_enabled: bool = True
    delete_if_compression_fails: bool = True

    def __init__(
        self,
        enabled: bool = True,
        capture_mode: str = "both",
        capture_on_window_change: bool = True,
        interval_minutes: float = 30.0,
        max_size_kb: int = 100,
        compression_enabled: bool = True,
        delete_if_compression_fails: bool = True,
        screenshot_enabled: bool | None = None,
        screenshot_interval_minutes: float | None = None,
        max_screenshot_size_kb: int | None = None,
        min_screenshot_size_kb: int | None = None,
        **kwargs: Any,
    ) -> None:
        if screenshot_enabled is not None:
            enabled = screenshot_enabled
        if screenshot_interval_minutes is not None:
            interval_minutes = screenshot_interval_minutes
        if max_screenshot_size_kb is not None:
            max_size_kb = max_screenshot_size_kb

        self.enabled = _coerce_bool(enabled, True)
        self.capture_mode = str(capture_mode).strip().lower()
        self.capture_on_window_change = _coerce_bool(capture_on_window_change, True)
        self.interval_minutes = _coerce_float(interval_minutes, 30.0)
        self.max_size_kb = _coerce_int(max_size_kb, 100, min_val=1)
        self.compression_enabled = _coerce_bool(compression_enabled, True)
        self.delete_if_compression_fails = _coerce_bool(delete_if_compression_fails, True)
        self.validate()

    def validate(self) -> None:
        """Ensure settings conform to allowed values and bounds."""
        if self.capture_mode not in VALID_CAPTURE_MODES:
            logger.warning(
                "Invalid capture_mode '%s'; defaulting to 'both'",
                self.capture_mode,
            )
            self.capture_mode = "both"

        if self.interval_minutes <= 0:
            self.interval_minutes = 30.0

        if self.max_size_kb <= 0:
            self.max_size_kb = 100

    # Backwards-compatibility aliases and properties
    @property
    def screenshot_enabled(self) -> bool:
        """Alias for enabled."""
        return self.enabled

    @screenshot_enabled.setter
    def screenshot_enabled(self, val: bool) -> None:
        self.enabled = val

    @property
    def screenshot_interval_minutes(self) -> float:
        """Alias for interval_minutes."""
        return self.interval_minutes

    @screenshot_interval_minutes.setter
    def screenshot_interval_minutes(self, val: float) -> None:
        self.interval_minutes = val

    @property
    def max_screenshot_size_kb(self) -> int:
        """Alias for max_size_kb."""
        return self.max_size_kb

    @max_screenshot_size_kb.setter
    def max_screenshot_size_kb(self, val: int) -> None:
        self.max_size_kb = val

    @property
    def min_screenshot_size_kb(self) -> int:
        """Target minimum in KB (0 by default; preserves smaller screenshots)."""
        return 0

    @min_screenshot_size_kb.setter
    def min_screenshot_size_kb(self, val: int) -> None:
        pass

    @property
    def max_size_bytes(self) -> int:
        """Strict maximum in bytes (ceiling)."""
        return int(self.max_size_kb * 1024)

    @property
    def max_screenshot_bytes(self) -> int:
        """Alias for max_size_bytes."""
        return self.max_size_bytes

    @property
    def min_screenshot_bytes(self) -> int:
        """Target minimum in bytes."""
        return 0

    @property
    def interval_seconds(self) -> float:
        """Same-window interval in seconds."""
        return float(self.interval_minutes * 60.0)

    def should_capture_on_window_change(self) -> bool:
        """Determine if a screenshot should be captured when active window changes."""
        if not self.enabled:
            return False
        if not self.capture_on_window_change:
            return False
        return self.capture_mode in ("window_change", "both")

    def should_capture_on_interval(self) -> bool:
        """Determine if periodic interval screenshot capture is enabled for same active window."""
        if not self.enabled:
            return False
        return self.capture_mode in ("interval", "both")

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to standard dictionary."""
        return {
            "screenshot_settings": {
                "enabled": self.enabled,
                "capture_mode": self.capture_mode,
                "capture_on_window_change": self.capture_on_window_change,
                "interval_minutes": self.interval_minutes,
                "max_size_kb": self.max_size_kb,
            }
        }

    def update_from_dict(self, data: dict[str, Any]) -> None:
        """Safely update configuration from a dictionary (e.g. local config or future API response).

        Ignores unknown keys and coerces values safely without raising exceptions.
        """
        if not isinstance(data, dict):
            return

        # Unwrap root wrapper if present
        if "screenshot_settings" in data and isinstance(data["screenshot_settings"], dict):
            data = data["screenshot_settings"]

        if "enabled" in data:
            self.enabled = _coerce_bool(data["enabled"], self.enabled)
        elif "screenshot_enabled" in data:
            self.enabled = _coerce_bool(data["screenshot_enabled"], self.enabled)

        if "capture_mode" in data:
            mode = str(data["capture_mode"]).strip().lower()
            if mode in VALID_CAPTURE_MODES:
                self.capture_mode = mode
            else:
                logger.warning("Invalid capture_mode '%s'; defaulting to 'both'", mode)
                self.capture_mode = "both"

        if "interval_minutes" in data:
            val = _coerce_float(data["interval_minutes"], 30.0)
            self.interval_minutes = val if val > 0 else 30.0
        elif "screenshot_interval_minutes" in data:
            val = _coerce_float(data["screenshot_interval_minutes"], 30.0)
            self.interval_minutes = val if val > 0 else 30.0
        elif "capture_interval_minutes" in data:
            val = _coerce_float(data["capture_interval_minutes"], 30.0)
            self.interval_minutes = val if val > 0 else 30.0
        elif "screenshot_interval_seconds" in data:
            sec = _coerce_float(data["screenshot_interval_seconds"], 0.0)
            self.interval_minutes = sec / 60.0 if sec > 0 else 30.0

        if "max_size_kb" in data:
            val = _coerce_int(
                data["max_size_kb"],
                100,
                min_val=0,
            )
            self.max_size_kb = val if val > 0 else 100
        elif "max_screenshot_size_kb" in data:
            val = _coerce_int(
                data["max_screenshot_size_kb"],
                100,
                min_val=0,
            )
            self.max_size_kb = val if val > 0 else 100

        if "compression_enabled" in data:
            self.compression_enabled = _coerce_bool(
                data["compression_enabled"], self.compression_enabled
            )

        if "delete_if_compression_fails" in data:
            self.delete_if_compression_fails = _coerce_bool(
                data["delete_if_compression_fails"], self.delete_if_compression_fails
            )

        if "capture_on_window_change" in data:
            self.capture_on_window_change = _coerce_bool(
                data["capture_on_window_change"], self.capture_on_window_change
            )

        self.validate()
        logger.info(
            "ScreenshotConfig updated: enabled=%s mode=%s on_change=%s "
            "interval=%.1fm max_size=%dKB compress=%s delete_on_fail=%s",
            self.enabled,
            self.capture_mode,
            self.capture_on_window_change,
            self.interval_minutes,
            self.max_size_kb,
            self.compression_enabled,
            self.delete_if_compression_fails,
        )


def load_local_screenshot_config() -> ScreenshotConfig:
    """Read screenshot configuration from local file or return defaults.

    Checks:
    1. Local app data directory: screenshot_settings.json
    2. Project config directory: screenshot_settings.json
    3. Project root: screenshot_settings.json
    4. Falls back to default values.
    """
    config = ScreenshotConfig()
    search_paths = []
    try:
        from utils.paths import get_app_data_directory
        search_paths.append(get_app_data_directory() / "screenshot_settings.json")
    except Exception:
        pass

    project_root = Path(__file__).resolve().parent.parent
    search_paths.append(project_root / "config" / "screenshot_settings.json")
    search_paths.append(project_root / "screenshot_settings.json")

    for path in search_paths:
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8")
                loaded = json.loads(content)
                if isinstance(loaded, dict):
                    config.update_from_dict(loaded)
                    logger.info("Loaded local screenshot settings from %s", path)
                    break
            except Exception as err:
                logger.warning("Could not read local screenshot config %s: %s", path, err)

    return config


# ==============================================================
# GLOBAL CONFIGURATION SINGLETON & FUTURE API INTEGRATION HOOK
# ==============================================================

_config_lock = threading.Lock()
_global_screenshot_config: ScreenshotConfig | None = None


def get_screenshot_config() -> ScreenshotConfig:
    """Return the global active ScreenshotConfig singleton."""
    global _global_screenshot_config
    if _global_screenshot_config is None:
        with _config_lock:
            if _global_screenshot_config is None:
                _global_screenshot_config = load_local_screenshot_config()
    return _global_screenshot_config


def set_screenshot_config(config: ScreenshotConfig) -> None:
    """Replace the global active ScreenshotConfig."""
    global _global_screenshot_config
    with _config_lock:
        _global_screenshot_config = config


def reset_screenshot_config() -> ScreenshotConfig:
    """Reset the global ScreenshotConfig to clean defaults."""
    global _global_screenshot_config
    with _config_lock:
        _global_screenshot_config = ScreenshotConfig()
    return _global_screenshot_config


def apply_api_screenshot_config(api_data: dict[str, Any]) -> ScreenshotConfig:
    """Entry point for future API integration to populate screenshot settings.

    Accepts arbitrary key-value mappings from backend configuration responses
    and safely updates the active ScreenshotConfig without requiring any capture logic changes.

    Example future usage in sync_service.fetch_settings():
        settings_data = response.json().get('data', {})
        apply_api_screenshot_config(settings_data)
    """
    config = get_screenshot_config()
    config.update_from_dict(api_data)
    return config
