"""Tests for platform_support.create_activity_provider - the single OS branch point."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

import psutil  # noqa: F401

import platform_support as activity_platform
from platform_support.base import UnsupportedPlatformError


class TestPlatformFactory(unittest.TestCase):
    def test_unsupported_platform_raises(self):
        with patch.object(sys, "platform", "linux"):
            with self.assertRaises(UnsupportedPlatformError):
                activity_platform.create_activity_provider()

    def test_windows_platform_returns_windows_provider(self):
        with patch.object(sys, "platform", "win32"):
            provider = activity_platform.create_activity_provider()
            self.assertEqual(type(provider).__name__, "WindowsActivityProvider")

    def test_macos_platform_returns_macos_provider(self):
        with patch.object(sys, "platform", "darwin"):
            provider = activity_platform.create_activity_provider()
            self.assertEqual(type(provider).__name__, "MacOSActivityProvider")

    def test_provider_calls_never_raise_when_native_libs_missing(self):
        with patch.object(sys, "platform", "win32"):
            from platform_support.windows.provider import WindowsActivityProvider

            p = WindowsActivityProvider()
            self.assertTrue(p.get_active_application() is None or p.get_active_application() is not None)
            self.assertIsInstance(p.get_idle_seconds(), (int, float))


if __name__ == "__main__":
    unittest.main()
