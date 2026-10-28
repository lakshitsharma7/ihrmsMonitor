"""Comprehensive tests for Screenshot Capture and Upload Optimization.

Verifies all 10 requirements specified in the project optimization task:
1. Screenshot file sizes before and after compression (100 KB–150 KB target).
2. Confirmation that no screenshot over 150 KB is uploaded.
3. Behavior when compression cannot reach the required size.
4. Capture on an active-window change.
5. No duplicate capture during the same window's polling cycles.
6. One new capture after the same window remains active for 30 minutes.
7. Correct behavior when switching windows before 30 minutes.
8. Existing screenshot API contract remains unchanged.
9. Local file cleanup and upload-failure handling.
10. System verification and regression testing.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from database.database import get_session
from database.models import ActivitySession
from database.repository import ActivityRepository
from config.screenshot_config import (
    ScreenshotConfig,
    apply_api_screenshot_config,
    get_screenshot_config,
    reset_screenshot_config,
    set_screenshot_config,
)
from platform_support.base import ActiveApplication, PlatformActivityProvider
from services.screenshot import (
    MAX_SCREENSHOT_BYTES,
    MIN_TARGET_BYTES,
    capture_screenshot,
    compress_image,
    compress_image_file,
)
from services.sync_service import SyncService
from services.secure_session import SessionStore
from tracker.activity_tracker import ActivityTracker


@pytest.fixture(autouse=True)
def clean_config_state():
    """Ensure every test starts and ends with clean default ScreenshotConfig."""
    reset_screenshot_config()
    yield
    reset_screenshot_config()


# ==============================================================
# FAKES & TEST FIXTURES
# ==============================================================

class DeterministicClock:
    """Controllable clock for time-dependent tracker tests."""

    def __init__(self, start_time: datetime | None = None) -> None:
        self.current = start_time or datetime(2026, 10, 27, 10, 0, 0, tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.current


class FakeActivityProvider(PlatformActivityProvider):
    """Controllable active application provider for testing focus changes."""

    def __init__(self) -> None:
        self._active_app: ActiveApplication | None = None
        self._idle_seconds: float = 0.0

    def set_active(self, app_name: str, pid: int, title: str | None = None, hwnd: int | None = None) -> None:
        self._active_app = ActiveApplication(app_name, pid, title, window_handle=hwnd)

    def set_idle_seconds(self, seconds: float) -> None:
        self._idle_seconds = seconds

    def get_active_application(self) -> ActiveApplication | None:
        return self._active_app

    def get_idle_seconds(self) -> float:
        return self._idle_seconds


def _create_high_entropy_screen(width: int = 1920, height: int = 1080) -> Image.Image:
    """Generate a realistic desktop screen with smooth 2D gradients and rich content."""
    x = np.linspace(0, 1, width)
    y = np.linspace(0, 1, height)
    xx, yy = np.meshgrid(x, y)
    r = (np.sin(xx * 50) * 127 + 128).astype(np.uint8)
    g = (np.cos(yy * 50) * 127 + 128).astype(np.uint8)
    b = (np.sin((xx + yy) * 30) * 127 + 128).astype(np.uint8)
    arr = np.stack([r, g, b], axis=-1)
    return Image.fromarray(arr)


def advance_tracker(tracker: ActivityTracker, clock: DeterministicClock, total_seconds: float, step: float = 5.0) -> None:
    """Advance clock and poll tracker in small intervals to simulate continuous desktop execution."""
    remaining = total_seconds
    while remaining > 0:
        dt = min(remaining, step)
        clock.advance(dt)
        remaining -= dt
        tracker.poll()


# ==============================================================
# REQUIREMENT 1: SCREENSHOT SIZE & COMPRESSION
# ==============================================================

def test_1_screenshot_size_before_and_after_compression():
    """Verify that screenshots are compressed to the configured maximum (default <= 100 KB)."""
    # Test with synthetic rich image
    image = _create_high_entropy_screen(1920, 1080)

    raw_buf = io.BytesIO()
    image.save(raw_buf, format="PNG")
    raw_size = len(raw_buf.getvalue())
    assert raw_size > 100 * 1024, f"Test image must exceed 100 KB initially (was {raw_size} bytes)"

    result = compress_image(image)
    assert result is not None, "Compression must succeed for realistic desktop screen"
    compressed_bytes, ext = result
    comp_size = len(compressed_bytes)

    # Verify strict maximum (<= max_size_bytes, default 100 KB)
    cfg = get_screenshot_config()
    assert comp_size <= cfg.max_size_bytes, (
        f"Compressed size {comp_size} bytes exceeds maximum allowed {cfg.max_size_kb} KB ({cfg.max_size_bytes} bytes)"
    )

    # Verify format
    assert ext in (".jpg", ".jpeg", ".png")

    # Verify decodability and aspect ratio preservation
    with Image.open(io.BytesIO(compressed_bytes)) as decoded:
        assert decoded.width > 0
        assert decoded.height > 0
        aspect_original = image.width / image.height
        aspect_decoded = decoded.width / decoded.height
        assert abs(aspect_original - aspect_decoded) < 0.05

    # Verify format
    assert ext in (".jpg", ".jpeg", ".png")

    # Verify decodability and aspect ratio preservation
    with Image.open(io.BytesIO(compressed_bytes)) as decoded:
        assert decoded.width > 0
        assert decoded.height > 0
        aspect_original = image.width / image.height
        aspect_decoded = decoded.width / decoded.height
        assert abs(aspect_original - aspect_decoded) < 0.05

    # Also verify with real 1.05 MB desktop screenshot if available on disk
    real_screenshot_path = Path(r"C:\Users\Dell\AppData\Local\Workpulse\screenshots\session_1135_2026-10-21_13-08-29-481702.png")
    if real_screenshot_path.exists():
        real_before = real_screenshot_path.stat().st_size
        assert real_before > 150 * 1024, "Real screenshot must be > 150 KB"
        real_res = compress_image_file(real_screenshot_path)
        assert real_res is not None
        real_bytes, real_ext = real_res
        assert len(real_bytes) <= MAX_SCREENSHOT_BYTES
        assert len(real_bytes) >= MIN_TARGET_BYTES


def test_1b_compress_image_file_on_disk(tmp_path: Path):
    """Verify compress_image_file compresses an existing file on disk and verifies size."""
    image = _create_high_entropy_screen(1920, 1080)
    raw_file = tmp_path / "desktop_raw.png"
    image.save(raw_file, format="PNG")

    file_size_before = raw_file.stat().st_size
    assert file_size_before > 150 * 1024

    comp_res = compress_image_file(raw_file)
    assert comp_res is not None
    comp_bytes, ext = comp_res

    assert len(comp_bytes) <= MAX_SCREENSHOT_BYTES
    assert len(comp_bytes) >= MIN_TARGET_BYTES


# ==============================================================
# REQUIREMENT 2: CONFIRMATION NO SCREENSHOT OVER 150 KB IS UPLOADED
# ==============================================================

def test_2_no_screenshot_over_150kb_is_uploaded(tmp_path: Path):
    """Verify that upload_screenshot_now refuses to upload any file over configured max_size_kb."""
    oversized_file = tmp_path / "oversized.bin"
    # Create an uncompressible random byte file of 120 KB (exceeds default 100 KB limit)
    oversized_file.write_bytes(os.urandom(120 * 1024))
    assert oversized_file.stat().st_size > 100 * 1024

    sync_service = SyncService()

    with patch("requests.post") as mock_post:
        success = sync_service.upload_screenshot_now(
            screenshot_path=oversized_file,
            activity_session_id="server_123",
            application_name="App.exe",
            process_id=1234,
            local_session_id=None,
            device_token="valid_token_abc",
        )

        assert success is False, "upload_screenshot_now must return False for uncompressible oversized files"
        # Confirmation: requests.post must NEVER be invoked
        mock_post.assert_not_called()

    # The oversized file must be deleted from local disk
    assert not oversized_file.exists(), "Oversized screenshot file must be deleted locally"


# ==============================================================
# REQUIREMENT 3: BEHAVIOR WHEN COMPRESSION CANNOT REACH REQUIRED SIZE
# ==============================================================

def test_3_behavior_when_compression_cannot_reach_required_size(tmp_path: Path):
    """When compression cannot reach <= max_size_kb: delete file, return None, do not save in DB."""
    # Mock compress_image to simulate failure to achieve required size
    with patch("services.screenshot.compress_image", return_value=None):
        path = capture_screenshot(activity_session_id=99999)
        assert path is None, "capture_screenshot must return None if compression cannot reach required size"

    # Confirm capture_screenshot also deletes file if disk size exceeds limit
    dummy_img = Image.new("RGB", (100, 100), (255, 0, 0))
    with patch("services.screenshot._grab_screen_image", return_value=dummy_img), \
         patch("services.screenshot.compress_image", return_value=(b"X" * (120 * 1024), ".jpg")):
        path2 = capture_screenshot(activity_session_id=88888)
        assert path2 is None, "Must return None if size exceeds configured limit"


def test_3b_rejected_screenshot_cleared_from_database(tmp_path: Path):
    """Verify that if an uncompressible oversized file is queued, it is purged from DB."""
    db = get_session()
    repo = ActivityRepository(db)
    now = datetime.now(timezone.utc)
    sess = repo.create_session("HeavyApp", 5555, "Editor", now)
    sess_id = sess.id
    db.close()

    oversized_file = tmp_path / f"session_{sess_id}_huge.jpg"
    oversized_file.write_bytes(os.urandom(120 * 1024))

    # Associate in DB
    db = get_session()
    repo = ActivityRepository(db)
    repo.update_session_screenshot_path(sess_id, str(oversized_file))
    db.close()

    sync_service = SyncService()
    with patch("requests.post") as mock_post:
        success = sync_service.upload_screenshot_now(
            screenshot_path=oversized_file,
            activity_session_id="server_sess_555",
            application_name="HeavyApp",
            process_id=5555,
            local_session_id=sess_id,
            device_token="device_tok_123",
        )
        assert success is False
        mock_post.assert_not_called()

    # Verify purged from DB
    db = get_session()
    rec = db.get(ActivitySession, sess_id)
    assert rec.screenshot_path is None, "Database record must have screenshot_path cleared to None"
    db.close()


# ==============================================================
# REQUIREMENT 4: CAPTURE ON ACTIVE-WINDOW CHANGE
# ==============================================================

def test_4_capture_on_active_window_change():
    """Verify screenshot is captured when the active application/window changes."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=3600,
            clock=clock,
            capture_on_switch=True,
        )
        tracker.start()

        # Window 1: Chrome
        provider.set_active("Chrome.exe", 1001, "Google Search")
        tracker.poll()
        assert len(capture_calls) == 1
        assert tracker._current.application_name == "Chrome.exe"

        # Advance 2 minutes in Chrome (before 30 min)
        advance_tracker(tracker, clock, 120, step=5.0)

        # Window 2: VS Code (Active window changed!)
        provider.set_active("Code.exe", 2002, "main.py")
        tracker.poll()

        # Confirmation: capture on active-window change
        assert len(capture_calls) == 2
        assert tracker._current.application_name == "Code.exe"
        assert capture_calls[1][0] == tracker._current.db_id

        tracker.stop()


# ==============================================================
# REQUIREMENT 5: NO DUPLICATE CAPTURE DURING SAME WINDOW'S POLLING CYCLES
# ==============================================================

def test_5_no_duplicate_capture_during_same_window_polling_cycles():
    """Verify that polling the same active window does NOT repeatedly capture screenshots."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append(activity_session_id)
        return path

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=3600,
            clock=clock,
            capture_on_switch=True,
        )
        tracker.start()

        provider.set_active("Word.exe", 3001, "Document 1 - Word")
        tracker.poll()  # Initial capture
        assert len(capture_calls) == 1

        # Simulate 20 consecutive polling cycles (1 second each)
        for _ in range(20):
            clock.advance(1)
            tracker.poll()

        # Confirm NO duplicate screenshots were captured during same window polling cycles
        assert len(capture_calls) == 1, (
            f"Expected only 1 capture for same window across polling cycles, but got {len(capture_calls)}"
        )

        tracker.stop()


# ==============================================================
# REQUIREMENT 6: ONE NEW CAPTURE AFTER SAME WINDOW REMAINS ACTIVE FOR 30 MINUTES
# ==============================================================

def test_6_one_new_capture_after_same_window_remains_active_for_30_minutes():
    """Verify one new capture after 30 minutes, starting a new 30-minute interval."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=7200,
            clock=clock,
            capture_on_switch=True,
        )
        tracker.start()

        provider.set_active("Excel.exe", 4001, "Sheet1 - Excel")
        tracker.poll()  # T = 0: Initial capture
        assert len(capture_calls) == 1

        # Advance to 29 minutes (1740 seconds) via continuous polling
        advance_tracker(tracker, clock, 29 * 60, step=5.0)
        assert len(capture_calls) == 1, "Must not capture before 30 minutes"

        # Advance remaining 60 seconds (reaches 30 minutes / 1800 seconds)
        advance_tracker(tracker, clock, 60, step=5.0)
        assert len(capture_calls) == 2, "Must capture exactly one new screenshot at 30 minutes"

        # Advance another 60 seconds (T = 31 minutes): No extra capture
        advance_tracker(tracker, clock, 60, step=5.0)
        assert len(capture_calls) == 2, "Must not capture immediately after 30-minute mark"

        # Advance another 29 minutes (T = 60 minutes / 3600 seconds from start): Next 30-min capture
        advance_tracker(tracker, clock, 29 * 60, step=5.0)
        assert len(capture_calls) == 3, "Must capture one new screenshot after second 30-minute interval"

        tracker.stop()


# ==============================================================
# REQUIREMENT 7: BEHAVIOR WHEN SWITCHING WINDOWS BEFORE 30 MINUTES
# ==============================================================

def test_7_behavior_when_switching_windows_before_30_minutes():
    """Verify switching windows before 30 minutes captures for the new window and resets interval."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=7200,
            clock=clock,
            capture_on_switch=True,
        )
        tracker.start()

        # Window A at T = 0
        provider.set_active("AppA.exe", 100, "Window A")
        tracker.poll()
        assert len(capture_calls) == 1

        # User works in Window A for 10 minutes (before 30 minutes)
        advance_tracker(tracker, clock, 10 * 60, step=5.0)
        assert len(capture_calls) == 1

        # Switch to Window B at T = 10 minutes
        provider.set_active("AppB.exe", 200, "Window B")
        tracker.poll()
        assert len(capture_calls) == 2, "Must capture screenshot for newly active window"

        # Window B stays active for 15 minutes (T = 25 minutes)
        advance_tracker(tracker, clock, 15 * 60, step=5.0)
        assert len(capture_calls) == 2, "No duplicate capture for Window B before its 30 minutes"

        # Window B reaches its own 30 minutes (T = 10m + 30m = 40m)
        advance_tracker(tracker, clock, 15 * 60, step=5.0)
        assert len(capture_calls) == 3, "Window B must get a new screenshot after it remains active for 30 minutes"

        tracker.stop()


def test_7b_rapid_focus_switch_debouncing():
    """Verify rapid focus switches within debounce threshold avoid duplicate screenshot captures."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=3600,
            clock=clock,
            capture_on_switch=True,
        )
        tracker.start()

        # Window A active at T=0
        provider.set_active("AppA.exe", 100, "Window A")
        tracker.poll()
        assert len(capture_calls) == 1

        # Rapid focus change: User Alt+Tabs to Window B only 0.2s later
        clock.advance(0.2)
        provider.set_active("AppB.exe", 200, "Window B")
        tracker.poll()
        # Debounced! No immediate duplicate capture taken
        assert len(capture_calls) == 1

        # Window B settles: next poll when elapsed >= 1.0s
        clock.advance(1.0)
        tracker.poll()
        # Now captured for Window B
        assert len(capture_calls) == 2

        tracker.stop()


# ==============================================================
# REQUIREMENT 8: SCREENSHOT API CONTRACT REMAINS UNCHANGED
# ==============================================================

def test_8_existing_screenshot_api_contract_unchanged(tmp_path: Path):
    """Verify upload endpoint, method, headers, auth, and request format remain exactly as required."""
    img = Image.new("RGB", (400, 300), (10, 80, 160))
    valid_file = tmp_path / "session_10_2026-10-27.jpg"
    img.save(valid_file, format="JPEG", quality=85)
    file_bytes = valid_file.read_bytes()
    assert len(file_bytes) <= MAX_SCREENSHOT_BYTES

    sync_service = SyncService()

    with patch("requests.post") as mock_post:
        # Mock successful server response matching existing backend contract
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"response": "Success", "data": {"screenshot_id": "sc_777"}}'
        mock_response.json.return_value = {"response": "Success", "data": {"screenshot_id": "sc_777"}}
        mock_post.return_value = mock_response

        captured_dt = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
        success = sync_service.upload_screenshot_now(
            screenshot_path=valid_file,
            activity_session_id="serv_sess_99",
            application_name="TestApp",
            process_id=456,
            captured_at=captured_dt,
            local_session_id=10,
            device_token="test_bearer_token",
        )

        assert success is True
        mock_post.assert_called_once()

        # Verify API Endpoint: POST .../workpulse/upload_screenshot
        called_url = mock_post.call_args[0][0]
        assert called_url.endswith("/workpulse/upload_screenshot")

        # Verify multipart files
        called_files = mock_post.call_args[1]["files"]
        assert "screenshot" in called_files
        fname, raw_data, content_type = called_files["screenshot"]
        assert fname == valid_file.name
        assert raw_data == file_bytes
        assert content_type in ("image/jpeg", "image/png")

        # Verify multipart data fields
        called_data = mock_post.call_args[1]["data"]
        assert called_data["device_token"] == "test_bearer_token"
        assert called_data["activity_session_id"] == "serv_sess_99"
        assert called_data["captured_at"] == "2026-10-27T12:00:00Z"
        assert "screenshot" in called_data  # base64 encoded string

        # Verify headers
        called_headers = mock_post.call_args[1]["headers"]
        assert "application/json" in called_headers.get("Accept", "")


# ==============================================================
# REQUIREMENT 9: LOCAL FILE CLEANUP AND UPLOAD-FAILURE HANDLING
# ==============================================================

def test_9a_local_file_cleanup_after_successful_upload(tmp_path: Path):
    """Verify local screenshot file is deleted immediately upon successful upload."""
    img = Image.new("RGB", (200, 200), (50, 150, 50))
    screenshot_file = tmp_path / "session_cleanup.jpg"
    img.save(screenshot_file, format="JPEG", quality=80)
    assert screenshot_file.exists()

    sync_service = SyncService()
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"response": "Success"}'
        mock_resp.json.return_value = {"response": "Success"}
        mock_post.return_value = mock_resp

        success = sync_service.upload_screenshot_now(
            screenshot_path=screenshot_file,
            activity_session_id="srv_1",
            application_name="App",
            process_id=1,
            local_session_id=None,
            device_token="tok",
        )
        assert success is True

    # Local file MUST be deleted after verified upload
    assert not screenshot_file.exists(), "Local screenshot file must be unlinked after successful upload"


def test_9b_upload_failure_preserves_file_for_retry(tmp_path: Path):
    """Verify that network/server upload failure preserves the valid file for existing retry mechanism."""
    import requests

    img = Image.new("RGB", (200, 200), (50, 150, 50))
    screenshot_file = tmp_path / "session_retry.jpg"
    img.save(screenshot_file, format="JPEG", quality=80)
    assert screenshot_file.exists()

    sync_service = SyncService()
    with patch("requests.post", side_effect=requests.RequestException("Network timeout")):
        success = sync_service.upload_screenshot_now(
            screenshot_path=screenshot_file,
            activity_session_id="srv_2",
            application_name="App",
            process_id=2,
            local_session_id=None,
            device_token="tok",
        )
        assert success is False

    # Valid pending file (< 150 KB) MUST be preserved for retry
    assert screenshot_file.exists(), "Valid pending screenshot must remain on disk for retry after transient failure"


# ==============================================================
# REQUIREMENT 10: CONFIGURABLE CAPTURE MODES & TIMING
# ==============================================================

def test_10_capture_mode_window_change_only():
    """Verify 'window_change' mode captures on window changes but NEVER on interval expiration."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    config = ScreenshotConfig(
        screenshot_enabled=True,
        capture_mode="window_change",
        screenshot_interval_minutes=30.0,
        capture_on_window_change=True,
    )

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=7200,
            clock=clock,
            screenshot_config=config,
            capture_on_switch=True,
        )
        tracker.start()

        # Window A active at T=0
        provider.set_active("AppA.exe", 100, "Window A")
        tracker.poll()
        assert len(capture_calls) == 1, "Window-change mode must capture on initial active window"

        # Advance 30 minutes in Window A
        advance_tracker(tracker, clock, 30 * 60, step=5.0)
        assert len(capture_calls) == 1, "Window-change mode must NOT capture periodic screenshots on interval expiration"

        # Advance another 30 minutes (60 min total in Window A)
        advance_tracker(tracker, clock, 30 * 60, step=5.0)
        assert len(capture_calls) == 1, "Still no interval capture in window_change mode"

        # Switch to Window B
        provider.set_active("AppB.exe", 200, "Window B")
        tracker.poll()
        assert len(capture_calls) == 2, "Window-change mode must capture on window change"

        tracker.stop()


def test_11_capture_mode_interval_only():
    """Verify 'interval' mode captures on interval expiration but NEVER on window change."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    config = ScreenshotConfig(
        screenshot_enabled=True,
        capture_mode="interval",
        screenshot_interval_minutes=15.0,  # 15 minutes
        capture_on_window_change=True,
    )

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=7200,
            clock=clock,
            screenshot_config=config,
            capture_on_switch=True,
        )
        tracker.start()

        # Window A active at T=0
        provider.set_active("AppA.exe", 100, "Window A")
        tracker.poll()
        # In interval-only mode, initial window switch must NOT capture
        assert len(capture_calls) == 0, "Interval mode must not capture on window open"

        # User works for 10 minutes (before 15 min interval)
        advance_tracker(tracker, clock, 10 * 60, step=5.0)
        assert len(capture_calls) == 0

        # Switch to Window B at T=10 min: interval mode does not capture on switch!
        provider.set_active("AppB.exe", 200, "Window B")
        tracker.poll()
        assert len(capture_calls) == 0, "Interval mode must not capture on active window change"

        # Window B stays active for 15 minutes (its configured interval)
        advance_tracker(tracker, clock, 15 * 60, step=5.0)
        assert len(capture_calls) == 1, "Interval mode must capture when window remains active for configured interval"

        # Window B stays active for another 15 minutes
        advance_tracker(tracker, clock, 15 * 60, step=5.0)
        assert len(capture_calls) == 2, "Interval mode must restart interval and capture again"

        tracker.stop()


def test_12_capture_mode_both_and_simultaneous_prevention():
    """Verify 'both' mode captures on window change AND interval, avoiding duplicates."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    config = ScreenshotConfig(
        screenshot_enabled=True,
        capture_mode="both",
        screenshot_interval_minutes=20.0,  # 20 minutes
        capture_on_window_change=True,
    )

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=7200,
            clock=clock,
            screenshot_config=config,
            capture_on_switch=True,
        )
        tracker.start()

        # Window A at T=0: capture #1 (window change)
        provider.set_active("AppA.exe", 100, "Window A")
        tracker.poll()
        assert len(capture_calls) == 1

        # Advance 20 minutes in Window A: capture #2 (interval expiration)
        advance_tracker(tracker, clock, 20 * 60, step=5.0)
        assert len(capture_calls) == 2

        # Advance 5 minutes in Window A (no capture)
        advance_tracker(tracker, clock, 5 * 60, step=5.0)
        assert len(capture_calls) == 2

        # Switch to Window B: capture #3 (window change)
        provider.set_active("AppB.exe", 200, "Window B")
        tracker.poll()
        assert len(capture_calls) == 3

        # Window B reaches its 20-minute interval: capture #4 (interval)
        advance_tracker(tracker, clock, 20 * 60, step=5.0)
        assert len(capture_calls) == 4

        tracker.stop()


def test_13_screenshot_disabled_master_toggle():
    """Verify screenshot_enabled=False suppresses all captures completely."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append(activity_session_id)
        return path

    config = ScreenshotConfig(
        screenshot_enabled=False,
        capture_mode="both",
        screenshot_interval_minutes=5.0,
    )
    set_screenshot_config(config)

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=7200,
            clock=clock,
            screenshot_config=config,
            capture_on_switch=True,
        )
        tracker.start()

        # Window changes
        provider.set_active("AppA.exe", 100, "Window A")
        tracker.poll()
        assert len(capture_calls) == 0, "No capture when screenshot_enabled=False"

        # Advance past interval
        advance_tracker(tracker, clock, 10 * 60, step=5.0)
        assert len(capture_calls) == 0, "No interval capture when screenshot_enabled=False"

        # Switch to another window
        provider.set_active("AppB.exe", 200, "Window B")
        tracker.poll()
        assert len(capture_calls) == 0

        tracker.stop()


def test_14_capture_on_window_change_toggle():
    """Verify capture_on_window_change=False disables window-change capture while keeping interval."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    config = ScreenshotConfig(
        screenshot_enabled=True,
        capture_mode="both",
        capture_on_window_change=False,  # Window-change explicitly disabled
        screenshot_interval_minutes=10.0,
    )

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=7200,
            clock=clock,
            screenshot_config=config,
            capture_on_switch=True,
        )
        tracker.start()

        provider.set_active("AppA.exe", 100, "Window A")
        tracker.poll()
        assert len(capture_calls) == 0, "Must not capture on window change when capture_on_window_change=False"

        # Advance 10 minutes in Window A: interval capture must fire!
        advance_tracker(tracker, clock, 10 * 60, step=5.0)
        assert len(capture_calls) == 1, "Interval capture must still fire when interval expires"

        tracker.stop()


def test_15_configuration_interface_and_future_api_population():
    """Verify ScreenshotConfig handles arbitrary future API response payloads safely."""
    # 1. Test exact default dictionary required by prompt:
    defaults_dict = {
        "screenshot_settings": {
            "enabled": True,
            "capture_mode": "both",
            "capture_on_window_change": True,
            "interval_minutes": 30,
            "max_size_kb": 100,
        }
    }
    cfg = ScreenshotConfig()
    cfg.update_from_dict(defaults_dict)
    assert cfg.enabled is True
    assert cfg.capture_mode == "both"
    assert cfg.capture_on_window_change is True
    assert cfg.interval_minutes == 30
    assert cfg.max_size_kb == 100
    assert cfg.max_size_bytes == 100 * 1024

    # 2. Test custom API payload
    api_payload = {
        "screenshot_settings": {
            "enabled": "true",
            "capture_mode": "INTERVAL",
            "interval_minutes": "45.5",
            "max_size_kb": "145",
            "compression_enabled": 1,
            "delete_if_compression_fails": "yes",
            "capture_on_window_change": "0",
        }
    }

    config = apply_api_screenshot_config(api_payload)

    assert config.enabled is True
    assert config.capture_mode == "interval"
    assert config.interval_minutes == 45.5
    assert config.interval_seconds == 45.5 * 60.0
    assert config.max_size_kb == 145
    assert config.max_size_bytes == 145 * 1024
    assert config.compression_enabled is True
    assert config.delete_if_compression_fails is True
    assert config.capture_on_window_change is False

    # 3. Verify serialization
    as_dict = config.to_dict()
    assert as_dict["screenshot_settings"]["capture_mode"] == "interval"
    assert as_dict["screenshot_settings"]["interval_minutes"] == 45.5
    assert as_dict["screenshot_settings"]["max_size_kb"] == 145

    # 4. Test safe fallback on invalid/corrupted payload
    corrupted_payload = {
        "screenshot_settings": {
            "capture_mode": "unsupported_mode",
            "interval_minutes": -10,
            "max_size_kb": -20,
        }
    }
    config.update_from_dict(corrupted_payload)
    assert config.capture_mode == "both"  # defaulted
    assert config.interval_minutes == 30.0  # defaulted
    assert config.max_size_kb == 100  # defaulted


def test_16_compression_enabled_and_delete_if_fails(tmp_path: Path):
    """Verify compression_enabled and delete_if_compression_fails behavior in services/screenshot.py."""
    # 1. When compression_enabled=False:
    # A large image cannot meet <= 100 KB without compression
    config = ScreenshotConfig(
        enabled=True,
        compression_enabled=False,
        max_size_kb=100,
        delete_if_compression_fails=True,
    )
    set_screenshot_config(config)

    large_img = _create_high_entropy_screen(1920, 1080)
    with patch("services.screenshot._grab_screen_image", return_value=large_img):
        res = capture_screenshot(activity_session_id=12345)
        # Large raw PNG (140 KB) exceeds 100 KB and compression is disabled -> discarded
        assert res is None

    # 2. When compression_enabled=True:
    config.compression_enabled = True
    set_screenshot_config(config)
    with patch("services.screenshot._grab_screen_image", return_value=large_img):
        res = capture_screenshot(activity_session_id=12346)
        assert res is not None
        p = Path(res)
        assert p.exists()
        assert p.stat().st_size <= config.max_size_bytes
        p.unlink()


def test_17_strongest_reliable_window_identity_with_hwnd():
    """Verify window identification uses native window handle + process ID when available."""
    clock = DeterministicClock()
    provider = FakeActivityProvider()
    capture_calls = []

    def fake_capture(activity_session_id=None):
        path = f"/mock/screenshots/session_{activity_session_id}.jpg"
        capture_calls.append((activity_session_id, clock.current))
        return path

    with patch("tracker.activity_tracker.capture_screenshot", side_effect=fake_capture):
        tracker = ActivityTracker(
            provider=provider,
            session_factory=get_session,
            idle_threshold_seconds=7200,
            clock=clock,
            capture_on_switch=True,
        )
        tracker.start()

        # Two different windows with the SAME title and app, but DIFFERENT HWND (native handle)
        provider.set_active("Chrome.exe", 1001, "Google - Chrome", hwnd=123456)
        tracker.poll()
        assert len(capture_calls) == 1

        # Same window (same HWND): no duplicate capture
        tracker.poll()
        assert len(capture_calls) == 1

        # Switch to second window: same title and app, but different HWND (654321)
        clock.advance(2.0)
        provider.set_active("Chrome.exe", 1001, "Google - Chrome", hwnd=654321)
        tracker.poll()
        assert len(capture_calls) == 2, "Must recognize distinct window handle as window change"

        tracker.stop()


def test_18_no_artificial_enlargement_under_limit():
    """Verify valid screenshots smaller than max_size_kb are preserved without artificial enlargement."""
    small_img = Image.new("RGB", (150, 150), (30, 120, 200))
    raw_buf = io.BytesIO()
    small_img.save(raw_buf, format="PNG")
    raw_sz = len(raw_buf.getvalue())
    assert raw_sz < 50 * 1024

    res = compress_image(small_img, max_bytes=100 * 1024)
    assert res is not None
    data, ext = res
    assert ext == ".png", "Small image under max size must remain lossless PNG"
    assert len(data) <= 100 * 1024
    assert len(data) <= raw_sz, "Lossless PNG must not be enlarged"


def test_19_local_config_file_loading(tmp_path: Path):
    """Verify load_local_screenshot_config reads local JSON file when present."""
    import json
    from config.screenshot_config import load_local_screenshot_config
    cfg_data = {
        "screenshot_settings": {
            "enabled": True,
            "capture_mode": "window_change",
            "capture_on_window_change": True,
            "interval_minutes": 15,
            "max_size_kb": 80,
        }
    }

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch("pathlib.Path.read_text", return_value=json.dumps(cfg_data)):
        cfg = load_local_screenshot_config()
        assert cfg.capture_mode == "window_change"
        assert cfg.interval_minutes == 15
        assert cfg.max_size_kb == 80
        assert cfg.max_size_bytes == 80 * 1024


def test_20_exact_postman_api_enroll_device_response_parsing():
    """Verify parsing of the exact Postman enroll_device API response schema."""
    postman_response = {
        "workpulse_enabled": True,
        "device_token": "5264178cde488e1cccdbdbd875eabe16e63047915554853a0515e82bc53928e8",
        "capture_mode": "activity_with_screenshots",
        "sync_interval_seconds": 3600,
        "idle_threshold_seconds": 300,
        "allow_start_stop_activity_tracking": True,
        "allow_logout": True,
        "screenshot_settings": {
            "enabled": True,
            "capture_mode": "window_change",
            "allowed_types": [
                "png",
                "jpg",
                "jpeg",
            ],
            "capture_on_window_change": True,
            "interval_minutes": 30,
            "max_kb": 100,
        },
    }

    cfg = apply_api_screenshot_config(postman_response)
    assert cfg.enabled is True
    assert cfg.capture_mode == "window_change"
    assert cfg.allowed_types == ["png", "jpg", "jpeg"]
    assert cfg.capture_on_window_change is True
    assert cfg.interval_minutes == 30.0
    assert cfg.max_size_kb == 100
    assert cfg.max_size_bytes == 100 * 1024
    assert cfg.should_capture_on_window_change() is True
    assert cfg.should_capture_on_interval() is False


def test_21_dynamic_settings_update_during_sync_cycle():
    """Verify that sync_service.fetch_settings adopts dynamic screenshot settings from API."""
    sync_svc = SyncService()

    dynamic_api_response = {
        "response": "Success",
        "data": {
            "workpulse_enabled": True,
            "capture_mode": "activity_with_screenshots",
            "sync_interval_seconds": 60,
            "idle_threshold_seconds": 120,
            "screenshot_settings": {
                "enabled": True,
                "capture_mode": "interval",
                "allowed_types": ["jpg", "jpeg"],
                "capture_on_window_change": False,
                "interval_minutes": 10,
                "max_kb": 75,
            },
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = dynamic_api_response
    mock_resp.text = "{}"

    with patch.object(sync_svc, "_require_device_token", return_value="valid_test_token"), \
         patch("requests.post", return_value=mock_resp):
        settings = sync_svc.fetch_settings()
        assert settings != {}

        cfg = get_screenshot_config()
        assert cfg.capture_mode == "interval"
        assert cfg.interval_minutes == 10.0
        assert cfg.max_size_kb == 75
        assert cfg.max_size_bytes == 75 * 1024
        assert cfg.allowed_types == ["jpg", "jpeg"]
        assert cfg.capture_on_window_change is False
        assert cfg.should_capture_on_window_change() is False
        assert cfg.should_capture_on_interval() is True


def test_22_api_failure_preserves_last_valid_settings():
    """Verify that network errors or API failures preserve the last valid configuration."""
    # Establish valid configuration
    apply_api_screenshot_config({
        "screenshot_settings": {
            "enabled": True,
            "capture_mode": "both",
            "capture_on_window_change": True,
            "interval_minutes": 15,
            "max_kb": 80,
        }
    })
    initial_cfg = get_screenshot_config()
    assert initial_cfg.max_size_kb == 80
    assert initial_cfg.interval_minutes == 15.0

    # Simulate empty or invalid dictionary update
    apply_api_screenshot_config({})
    apply_api_screenshot_config(None)  # type: ignore[arg-type]
    apply_api_screenshot_config({"status": 0, "message": "Server Error"})

    # Configuration must remain untouched
    current_cfg = get_screenshot_config()
    assert current_cfg.max_size_kb == 80
    assert current_cfg.interval_minutes == 15.0
    assert current_cfg.capture_mode == "both"

    # Simulate network exception in fetch_settings
    sync_svc = SyncService()
    import requests
    with patch.object(sync_svc, "_require_device_token", return_value="valid_test_token"), \
         patch("requests.post", side_effect=requests.RequestException("Connection timeout")):
        res = sync_svc.fetch_settings()
        assert res == {}

    # Valid settings must still be preserved
    after_err_cfg = get_screenshot_config()
    assert after_err_cfg.max_size_kb == 80
    assert after_err_cfg.interval_minutes == 15.0
    assert after_err_cfg.capture_mode == "both"


def test_23_root_level_capture_mode_disables_screenshots():
    """Verify that root capture_mode='activity_only' or workpulse_enabled=False disables screenshots."""
    # 1. capture_mode='activity_only' at root
    apply_api_screenshot_config({
        "workpulse_enabled": True,
        "capture_mode": "activity_only",
        "screenshot_settings": {
            "enabled": True,
            "capture_mode": "both",
            "max_kb": 100,
        },
    })
    assert get_screenshot_config().enabled is False

    # 2. workpulse_enabled=False at root
    apply_api_screenshot_config({
        "workpulse_enabled": False,
        "capture_mode": "activity_with_screenshots",
        "screenshot_settings": {
            "enabled": True,
            "capture_mode": "both",
            "max_kb": 100,
        },
    })
    assert get_screenshot_config().enabled is False


def test_24_allowed_types_filtering_enforcement():
    """Verify that compress_image respects allowed_types restrictions."""
    # 1. Only JPG allowed: even tiny image that easily fits in PNG must produce JPG
    apply_api_screenshot_config({
        "screenshot_settings": {
            "allowed_types": ["jpg"],
            "max_kb": 100,
        }
    })
    small_img = Image.new("RGB", (100, 100), (40, 80, 120))
    res = compress_image(small_img, max_bytes=100 * 1024)
    assert res is not None
    data, ext = res
    assert ext == ".jpg", "When only JPG is allowed, PNG must not be produced"

    # 2. Only PNG allowed: if an image is large and cannot fit without JPEG, return None
    apply_api_screenshot_config({
        "screenshot_settings": {
            "allowed_types": ["png"],
            "max_kb": 5,  # 5 KB limit: high entropy screen cannot fit in 5KB PNG
        }
    })
    high_entropy = _create_high_entropy_screen(1920, 1080)
    res_png_only = compress_image(high_entropy, max_bytes=5 * 1024)
    assert res_png_only is None, "When only PNG is allowed and image exceeds max_bytes, must discard"


def test_25_re_enroll_device_applies_screenshot_settings():
    """Verify that re_enroll_device dynamically applies screenshot_settings from server."""
    sync_svc = SyncService()
    enroll_payload = {
        "workpulse_enabled": True,
        "device_token": "refreshed_device_token_xyz_123",
        "capture_mode": "activity_with_screenshots",
        "screenshot_settings": {
            "enabled": True,
            "capture_mode": "window_change",
            "allowed_types": ["png", "jpg"],
            "capture_on_window_change": True,
            "interval_minutes": 45,
            "max_kb": 90,
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = enroll_payload
    mock_resp.text = "{}"

    with patch("requests.post", return_value=mock_resp), \
         patch.object(SessionStore, "load_session", return_value={"username": "test_user", "indo_code": "INDO1", "api_key": "k", "base_url": "https://test.api"}), \
         patch.object(SessionStore, "update_device_token"):
        new_token = sync_svc.re_enroll_device()
        assert new_token == "refreshed_device_token_xyz_123"

        cfg = get_screenshot_config()
        assert cfg.max_size_kb == 90
        assert cfg.interval_minutes == 45.0
        assert cfg.capture_mode == "window_change"
        assert cfg.allowed_types == ["png", "jpg"]



