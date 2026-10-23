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

import os
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


def _is_real_ihrms_process_running(target_pid: int | None) -> bool:
    """Verify if target_pid corresponds to a genuine live iHRMS Desktop process."""
    if not target_pid or target_pid <= 0 or target_pid == os.getpid():
        return False
    try:
        import psutil
        if not psutil.pid_exists(target_pid):
            return False
        proc = psutil.Process(target_pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return False
        name = proc.name().lower()
        if "supervisor" in name:
            return False
        if any(n in name for n in ("ihrms", "workpulse")):
            return True
        if "python" in name:
            try:
                cmdline = " ".join(proc.cmdline()).lower()
                if "supervisor" in cmdline:
                    return False
                if any(c in cmdline for c in ("app.py", "ihrms", "workpulse")):
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


def ensure_supervisor_running() -> bool:
    """Ensure the transparent iHRMS Desktop Supervisor is active in the background on Windows."""
    if not sys.platform.startswith("win"):
        return False
    if os.environ.get("IHRMS_SUPERVISED") == "1" or os.environ.get("IHRMS_DISABLE_SUPERVISOR") == "1":
        return False
    if any(
        arg.lower() in (
            "--no-supervisor",
            "/no-supervisor",
            "-no-supervisor",
            "--supervisor",
            "/supervisor",
            "-supervisor",
            "--supervised",
            "/supervised",
            "-supervised",
        )
        for arg in sys.argv
    ):
        return False
    if "unittest" in sys.modules or any("test" in arg.lower() for arg in sys.argv):
        if os.environ.get("IHRMS_ENABLE_TEST_SUPERVISOR") != "1":
            return False

    try:
        from system.supervisor import is_supervisor_running
        if is_supervisor_running():
            logger.info("iHRMS Desktop Supervisor is already active.")
            return True

        cur_pid = os.getpid()
        if getattr(sys, "frozen", False):
            exe = sys.executable
            exe_dir = Path(exe).parent
            sup_exe = exe_dir / "iHRMS-Supervisor.exe"
            if sup_exe.is_file():
                cmd = [str(sup_exe), "--supervisor", "--monitor-pid", str(cur_pid)]
            elif "python" not in os.path.basename(exe).lower():
                cmd = [exe, "--supervisor", "--monitor-pid", str(cur_pid)]
            else:
                from system.startup import _find_windows_executable
                found_exe = _find_windows_executable()
                if found_exe and found_exe.is_file():
                    found_sup = found_exe.parent / "iHRMS-Supervisor.exe"
                    if found_sup.is_file():
                        cmd = [str(found_sup), "--supervisor", "--monitor-pid", str(cur_pid)]
                    else:
                        cmd = [str(found_exe), "--supervisor", "--monitor-pid", str(cur_pid)]
                else:
                    cmd = [sys.executable, os.path.abspath(__file__), "--supervisor", "--monitor-pid", str(cur_pid)]
        else:
            from system.startup import _find_windows_executable
            found_exe = _find_windows_executable()
            if found_exe and (found_exe.parent / "iHRMS-Supervisor.exe").is_file():
                cmd = [str(found_exe.parent / "iHRMS-Supervisor.exe"), "--supervisor", "--monitor-pid", str(cur_pid)]
            else:
                app_py = os.path.abspath(__file__)
                cmd = [sys.executable, app_py, "--supervisor", "--monitor-pid", str(cur_pid)]

        if any(arg.lower() in ("--startup", "/startup", "-startup", "--minimized", "--background", "--hidden", "-s", "-b") for arg in sys.argv):
            cmd.append("--startup")

        logger.info("Launching iHRMS Desktop Supervisor: %s", " ".join(cmd))
        from system.supervisor import spawn_detached_process
        pid, _ = spawn_detached_process(cmd)
        return pid is not None
    except Exception as exc:
        logger.warning("Could not launch iHRMS Desktop Supervisor: %s", exc)
        return False


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

    from ui.keyboard_navigation import KeyboardNavigationEventFilter
    KeyboardNavigationEventFilter.install()

    if "--test-screenshot" in sys.argv:
        from services.screenshot import capture_screenshot
        path = capture_screenshot()
        print(f"TEST_SCREENSHOT_RESULT: {path}", flush=True)
        return 0 if path else 1

    if "--trigger-test-error" in sys.argv or "--test-error-reporting" in sys.argv:
        import json
        from services.error_report_service import ErrorReportService
        force_email = "--force-email" in sys.argv
        clear_cooldown = "--clear-cooldown" in sys.argv
        res = ErrorReportService().trigger_test_error(
            synchronous=True,
            force_email=force_email,
            clear_cooldown=clear_cooldown,
        )
        print(f"TEST_ERROR_RESULT: {json.dumps(res, default=str)}", flush=True)
        return 0

    # Allow clean exit if LoginWindow is closed without authentication
    app.setQuitOnLastWindowClosed(True)
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
        arg.lower() in (
            "--startup",
            "/startup",
            "-startup",
            "--minimized",
            "/minimized",
            "-minimized",
            "--background",
            "/background",
            "-background",
            "--autostart",
            "/autostart",
            "-autostart",
            "--hidden",
            "/hidden",
            "-hidden",
            "--silent",
            "/silent",
            "-silent",
            "-s",
            "/s",
            "-b",
            "/b",
        )
        for arg in sys.argv[1:]
    )
    if is_startup:
        logger.info("iHRMS Desktop launched through Windows startup / background mode (%s)", sys.argv)
    else:
        logger.info("iHRMS Desktop launched manually by user (%s)", sys.argv)

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

    # Transparent supervisor invocation
    if any(arg.lower() in ("--supervisor", "/supervisor", "-supervisor") for arg in sys.argv[1:]):
        from system.supervisor import run_supervisor
        target_args = []
        monitor_pid = None
        args = sys.argv[1:]
        i = 0
        while i < len(args):
            arg = args[i]
            if arg.lower() in ("--supervisor", "/supervisor", "-supervisor"):
                i += 1
            elif arg.lower() in ("--monitor-pid", "-monitor-pid", "/monitor-pid"):
                if i + 1 < len(args) and args[i + 1].isdigit():
                    monitor_pid = int(args[i + 1])
                    i += 2
                else:
                    i += 1
            else:
                target_args.append(arg)
                i += 1
        return run_supervisor(target_args=target_args or ["--startup"], monitor_pid=monitor_pid)

    from PySide6.QtCore import QDir, QLockFile


    # Single-instance guard to prevent duplicate background processes from
    # conflicting on SQLite database locks and system resources.
    lock_path = os.path.join(QDir.tempPath(), "ihrms_monitor.lock")
    lock_file = QLockFile(lock_path)
    lock_file.setStaleLockTime(15000)

    if not lock_file.tryLock(100):
        # Inspect lock info
        pid = None
        try:
            pid, _, _ = lock_file.getLockInfo()
        except Exception:
            pass

        # If previous instance terminated, crashed, or PID was recycled by OS, clear stale lock
        if not _is_real_ihrms_process_running(pid):
            logger.info("Lock file was left behind by terminated or inactive PID %s. Clearing stale lock.", pid)
            try:
                lock_file.removeStaleLockFile()
                lock_file.tryLock(200)
            except Exception as lock_err:
                logger.debug("Could not remove stale lock via QLockFile: %s", lock_err)
            
            # If QLockFile still considers it locked despite dead process, unlink orphaned file
            if not lock_file.isLocked():
                try:
                    if os.path.isfile(lock_path):
                        os.remove(lock_path)
                    lock_file = QLockFile(lock_path)
                    lock_file.setStaleLockTime(15000)
                    lock_file.tryLock(200)
                except Exception as rem_err:
                    logger.debug("Could not delete orphaned lock file: %s", rem_err)

    if not lock_file.isLocked():
        logger.warning(
            "Another active instance of %s is already running. Exiting gracefully.",
            APP_NAME,
        )
        if not is_startup:
            if sys.platform.startswith("win"):
                try:
                    import win32gui
                    import win32con
                    import win32process

                    import time

                    pid = None
                    try:
                        pid, _, _ = lock_file.getLockInfo()
                    except Exception:
                        pass

                    def _find_genuine_windows():
                        genuine_hwnds = []

                        def _enum_windows_cb(hwnd, _):
                            if not win32gui.IsWindow(hwnd):
                                return
                            try:
                                # 1. Must be a top-level window (no parent)
                                if win32gui.GetParent(hwnd):
                                    return

                                # 2. Match PID if known
                                _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
                                if pid and win_pid != pid:
                                    return

                                # 3. Class name must NOT be internal Qt helper or observer window
                                cls = (win32gui.GetClassName(hwnd) or "").lower()
                                if any(k in cls for k in ("observer", "titlebar", "cicloader", "trayicon", "ime", "uac", "indicator", "message")):
                                    return

                                # 4. Title must be non-empty and match application window title
                                title = (win32gui.GetWindowText(hwnd) or "").strip()
                                if not title or not any(t in title for t in ("iHRMS Desktop", "Workpulse", "iHRMS Monitor")):
                                    return

                                genuine_hwnds.append(hwnd)
                            except Exception:
                                pass

                        win32gui.EnumWindows(_enum_windows_cb, None)
                        return genuine_hwnds

                    # Wait briefly (up to ~1s) if the primary instance is in the process of creating its window
                    found_hwnds = []
                    for _ in range(5):
                        found_hwnds = _find_genuine_windows()
                        if found_hwnds:
                            break
                        time.sleep(0.2)

                    for hwnd in found_hwnds:
                        try:
                            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                            win32gui.SetForegroundWindow(hwnd)
                        except Exception:
                            pass
                except Exception:
                    pass
            elif sys.platform == "darwin":
                try:
                    import subprocess
                    subprocess.run(
                        ["osascript", "-e", 'tell application id "com.indovision.ihrms-desktop" to activate'],
                        capture_output=True,
                        timeout=3,
                    )
                except Exception:
                    pass
        # Exit immediately - do not create any further Qt objects that would appear as blank taskbar previews.
        return 0

    app._instance_lock = lock_file
    try:
        from services.secure_session import SessionStore
        SessionStore().set_clean_shutdown(False)
    except Exception:
        pass
    ensure_supervisor_running()

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
                company_id=saved_session.get("company_id") or getattr(api_config, "company_id", None),
                base_url=saved_session.get("base_url") or getattr(api_config, "base_url", None),
                portal_url=saved_session.get("portal_url") or getattr(api_config, "portal_url", None),
                logo_url=saved_session.get("logo_url") or getattr(api_config, "logo_url", None),
                email=saved_session.get("email"),
                device_token=saved_session["device_token"],
                session_credential=saved_session.get("session_credential"),
            )

            logger.info("Session restored successfully for user: %s", saved_session.get("username"))

            # Open main window and handle background vs foreground startup
            from ui.main_window import MainWindow
            main_window = MainWindow(login_window=None, is_background=is_startup)
            app.aboutToQuit.connect(main_window._shutdown)

            if is_startup:
                logger.info("iHRMS Desktop started silently in the background / system tray.")
                main_window.hide()
                if hasattr(main_window, "tray") and main_window.tray:
                    main_window.tray.show()
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
