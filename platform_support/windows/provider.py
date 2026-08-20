"""Windows implementation of :class:`platform_support.base.PlatformActivityProvider`."""

from __future__ import annotations

from platform_support.base import ActiveApplication, PlatformActivityProvider
from platform_support.windows import active_window, idle_detector
from utils.logger import get_logger

logger = get_logger(__name__)


class WindowsActivityProvider(PlatformActivityProvider):
    """Windows-backed activity provider using pywin32 and ctypes."""

    def get_active_application(self) -> ActiveApplication | None:
        return active_window.get_active_application()

    def get_idle_seconds(self) -> float:
        return idle_detector.get_idle_seconds()

    def supports_window_titles(self) -> bool:
        return True
