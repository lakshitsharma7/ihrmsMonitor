"""macOS implementation of :class:`platform_support.base.PlatformActivityProvider`."""

from __future__ import annotations

from platform_support.base import ActiveApplication, PlatformActivityProvider
from platform_support.macos import active_window, idle_detector
from utils.logger import get_logger

logger = get_logger(__name__)


class MacOSActivityProvider(PlatformActivityProvider):
    """macOS-backed activity provider using PyObjC (AppKit/Quartz)."""

    def get_active_application(self) -> ActiveApplication | None:
        return active_window.get_active_application()

    def get_idle_seconds(self) -> float:
        return idle_detector.get_idle_seconds()

    def supports_window_titles(self) -> bool:
        # Capability exists, but requires the user to grant Screen
        # Recording/Accessibility permission at runtime - individual calls
        # may still return window_title=None.
        return True
