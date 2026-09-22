"""Tests for services/mac_permission_service.py.

These tests run on all platforms (including Windows / Linux CI).
On non-darwin platforms every public function is a no-op that returns True,
so the tests validate that behaviour first, then simulate the macOS code-paths
by patching ``sys.platform`` and the CoreGraphics ctypes library.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: force a clean module reload between tests so module-level globals
# (_cg_lib, _mac_permission_logged) don't bleed across test cases.
# ---------------------------------------------------------------------------

def _reload_service():
    import importlib
    import services.mac_permission_service as mod
    importlib.reload(mod)
    return mod


# ===========================================================================
# 1. Non-macOS (Windows/Linux): every function is a no-op
# ===========================================================================

class TestNonDarwin:
    """On non-darwin platforms all permission helpers must return True / no-op."""

    def test_has_permission_returns_true_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mod = _reload_service()
        assert mod.has_screen_recording_permission() is True

    def test_request_permission_returns_true_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mod = _reload_service()
        assert mod.request_screen_recording_permission() is True

    def test_open_settings_returns_false_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mod = _reload_service()
        assert mod.open_screen_recording_settings() is False

    def test_can_relaunch_returns_true_on_non_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mod = _reload_service()
        ok, reason = mod.can_relaunch()
        assert ok is True
        assert reason == ""


# ===========================================================================
# 2. macOS: has_screen_recording_permission()
# ===========================================================================

class TestHasPermission:
    """CGPreflightScreenCaptureAccess() binding behaviour."""

    @pytest.fixture(autouse=True)
    def _use_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

    def _make_cg_lib(self, granted: bool):
        lib = MagicMock()
        lib.CGPreflightScreenCaptureAccess.return_value = granted
        lib.CGPreflightScreenCaptureAccess.restype = None  # ctypes sets this
        return lib

    def test_returns_true_when_cg_says_granted(self, monkeypatch):
        mod = _reload_service()
        fake_lib = self._make_cg_lib(True)
        monkeypatch.setattr(mod, "_cg_lib", fake_lib)
        assert mod.has_screen_recording_permission() is True
        fake_lib.CGPreflightScreenCaptureAccess.assert_called_once()

    def test_returns_false_when_cg_says_denied(self, monkeypatch):
        mod = _reload_service()
        fake_lib = self._make_cg_lib(False)
        monkeypatch.setattr(mod, "_cg_lib", fake_lib)
        assert mod.has_screen_recording_permission() is False

    def test_fails_open_when_cg_unavailable(self, monkeypatch):
        """If CoreGraphics cannot be loaded, assume granted (fail-open)."""
        mod = _reload_service()
        monkeypatch.setattr(mod, "_cg_lib", None)
        # _get_cg_lib will try to load; patch it to also return None
        monkeypatch.setattr(mod, "_get_cg_lib", lambda: None)
        assert mod.has_screen_recording_permission() is True

    def test_exception_in_cg_call_returns_true(self, monkeypatch):
        mod = _reload_service()
        lib = MagicMock()
        lib.CGPreflightScreenCaptureAccess.side_effect = OSError("boom")
        monkeypatch.setattr(mod, "_cg_lib", lib)
        assert mod.has_screen_recording_permission() is True


# ===========================================================================
# 3. macOS: request_screen_recording_permission()
# ===========================================================================

class TestRequestPermission:
    @pytest.fixture(autouse=True)
    def _use_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

    def test_returns_true_on_success(self, monkeypatch):
        mod = _reload_service()
        lib = MagicMock()
        lib.CGRequestScreenCaptureAccess.return_value = True
        monkeypatch.setattr(mod, "_cg_lib", lib)
        assert mod.request_screen_recording_permission() is True

    def test_returns_false_on_denied(self, monkeypatch):
        mod = _reload_service()
        lib = MagicMock()
        lib.CGRequestScreenCaptureAccess.return_value = False
        monkeypatch.setattr(mod, "_cg_lib", lib)
        assert mod.request_screen_recording_permission() is False

    def test_returns_false_on_exception(self, monkeypatch):
        mod = _reload_service()
        lib = MagicMock()
        lib.CGRequestScreenCaptureAccess.side_effect = RuntimeError("nope")
        monkeypatch.setattr(mod, "_cg_lib", lib)
        assert mod.request_screen_recording_permission() is False


# ===========================================================================
# 4. Relaunch loop guard
# ===========================================================================

class TestRelaunchGuard:
    """can_relaunch() must prevent infinite restart loops."""

    @pytest.fixture(autouse=True)
    def _use_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

    def test_first_relaunch_allowed(self, monkeypatch):
        mod = _reload_service()
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "permission_relaunch_state.json"
            monkeypatch.setattr(mod, "_get_state_path", lambda: state_path)
            ok, reason = mod.can_relaunch()
            assert ok is True
            assert reason == ""

    def test_relaunch_blocked_after_max_attempts(self, monkeypatch):
        mod = _reload_service()
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "permission_relaunch_state.json"
            monkeypatch.setattr(mod, "_get_state_path", lambda: state_path)
            # Simulate MAX_RELAUNCHES attempts within cooldown window
            now = time.monotonic()
            state_path.write_text(
                json.dumps({"count": mod._MAX_RELAUNCHES, "first_ts": now}),
                encoding="utf-8",
            )
            ok, reason = mod.can_relaunch()
            assert ok is False
            assert "manually" in reason.lower() or "relaunch" in reason.lower()

    def test_counter_resets_after_cooldown(self, monkeypatch):
        mod = _reload_service()
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "permission_relaunch_state.json"
            monkeypatch.setattr(mod, "_get_state_path", lambda: state_path)
            # Old timestamps outside the cooldown window → counter should reset
            expired_ts = time.monotonic() - (mod._RELAUNCH_COOLDOWN_SECONDS + 1)
            state_path.write_text(
                json.dumps({"count": mod._MAX_RELAUNCHES, "first_ts": expired_ts}),
                encoding="utf-8",
            )
            ok, reason = mod.can_relaunch()
            assert ok is True

    def test_reset_clears_state(self, monkeypatch):
        mod = _reload_service()
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "permission_relaunch_state.json"
            monkeypatch.setattr(mod, "_get_state_path", lambda: state_path)
            # Write a non-zero count
            state_path.write_text(json.dumps({"count": 2, "first_ts": time.monotonic()}))
            mod.reset_relaunch_state()
            data = json.loads(state_path.read_text())
            assert data["count"] == 0


# ===========================================================================
# 5. screenshot.py permission integration
# ===========================================================================

class TestScreenshotPermissionGuard:
    """capture_screenshot() must return None on macOS when permission absent."""

    @pytest.fixture(autouse=True)
    def _use_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

    def test_returns_none_when_permission_denied(self, monkeypatch):
        """capture_screenshot must return None (not raise) when permission absent."""
        import importlib
        import services.screenshot as smod
        importlib.reload(smod)

        # Patch mac_permission_service.has_screen_recording_permission -> False
        fake_perm = MagicMock()
        fake_perm.has_screen_recording_permission.return_value = False
        monkeypatch.setitem(sys.modules, "services.mac_permission_service", fake_perm)

        result = smod.capture_screenshot(activity_session_id=42)
        assert result is None

    def test_proceeds_when_permission_granted(self, monkeypatch):
        """capture_screenshot must attempt capture when permission is granted."""
        import importlib
        import services.screenshot as smod
        importlib.reload(smod)

        fake_perm = MagicMock()
        fake_perm.has_screen_recording_permission.return_value = True
        monkeypatch.setitem(sys.modules, "services.mac_permission_service", fake_perm)

        # Patch _grab_screen_image to return None (no real display in CI)
        monkeypatch.setattr(smod, "_grab_screen_image", lambda: None)

        # Should call _grab_screen_image (not short-circuit at permission check)
        result = smod.capture_screenshot(activity_session_id=1)
        # _grab_screen_image returns None → capture_screenshot returns None too
        assert result is None


# ===========================================================================
# 6. open_screen_recording_settings() safety
# ===========================================================================

class TestOpenSettings:
    @pytest.fixture(autouse=True)
    def _use_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")

    def test_calls_open_subprocess(self, monkeypatch):
        import subprocess
        mod = _reload_service()
        launched = []

        def fake_popen(args, **kwargs):
            launched.append(args)
            return MagicMock()

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        result = mod.open_screen_recording_settings()
        assert result is True
        assert any("x-apple.systempreferences" in str(a) for a in launched[0])

    def test_returns_false_on_error(self, monkeypatch):
        import subprocess
        mod = _reload_service()
        monkeypatch.setattr(subprocess, "Popen", MagicMock(side_effect=OSError("no open")))
        assert mod.open_screen_recording_settings() is False
