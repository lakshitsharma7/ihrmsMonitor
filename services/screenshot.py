"""Screen capture used by the activity tracker.

The captured file is written before ``capture_screenshot()`` returns. Callers
immediately stat the returned path and hand it to the upload API, so writing
it on a background thread (as this module used to) made them see a file that
did not exist yet - the screenshot was then dropped and never uploaded.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageGrab

from utils.logger import get_logger


logger = get_logger(__name__)


# ==============================================================
# PATHS
# ==============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)


def get_destination_directory() -> Path:
    """Return a guaranteed writable per-user directory for saving screenshots."""
    try:
        from utils.paths import get_screenshots_directory
        dir_path = get_screenshots_directory()
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path
    except Exception:
        fallback = PROJECT_ROOT / "screenshots"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return fallback


SCREENSHOT_DIR = get_destination_directory()


# Captures smaller than this are stored exactly as grabbed; larger ones are
# colour-reduced first.
COMPRESS_ABOVE_BYTES = 102400


_dpi_awareness_applied = False


def _ensure_dpi_awareness() -> None:
    """
    Make captures cover the whole physical desktop.

    Without this, a process on a scaled display grabs only the unscaled
    top-left region. Applied once per process.
    """

    global _dpi_awareness_applied

    if _dpi_awareness_applied or not sys.platform.startswith("win"):
        return

    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)

    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()

        except Exception:  # noqa: BLE001
            logger.debug(
                "Could not make the process DPI aware",
                exc_info=True,
            )

    _dpi_awareness_applied = True


def _grab_screen_image() -> Image.Image | None:
    """
    Grab the screen using a robust multi-tiered fallback chain:
    1. PySide6 QGuiApplication (uses native Windows DWM/QPA compositor; works where GDI BitBlt fails)
    2. PIL ImageGrab (with all_screens=True if supported)
    3. Win32 GDI BitBlt
    4. mss
    """
    # Tier 1: PySide6 QGuiApplication
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QBuffer, QIODevice

        app = QApplication.instance()
        if app is None:
            try:
                app = QApplication(sys.argv)
            except Exception:
                pass

        if app is not None:
            screens = QGuiApplication.screens()
            if screens:
                primary = QGuiApplication.primaryScreen() or screens[0]
                pixmap = primary.grabWindow(0)
                if not pixmap.isNull() and pixmap.width() > 0 and pixmap.height() > 0:
                    qbuffer = QBuffer()
                    qbuffer.open(QIODevice.OpenModeFlag.ReadWrite)
                    if pixmap.save(qbuffer, "PNG"):
                        png_bytes = bytes(qbuffer.data())
                        qbuffer.close()
                        if len(png_bytes) > 0:
                            img = Image.open(io.BytesIO(png_bytes))
                            img.load()
                            return img
    except Exception as e:
        logger.debug("Tier 1 (PySide6) screen capture failed: %s", e)

    # Tier 2: PIL.ImageGrab
    try:
        _ensure_dpi_awareness()
        try:
            img = ImageGrab.grab(all_screens=True)
        except Exception:
            img = ImageGrab.grab()
        if img is not None and img.size[0] > 0 and img.size[1] > 0:
            return img
    except Exception as e:
        logger.debug("Tier 2 (PIL.ImageGrab) screen capture failed: %s", e)

    # Tier 3: Win32 GDI BitBlt
    try:
        import win32gui
        import win32ui
        import win32con
        import win32api

        hwin = win32gui.GetDesktopWindow()
        width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN) or win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN) or win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN) if win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN) else 0
        top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN) if win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN) else 0

        hwindc = win32gui.GetWindowDC(hwin)
        srcdc = win32ui.CreateDCFromHandle(hwindc)
        memdc = srcdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(srcdc, width, height)
        memdc.SelectObject(bmp)
        memdc.BitBlt((0, 0), (width, height), srcdc, (left, top), win32con.SRCCOPY)

        bmpinfo = bmp.GetInfo()
        bmpstr = bmp.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1)

        memdc.DeleteDC()
        win32gui.DeleteObject(bmp.GetHandle())
        srcdc.DeleteDC()
        win32gui.ReleaseDC(hwin, hwindc)

        if img is not None and img.size[0] > 0 and img.size[1] > 0:
            return img
    except Exception as e:
        logger.debug("Tier 3 (Win32 GDI) screen capture failed: %s", e)

    # Tier 4: mss
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[0]
            sct_img = sct.grab(mon)
            if sct_img:
                return Image.frombytes("RGB", sct_img.size, sct_img.rgb)
    except Exception as e:
        logger.debug("Tier 4 (mss) screen capture failed: %s", e)

    return None


# ==============================================================
# CAPTURE SCREENSHOT
# ==============================================================

def capture_screenshot(
    activity_session_id: int | None = None,
) -> str | None:
    """
    Capture the current screen and return the saved file path.

    If an activity session ID is provided the screenshot is named after it:

        session_9_2026-08-24_07-34-21-123456.png

    Otherwise a plain screenshot filename is used. Returns None if the
    screen could not be captured or the file could not be written, having
    logged the reason.
    """

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S-%f"
    )

    if activity_session_id is not None:

        filename = (
            f"session_{activity_session_id}_"
            f"{timestamp}.png"
        )

    else:

        filename = (
            f"screenshot_{timestamp}.png"
        )

    target_dir = get_destination_directory()
    filepath = (
        target_dir / filename
    )

    # ----------------------------------------------------------
    # Destination
    # ----------------------------------------------------------

    try:
        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    except OSError:
        logger.exception(
            "Screenshot directory is not writable, cannot capture "
            "screenshot for session=%s: %s",
            activity_session_id,
            target_dir,
        )

        return None

    # ----------------------------------------------------------
    # Grab the screen using multi-tiered fallback chain
    # ----------------------------------------------------------

    image = _grab_screen_image()

    if image is None:
        logger.error(
            "All screen capture methods failed for session=%s",
            activity_session_id,
        )
        return None

    # ----------------------------------------------------------
    # Write the file (synchronously - the caller uploads this path)
    # ----------------------------------------------------------

    try:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        raw_size = buffer.tell()

        if raw_size < COMPRESS_ABOVE_BYTES:
            image.save(filepath, "PNG")

        else:
            compressed = image.quantize(
                colors=256,
                method=Image.Quantize.FASTOCTREE,
            )

            compressed.save(
                filepath,
                "PNG",
                optimize=True,
            )

    except Exception:  # noqa: BLE001
        logger.exception(
            "Could not write screenshot for session=%s to %s",
            activity_session_id,
            filepath,
        )

        return None

    # ----------------------------------------------------------
    # Confirm it actually landed on disk before reporting success
    # ----------------------------------------------------------

    try:
        written_size = filepath.stat().st_size

    except OSError:
        logger.exception(
            "Screenshot file is missing after saving for session=%s: %s",
            activity_session_id,
            filepath,
        )

        return None

    if written_size <= 0:
        logger.error(
            "Screenshot file is empty for session=%s: %s",
            activity_session_id,
            filepath,
        )

        return None

    logger.info(
        "Screenshot captured: session=%s raw=%dB saved=%dB path=%s",
        activity_session_id,
        raw_size,
        written_size,
        filepath,
    )

    return str(filepath)


# ==============================================================
# DIRECT TEST
# ==============================================================

if __name__ == "__main__":

    print(capture_screenshot())
