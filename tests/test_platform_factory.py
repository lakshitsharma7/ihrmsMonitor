"""Tests for platform_support.create_activity_provider - the single OS branch point."""

from __future__ import annotations

import sys

import psutil  # noqa: F401 - imported here, before any sys.platform patching below,
# so it's cached in sys.modules. psutil's own __init__ branches on the *real*
# sys.platform to pick its OS backend; importing it fresh while a test has
# monkeypatched sys.platform to a spoofed value would make psutil itself
# blow up with NotImplementedError, which is a test artifact unrelated to
# our code under test.
import pytest

import platform_support as activity_platform
from platform_support.base import UnsupportedPlatformError


def test_unsupported_platform_raises(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(UnsupportedPlatformError):
        activity_platform.create_activity_provider()


def test_windows_platform_returns_windows_provider(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    provider = activity_platform.create_activity_provider()
    assert type(provider).__name__ == "WindowsActivityProvider"


def test_macos_platform_returns_macos_provider(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    provider = activity_platform.create_activity_provider()
    assert type(provider).__name__ == "MacOSActivityProvider"


def test_provider_calls_never_raise_when_native_libs_missing():
    """On this (Linux) test machine neither pywin32 nor PyObjC is installed.

    get_active_application()/get_idle_seconds() must degrade gracefully
    (return None / 0.0) rather than raising ImportError, per spec section 17.
    """
    import sys as _sys

    _sys.platform = "win32"
    try:
        from platform_support.windows.provider import WindowsActivityProvider

        p = WindowsActivityProvider()
        assert p.get_active_application() is None
        assert p.get_idle_seconds() == 0.0
    finally:
        _sys.platform = "linux"
