from pathlib import Path
from datetime import datetime
from PIL import ImageGrab


# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Screenshot storage directory
SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"

# Create screenshots folder automatically
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def capture_screenshot():
    try:
        # Include microseconds so two screenshots don't get the same name
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")

        filename = f"screenshot_{timestamp}.png"

        filepath = SCREENSHOT_DIR / filename

        # Capture screen
        image = ImageGrab.grab()

        # Save screenshot
        image.save(filepath, "PNG")

        print(f"SCREENSHOT SAVED | {filepath}")

        return str(filepath)

    except Exception as e:
        print(f"SCREENSHOT ERROR | {e}")
        return None


if __name__ == "__main__":
    capture_screenshot()