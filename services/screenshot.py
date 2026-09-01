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

SCREENSHOT_DIR = (
    PROJECT_ROOT / "screenshots"
)

try:
    SCREENSHOT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

except OSError:
    # Never raise while importing: a missing directory must not stop the
    # application from starting. capture_screenshot() reports it instead.
    logger.exception(
        "Could not create the screenshot directory: %s",
        SCREENSHOT_DIR,
    )


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

    filepath = (
        SCREENSHOT_DIR / filename
    )

    # ----------------------------------------------------------
    # Destination
    # ----------------------------------------------------------

    try:
        SCREENSHOT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

    except OSError:
        logger.exception(
            "Screenshot directory is not writable, cannot capture "
            "screenshot for session=%s: %s",
            activity_session_id,
            SCREENSHOT_DIR,
        )

        return None

    # ----------------------------------------------------------
    # Grab the screen
    # ----------------------------------------------------------

    _ensure_dpi_awareness()

    try:
        image = ImageGrab.grab()

    except Exception:  # noqa: BLE001
        logger.exception(
            "Screen capture failed for session=%s",
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
