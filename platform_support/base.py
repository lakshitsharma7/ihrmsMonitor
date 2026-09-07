"""Common interface that all platform-specific activity providers implement.

Nothing outside the ``platform`` package should import ``WindowsActivityProvider``
or ``MacOSActivityProvider`` directly - always go through
``create_activity_provider()`` in ``platform/__init__.py`` and program against
``PlatformActivityProvider``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveApplication:
    """A snapshot of whatever application currently has OS focus.

    ``window_title`` may be ``None`` when the OS/permissions do not allow
    reading it (e.g. macOS Accessibility permission not granted) - callers
    must handle that gracefully rather than assuming it is always present.
    """

    application_name: str
    process_id: int | None
    window_title: str | None = None


class UnsupportedPlatformError(RuntimeError):
    """Raised when the application is run on an OS it does not support."""


class PlatformActivityProvider:
    """Abstract interface for OS-specific activity/idle detection.

    Every method must fail *safely*: on any internal error, implementations
    should log the problem and return ``None`` (or, for
    ``get_idle_seconds``, ``0``) rather than raising. The rest of the
    application relies on this contract to never crash because of a
    transient OS API failure.
    """

    def get_active_application(self) -> ActiveApplication | None:
        """Return the currently focused application, or ``None`` if unknown."""
        raise NotImplementedError

    def get_idle_seconds(self) -> float:
        """Return how many seconds the user has been idle (0 if active)."""
        raise NotImplementedError

    def supports_window_titles(self) -> bool:
        """Return whether this provider can ever report window titles.

        This is a capability hint for the UI/settings screen - it does not
        guarantee every call to ``get_active_application`` will include a
        title (permissions can still cause it to be ``None`` at runtime).
        """
        return True

    def reset_after_resume(self) -> None:
        """Reinitialize idle/activity detection after system resume from sleep."""
        pass

