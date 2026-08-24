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

        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        image = ImageGrab.grab()

        # ------------------------------------------------------
        # Save and compress using background worker thread
        # ------------------------------------------------------

        import io
        import base64
        import threading

        def _save_and_compress_worker():
            try:
                # Check size in memory buffer
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format='PNG')
                size_in_bytes = img_byte_arr.tell()

                if size_in_bytes < 102400: # < 100KB
                    image.save(filepath, "PNG")
                    img_byte_arr.seek(0)
                    base64_data = base64.b64encode(img_byte_arr.read()).decode("utf-8")
                    print(f"SCREENSHOT WORKER | Saved uncompressed (<100KB, size={size_in_bytes}B)")
                else:
                    from PIL import Image
                    compressed = image.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
                    compressed.save(filepath, "PNG", optimize=True)
                    
                    compressed_byte_arr = io.BytesIO()
                    compressed.save(compressed_byte_arr, format='PNG', optimize=True)
                    compressed_byte_arr.seek(0)
                    base64_data = base64.b64encode(compressed_byte_arr.read()).decode("utf-8")
                    print(f"SCREENSHOT WORKER | Saved compressed (>=100KB, size={size_in_bytes}B -> {compressed_byte_arr.tell()}B)")

                print(
                    "SCREENSHOT SAVED | "
                    f"session={activity_session_id} | "
                    f"{filepath}"
                )
            except Exception as e:
                print(
                    "SCREENSHOT WORKER ERROR | "
                    f"session={activity_session_id} | "
                    f"{e}"
                )

        worker_thread = threading.Thread(target=_save_and_compress_worker, daemon=True)
        worker_thread.start()

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