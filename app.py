"""Activity Tracker application entry point.

Run with:
    python app.py

Note on package naming:
    OS-specific activity/idle detection lives in the ``platform_support/``
    package (not ``platform/``). Python ships its own standard-library
    module named ``platform``, and this project's directory is placed on
    ``sys.path`` when run directly (``python app.py``) - naming our package
    ``platform`` would shadow the stdlib module for every other library in
    the process (many, including ``uuid``, import it internally), causing
    hard-to-diagnose failures. ``platform_support`` avoids that collision
    entirely.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from config.settings import APP_NAME, ORG_NAME
from database.database import init_database
from ui.styles import APP_STYLESHEET
from utils.logger import get_logger
from utils.paths import is_supported_platform

logger = get_logger(__name__)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(APP_STYLESHEET)

    if not is_supported_platform():
        QMessageBox.critical(
            None,
            APP_NAME,
            "This version of Activity Tracker supports Windows and macOS.",
        )
        return 1

    logger.info("Starting %s", APP_NAME)

    try:
        init_database()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to initialize database")
        QMessageBox.critical(
            None,
            APP_NAME,
            "Could not initialize the local database. Check the log file for details.",
        )
        return 1

    # Imported after QApplication exists, since it builds widgets.
    from ui.login_window import LoginWindow

    login_window = LoginWindow()
    login_window.show()

    return app.exec()



if __name__ == "__main__":
    sys.exit(main())
