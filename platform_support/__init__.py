"""Platform abstraction package.

Exposes a single factory, ``create_activity_provider()``, which is the only
place in the whole application that branches on operating system. Every
other module only ever talks to the ``PlatformActivityProvider`` interface.
"""

from __future__ import annotations

import sys

from platform_support.base import PlatformActivityProvider, UnsupportedPlatformError
from utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "PlatformActivityProvider",
    "UnsupportedPlatformError",
    "create_activity_provider",
]


def create_activity_provider() -> PlatformActivityProvider:
    """Return the correct :class:`PlatformActivityProvider` for this OS.

    This is the ONLY factory in the codebase that should branch on
    ``sys.platform``. All downstream code depends only on the returned
    object's interface.

    Raises:
        UnsupportedPlatformError: if running on an OS other than
            Windows or macOS.
    """
    if sys.platform.startswith("win"):
        logger.info("Detected platform: Windows")
        from platform_support.windows.provider import WindowsActivityProvider

        return WindowsActivityProvider()

    if sys.platform == "darwin":
        logger.info("Detected platform: macOS")
        from platform_support.macos.provider import MacOSActivityProvider

        return MacOSActivityProvider()

    logger.error("Unsupported platform detected: %s", sys.platform)
    raise UnsupportedPlatformError(
        "This version of iHRMS Monitor supports Windows and macOS."
    )
