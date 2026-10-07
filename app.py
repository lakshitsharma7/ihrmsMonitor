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
import threading

from PySide6.QtWidgets import QApplication, QMessageBox


from config.settings import APP_NAME, ORG_NAME
from database.database import init_database
from ui.styles import APP_STYLESHEET
from utils.logger import get_logger
from utils.paths import is_supported_platform, init_ca_bundle

logger = get_logger(__name__)

# Early CA bundle initialization to ensure requests/urllib3 find valid certificates
_CA_BUNDLE_PATH = init_ca_bundle()



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


def _setup_exception_hook() -> None:
    """Install global exception handlers to capture and report critical unhandled errors across main and background threads."""
    original_hook = sys.excepthook

    def _custom_excepthook(exc_type, exc_value, exc_traceback):
        logger.critical("Uncaught critical exception: %s", exc_value, exc_info=(exc_type, exc_value, exc_traceback))
        try:
            from services.error_report_service import ErrorReportService
            ErrorReportService().report_error(
                error_type="CRITICAL_RUNTIME_ERROR",
                error_message=str(exc_value),
                exc=exc_value,
            )
        except Exception:
            pass
        original_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = _custom_excepthook

    if hasattr(threading, "excepthook"):
        def _threading_excepthook(args):
            thread_name = getattr(args.thread, "name", "UnknownThread")
            logger.critical("Uncaught thread exception in %s: %s", thread_name, args.exc_value, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="THREAD_RUNTIME_ERROR",
                    error_message=f"Unhandled exception in thread '{thread_name}': {args.exc_value}",
                    exc=args.exc_value,
                    extra_context={"thread_name": thread_name},
                )
            except Exception:
                pass
        threading.excepthook = _threading_excepthook


def main() -> int:
    import multiprocessing
    multiprocessing.freeze_support()

    # Stabilize working directory for frozen / auto-started processes
    if getattr(sys, "frozen", False):
        try:
            os.chdir(os.path.dirname(sys.executable))
        except Exception:
            pass

    _setup_exception_hook()
    _set_windows_app_identity()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    if "--test-screenshot" in sys.argv:
        from services.screenshot import capture_screenshot
        path = capture_screenshot()
        print(f"TEST_SCREENSHOT_RESULT: {path}", flush=True)
        return 0 if path else 1

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

    is_startup = any(
        arg in sys.argv for arg in ("--startup", "--minimized", "--background", "--autostart", "-s")
    )
    if is_startup:
        logger.info("Workpulse launched through Windows startup / background mode (%s)", sys.argv)
    else:
        logger.info("Workpulse launched manually by user (%s)", sys.argv)

    if not is_supported_platform():
        QMessageBox.critical(
            None,
            APP_NAME,
            f"This version of {APP_NAME} supports Windows and macOS.",
        )
        return 1

    logger.info("Starting %s", APP_NAME)
    ca_status = init_ca_bundle()
    if ca_status:
        logger.info("TLS CA certificate bundle active: %s (exists=%s)", ca_status, os.path.isfile(ca_status))
    else:
        logger.warning("TLS CA certificate bundle could not be automatically resolved")

    from PySide6.QtCore import QDir, QLockFile

    # Single-instance guard to prevent duplicate background processes from
    # conflicting on SQLite database locks and system resources.
    lock_path = os.path.join(QDir.tempPath(), "ihrms_monitor.lock")
    lock_file = QLockFile(lock_path)
    lock_file.setStaleLockTime(15000)

    if not lock_file.tryLock(100):
        # Check if the lock was left behind by a terminated or dead process
        is_stale = False
        try:
            import psutil
            pid, hostname, appname = lock_file.getLockInfo()
            if pid and not psutil.pid_exists(pid):
                is_stale = True
        except Exception:
            pass

        if is_stale:
            try:
                lock_file.removeStaleLockFile()
                lock_file.tryLock(100)
            except Exception:
                pass

    if not lock_file.isLocked():
        logger.warning(
            "Another instance of %s is already running. Exiting gracefully.",
            APP_NAME,
        )
        if not is_startup and sys.platform.startswith("win"):
            try:
                import win32gui
                import win32con

                found_hwnds = []

                def _enum_windows_cb(hwnd, _):
                    if win32gui.IsWindow(hwnd) and not win32gui.GetParent(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        if ("Workpulse" in title or "iHRMS Monitor" in title) and not found_hwnds:
                            try:
                                rect = win32gui.GetWindowRect(hwnd)
                                width = rect[2] - rect[0]
                                height = rect[3] - rect[1]
                                # Only target the actual main application window, not small helper widgets
                                if width < 500 or height < 400:
                                    return
                            except Exception:
                                pass
                            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                            win32gui.SetForegroundWindow(hwnd)
                            found_hwnds.append(hwnd)

                win32gui.EnumWindows(_enum_windows_cb, None)
                if not found_hwnds:
                    QMessageBox.information(
                        None,
                        APP_NAME,
                        f"{APP_NAME} is already running in the background or system tray.",
                    )
            except Exception:
                pass
        return 0
    app._instance_lock = lock_file

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

    # Auto-start registration check & sync with user preferences
    try:
        from database.database import get_session
        from services.settings_service import SettingsService
        from system import startup

        app_settings = SettingsService(get_session).get_settings()
        if app_settings.start_with_system:
            startup.ensure_startup_registered()
    except Exception as auto_reg_err:
        logger.warning("Error checking auto-start registration on startup: %s", auto_reg_err)

    # Verify whether an auto-update just occurred and prevent restart loops
    try:
        from services.update_service import verify_post_restart_update
        verified, update_msg = verify_post_restart_update()
        logger.info("Startup update check: %s", update_msg)
    except Exception as up_err:
        logger.debug("Startup update check exception: %s", up_err)

    # Imported after QApplication exists, since it builds widgets.
    from ui.login_window import LoginWindow
    from services.secure_session import SessionStore
    from services.session_service import SessionService
    from config.api_config import ApiConfig

    # Check for a saved session and attempt to restore it
    session_store = SessionStore()
    saved_session = session_store.load_session()

    if saved_session:
        logger.info("Found saved session for user: %s (company: %s)", saved_session.get("username"), saved_session.get("company_code"))
        
        try:
            # Restore the company context immediately from cached session to guarantee zero UI startup delay
            api_config = ApiConfig()
            company_code = saved_session.get("company_code")
            base_url = saved_session.get("base_url")
            company_id = saved_session.get("company_id")

            if company_code and base_url:
                api_config.set_cached_configuration(
                    company_code=company_code,
                    base_url=base_url,
                    company_id=company_id,
                )
            elif company_code:
                try:
                    api_config.load(company_code=company_code, force=False)
                except Exception as net_err:
                    logger.warning("Could not reach verification service online on startup: %s", net_err)

            # Restore the session
            SessionService().restore_session(
                username=saved_session["username"],
                role=saved_session.get("user_type", "User"),
                full_name=saved_session.get("full_name"),
                user_type=saved_session.get("user_type", "User"),
                workpulse_permitted=saved_session.get("workpulse_permitted", True),
                allow_user_device=saved_session.get("allow_user_device", True),
                allow_logout=saved_session.get("allow_logout", True),
                indo_code=saved_session["indo_code"],
                api_key=saved_session["api_key"],
                employee_id=saved_session.get("employee_id"),
                company_code=saved_session["company_code"],
                device_token=saved_session["device_token"],
            )

            logger.info("Session restored successfully for user: %s", saved_session.get("username"))

            # Open main window and handle background vs foreground startup
            from ui.main_window import MainWindow
            main_window = MainWindow(login_window=None)
            app.aboutToQuit.connect(main_window._shutdown)

            if is_startup:
                logger.info("Workpulse started silently in the background / system tray.")
                main_window.hide()
                if hasattr(main_window, "tray") and main_window.tray:
                    main_window.tray.show()
                    main_window.tray.show_message(
                        APP_NAME,
                        f"{APP_NAME} is active in the background.",
                    )
            else:
                main_window.show()
                main_window.raise_()
                main_window.activateWindow()
                if hasattr(main_window, "tray") and main_window.tray:
                    main_window.tray.show_message(
                        APP_NAME,
                        f"{APP_NAME} has started."
                    )
            
            return app.exec()

        except Exception as restore_err:
            logger.exception("Failed to restore session: %s", restore_err)
            # Only clear the session if the stored data is genuinely corrupted or invalid
            if not session_store.validate_session():
                logger.warning("Session data is corrupted. Clearing session store.")
                session_store.clear_session()

    # No valid session found, show login window
    logger.info("No saved session found; displaying login window.")
    login_window = LoginWindow()
    login_window.show()
    login_window.raise_()
    login_window.activateWindow()

    return app.exec()




if __name__ == "__main__":
    sys.exit(main())
