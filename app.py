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


# Identifies this process to the Windows shell. Any stable, unique string
# works; it must not change between releases or Windows treats each build as
# a different application when pinning to the taskbar.
WINDOWS_APP_ID = "IndovisionServices.iHRMSMonitor.Desktop"


def _set_windows_app_identity() -> None:
    """
    Give Windows an explicit application identity.

    Without this, Windows attributes the taskbar button to the process that
    hosts the script - python.exe - and shows the Python icon instead of the
    application icon, no matter what is passed to setWindowIcon(). Must run
    before any window is created.

    Frozen builds get their icon from the executable itself, so this is
    mainly what makes ``python app.py`` show the right icon; it also keeps
    taskbar pinning stable for the packaged build.
    """

    if not sys.platform.startswith("win"):
        return

    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_ID
        )

    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not set the Windows application id; the taskbar may show "
            "the interpreter icon.",
            exc_info=True,
        )


def main() -> int:
    _set_windows_app_identity()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(APP_STYLESHEET)

    from PySide6.QtGui import QIcon
    import os
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ihrms-logo-icon.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    if not is_supported_platform():
        QMessageBox.critical(
            None,
            APP_NAME,
            "This version of iHRMS Monitor supports Windows and macOS.",
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
