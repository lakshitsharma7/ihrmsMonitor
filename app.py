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
    if getattr(sys, "frozen", False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, "assets", "ihrms-logo-icon.ico")
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
    from services.secure_session import SessionStore
    from services.session_service import SessionService
    from config.api_config import ApiConfig

    # Check for a saved session and attempt to restore it
    session_store = SessionStore()
    saved_session = session_store.load_session()

    if saved_session:
        logger.info("Found saved session for user: %s", saved_session.get("username"))
        
        try:
            # Restore the company context
            api_config = ApiConfig()
            api_config.load(company_code=saved_session["company_code"], force=True)

            # Restore the session
            SessionService().restore_session(
                username=saved_session["username"],
                role=saved_session["user_type"],
                full_name=saved_session.get("full_name"),
                user_type=saved_session["user_type"],
                tracking_permitted=saved_session.get("tracking_permitted", True),
                indo_code=saved_session["indo_code"],
                api_key=saved_session["api_key"],
                employee_id=saved_session.get("employee_id"),
                company_code=saved_session["company_code"],
                device_token=saved_session["device_token"],
            )

            logger.info("Session restored successfully for user: %s", saved_session.get("username"))

            # Open main window directly without showing login
            from ui.main_window import MainWindow
            main_window = MainWindow(login_window=None)
            main_window.hide()
            if hasattr(main_window, "tray") and main_window.tray:
                main_window.tray.show_message(
                    "iHRMS Monitor",
                    "iHRMS Monitor has started in the background."
                )
            
            return app.exec()

        except Exception:
            logger.exception("Failed to restore session, falling back to login")
            # Fall through to login screen if session restoration fails
            session_store.clear_session()

    # No valid session found, show login window
    login_window = LoginWindow()
    login_window.show()

    return app.exec()




if __name__ == "__main__":
    sys.exit(main())
