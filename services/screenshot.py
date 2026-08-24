from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import ImageGrab


# ==============================================================
# PATHS
# ==============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

SCREENSHOT_DIR = (
    PROJECT_ROOT / "screenshots"
)

SCREENSHOT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ==============================================================
# CAPTURE SCREENSHOT
# ==============================================================

def capture_screenshot(
    activity_session_id: int | None = None,
) -> str | None:
    """
    Capture the current screen.

    If an activity session ID is provided, the screenshot is
    saved using that session ID.

    Example:

        session_9_2026-08-24_07-34-21-123456.png

    If no session ID is provided, a normal screenshot filename
    is used.
    """

    try:

        # ------------------------------------------------------
        # Timestamp
        # ------------------------------------------------------

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S-%f"
        )

        # ------------------------------------------------------
        # Session-specific filename
        # ------------------------------------------------------

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

        # ------------------------------------------------------
        # Capture screen
        # ------------------------------------------------------

        image = ImageGrab.grab()

        # ------------------------------------------------------
        # Save
        # ------------------------------------------------------

        image.save(
            filepath,
            "PNG",
        )

        print(
            "SCREENSHOT SAVED | "
            f"session={activity_session_id} | "
            f"{filepath}"
        )

        return str(filepath)

    except Exception as e:

        print(
            "SCREENSHOT ERROR | "
            f"session={activity_session_id} | "
            f"{e}"
        )

        return None


# ==============================================================
# DIRECT TEST
# ==============================================================

if __name__ == "__main__":

    capture_screenshot()