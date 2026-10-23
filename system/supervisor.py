"""Transparent background supervisor for iHRMS Desktop on Windows.

Provides crash recovery, process health monitoring, and graceful lifecycle
supervision without disguising processes, modifying Task Manager, or
introducing unkillable restart loops.

Key Guarantees:
1. Transparent Process Identity: Identifiable in Task Manager as iHRMS Desktop Supervisor.
2. Clean Exit Respect: If user logs out, clicks Exit, updates, or Windows shuts down,
   the supervisor terminates cleanly and does NOT restart the application.
3. Crash Recovery with Rate Limiting: Recovers from unexpected application crashes,
   capped at max 3 restarts within a 10-minute window to prevent restart loops.
4. Administrator Control: Respects Task Manager / administrative termination without
   stealth watchdogs or anti-kill tricks.
5. Dual-Mode Attachment: Can supervise a child launched by itself or attach to an
   already-running iHRMS Desktop instance by PID (--monitor-pid).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from config.settings import APP_NAME
from utils.logger import get_logger

logger = get_logger(__name__)

SUPERVISOR_NAME = f"{APP_NAME} Supervisor"
SUPERVISOR_LOCK_NAME = "ihrms_supervisor.lock"
SUPERVISOR_MUTEX_NAME = "Local\\iHRMS_Desktop_Supervisor_Mutex"
MAX_CRASH_RESTARTS = 3
CRASH_WINDOW_SECONDS = 600  # 10 minutes

_supervisor_mutex_handle = None


def get_supervisor_lock_path() -> Path:
    """Return the absolute path to the supervisor single-instance lock file."""
    try:
        from PySide6.QtCore import QDir
        temp_dir = Path(QDir.tempPath())
    except Exception:
        temp_dir = Path(os.environ.get("TEMP", os.environ.get("TMP", r"C:\Windows\Temp")))
    return temp_dir / SUPERVISOR_LOCK_NAME


def is_supervisor_running(exclude_pid: int | None = None) -> bool:
    """Check whether an iHRMS Desktop Supervisor process is currently active."""
    cur_pid = exclude_pid or os.getpid()

    # On Windows, check whether the Named Mutex is currently held by another process
    if sys.platform.startswith("win"):
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            h = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, SUPERVISOR_MUTEX_NAME)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
        except Exception:
            pass

    lock_path = get_supervisor_lock_path()
    if lock_path.exists():
        try:
            pid_str = lock_path.read_text(encoding="utf-8").strip()
            if pid_str.isdigit():
                sup_pid = int(pid_str)
                if sup_pid != cur_pid and _is_real_supervisor_process(sup_pid):
                    return True
        except Exception:
            pass

    return _is_supervisor_in_process_list(exclude_pid=cur_pid)


def _is_real_supervisor_process(pid: int) -> bool:
    """Verify if a given PID corresponds to an active iHRMS Desktop Supervisor."""
    try:
        import psutil
        if not psutil.pid_exists(pid):
            return False
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return False
        name = (proc.name() or "").lower()

        # Exclude shell wrappers and general scripting hosts
        if any(sh in name for sh in ("powershell", "pwsh", "cmd.exe", "conhost", "bash")):
            return False

        if "ihrms-supervisor" in name or "ihrms_supervisor" in name:
            return True
        cmdline = " ".join(proc.cmdline() or []).lower()
        if "--supervisor" in cmdline or "-supervisor" in cmdline:
            if "python" in name and any(k in cmdline for k in ("supervisor_entry", "system.supervisor")):
                return True
        return False
    except Exception:
        return False


def _is_supervisor_in_process_list(exclude_pid: int | None = None) -> bool:
    """Scan process table for any active supervisor instance."""
    try:
        import psutil
        cur_pid = exclude_pid or os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.info["pid"] == cur_pid:
                    continue
                name = (proc.info.get("name") or "").lower()

                # Ignore PowerShell, cmd, conhost to avoid false positives from diagnostic commands
                if any(sh in name for sh in ("powershell", "pwsh", "cmd.exe", "conhost", "bash")):
                    continue

                if "ihrms-supervisor" in name or "ihrms_supervisor" in name:
                    return True
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if "--supervisor" in cmdline or "-supervisor" in cmdline:
                    if "python" in name and any(k in cmdline for k in ("supervisor_entry", "system.supervisor")):
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def acquire_supervisor_lock() -> bool:
    """Acquire single-instance lock for the supervisor.
    
    Uses Windows Named Mutex on Windows for atomic kernel-managed locking that
    cannot be left stale after process crashes or Task Manager termination.
    """
    global _supervisor_mutex_handle

    if is_supervisor_running():
        return False

    if sys.platform.startswith("win"):
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183
            handle = kernel32.CreateMutexW(None, True, SUPERVISOR_MUTEX_NAME)
            last_err = kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                if handle:
                    kernel32.CloseHandle(handle)
                return False
            _supervisor_mutex_handle = handle
            # Also write lock file for file-based inspection
            try:
                get_supervisor_lock_path().write_text(str(os.getpid()), encoding="utf-8")
            except Exception:
                pass
            return True
        except Exception as exc:
            logger.warning("Windows mutex error in supervisor lock: %s", exc)

    try:
        get_supervisor_lock_path().write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as exc:
        logger.warning("Could not write supervisor lock file: %s", exc)
        return True


def release_supervisor_lock() -> None:
    """Release single-instance lock when supervisor terminates."""
    global _supervisor_mutex_handle
    if sys.platform.startswith("win") and _supervisor_mutex_handle:
        try:
            import ctypes
            ctypes.windll.kernel32.ReleaseMutex(_supervisor_mutex_handle)
            ctypes.windll.kernel32.CloseHandle(_supervisor_mutex_handle)
        except Exception:
            pass
        _supervisor_mutex_handle = None

    try:
        lock_path = get_supervisor_lock_path()
        if lock_path.exists():
            pid_str = lock_path.read_text(encoding="utf-8").strip()
            if pid_str == str(os.getpid()):
                lock_path.unlink()
    except Exception:
        pass


def _find_running_desktop_pid(exclude_pid: int | None = None) -> int | None:
    """Find the PID of an already running iHRMS Desktop instance, if any."""
    try:
        import psutil
        cur_pid = exclude_pid or os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = proc.info["pid"]
                if pid == cur_pid:
                    continue
                name = (proc.info.get("name") or "").lower()
                if any(sh in name for sh in ("powershell", "pwsh", "cmd.exe", "conhost", "bash")):
                    continue
                if "supervisor" in name:
                    continue

                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
                if "supervisor" in cmdline:
                    continue

                if "ihrms-desktop" in name or "workpulse.exe" in name or "ihrms desktop" in name:
                    return pid
                if "python" in name and "app.py" in cmdline:
                    return pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return None


def _set_supervisor_process_identity() -> None:
    """Explicitly identify this process to Windows and Task Manager."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "IndovisionServices.iHRMSMonitor.Supervisor"
            )
            if ctypes.windll.kernel32.GetConsoleWindow():
                ctypes.windll.kernel32.SetConsoleTitleW(f"{APP_NAME} Supervisor")
        except Exception:
            pass


def spawn_detached_process(
    cmd: list[str],
    cwd: str | Path | None = None,
    env: dict | None = None,
) -> tuple[int | None, subprocess.Popen | None]:
    """Launch a process completely detached from the current process tree and job object."""
    if cwd is None and cmd:
        try:
            exe_candidate = Path(cmd[0])
            if exe_candidate.is_file():
                cwd = str(exe_candidate.parent)
        except Exception:
            pass

    if env is not None:
        # Strip conflicting global python environment variables
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)

    # On Windows, use WMI Win32_Process.Create for session-level independence (unless in unit test)
    if sys.platform.startswith("win") and "unittest" not in sys.modules:
        try:
            import win32com.client
            wmi = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2")
            proc_mgr = wmi.Get("Win32_Process")
            params = proc_mgr.Methods_("Create").InParameters.SpawnInstance_()
            params.CommandLine = " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd)
            if cwd:
                params.CurrentDirectory = str(cwd)
            # Configure Win32_ProcessStartup with SW_HIDE for background/supervisor processes
            startup_cls = wmi.Get("Win32_ProcessStartup")
            startup_inst = startup_cls.SpawnInstance_()
            is_bg = any(k in params.CommandLine.lower() for k in ("--supervisor", "--startup", "--minimized", "--background", "--hidden"))
            if is_bg:
                startup_inst.ShowWindow = 0  # SW_HIDE
            params.ProcessStartupInformation = startup_inst

            res = proc_mgr.ExecMethod_("Create", params)
            if res.ReturnValue == 0 and res.ProcessId:
                logger.info("Spawned independent process via WMI: PID %d (%s) cwd=%s", res.ProcessId, cmd[0], cwd)
                return res.ProcessId, None
        except Exception as wmi_err:
            logger.debug("WMI process creation fallback: %s", wmi_err)

    # Standard fallback via subprocess.Popen
    creation_flags = 0
    startupinfo = None
    if sys.platform.startswith("win"):
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_BREAKAWAY_FROM_JOB = 0x01000000
        CREATE_NO_WINDOW = 0x08000000
        base_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        is_bg = any(k in " ".join(cmd).lower() for k in ("--supervisor", "--startup", "--minimized", "--background", "--hidden"))
        if is_bg:
            startupinfo.wShowWindow = 0  # SW_HIDE
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                creationflags=base_flags | CREATE_BREAKAWAY_FROM_JOB,
                startupinfo=startupinfo,
                close_fds=True,
            )
            return proc.pid, proc
        except Exception:
            creation_flags = base_flags

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        creationflags=creation_flags,
        startupinfo=startupinfo,
        close_fds=True,
    )
    return proc.pid, proc


class ProcessSupervisor:
    """Monitors the iHRMS Desktop process and recovers from unexpected termination."""

    def __init__(self, target_args: list[str] | None = None, monitor_pid: int | None = None) -> None:
        self._target_args = list(target_args or ["--startup"])
        self._initial_pid = monitor_pid
        self._child_pid: int | None = None
        self._child_process: subprocess.Popen | None = None
        self._crash_timestamps: list[float] = []
        self._stop_requested = False

    def _resolve_executable_command(self) -> list[str]:
        """Resolve the command line to launch iHRMS Desktop."""
        if getattr(sys, "frozen", False):
            exe = sys.executable
            exe_dir = Path(exe).parent
            # Look for desktop binary next to supervisor binary
            for candidate_name in ("iHRMS-Desktop.exe", "iHRMS Desktop.exe", "Workpulse.exe", "iHRMS Monitor.exe"):
                candidate = exe_dir / candidate_name
                if candidate.is_file():
                    return [str(candidate)] + list(self._target_args)

            if "python" not in Path(exe).name.lower() and "supervisor" not in Path(exe).name.lower():
                return [exe] + list(self._target_args)

        try:
            from system.startup import _find_windows_executable
            found_exe = _find_windows_executable()
            if found_exe and found_exe.is_file():
                return [str(found_exe)] + list(self._target_args)
        except Exception:
            pass

        # In development mode, invoke python interpreter with app.py
        app_py = Path(__file__).resolve().parent.parent / "app.py"
        return [sys.executable, str(app_py)] + list(self._target_args)

    def _is_clean_shutdown(self) -> bool:
        """Check whether the application signalled a clean shutdown."""
        try:
            from services.secure_session import SessionStore
            return SessionStore().is_clean_shutdown()
        except Exception:
            return False

    def _cleanup_stale_lock(self) -> None:
        """Remove any abandoned ihrms_monitor.lock file before launching instance."""
        try:
            from PySide6.QtCore import QDir
            lock_path = os.path.join(QDir.tempPath(), "ihrms_monitor.lock")
            if os.path.isfile(lock_path):
                os.remove(lock_path)
                logger.info("%s cleaned up stale lock file: %s", SUPERVISOR_NAME, lock_path)
        except Exception as lock_err:
            logger.debug("Failed to remove stale lock file: %s", lock_err)

    def _report_unexpected_termination(self, exit_code: int | None, pid: int | None, recovery_time_s: float | None = None) -> None:
        """Report unexpected termination to ErrorReportService."""
        try:
            from services.error_report_service import ErrorReportService
            ErrorReportService().report_error(
                error_type="APPLICATION_CRASH",
                error_message=f"{APP_NAME} (PID {pid}) terminated unexpectedly with exit code {exit_code}.",
                extra_context={
                    "exit_code": exit_code,
                    "target_pid": pid,
                    "crash_count_in_window": len(self._crash_timestamps),
                    "recovery_time_seconds": recovery_time_s,
                },
            )
        except Exception as rep_err:
            logger.debug("Failed to report application crash: %s", rep_err)

    def _wait_for_pid(self, target_pid: int) -> int | None:
        """Wait for an existing process with target_pid to terminate using Windows handles or psutil."""
        if not target_pid or target_pid <= 0 or target_pid == os.getpid():
            return 0

        # Windows synchronization handle (non-polling, responsive to stop_requested)
        if sys.platform.startswith("win"):
            try:
                import ctypes
                SYNCHRONIZE = 0x00100000
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                WAIT_TIMEOUT = 0x00000102
                h_process = ctypes.windll.kernel32.OpenProcess(
                    SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, target_pid
                )
                if h_process:
                    try:
                        exit_code = ctypes.c_ulong()
                        while not self._stop_requested:
                            res = ctypes.windll.kernel32.WaitForSingleObject(h_process, 500)
                            if res != WAIT_TIMEOUT:
                                ctypes.windll.kernel32.GetExitCodeProcess(h_process, ctypes.byref(exit_code))
                                return exit_code.value
                        return 0
                    finally:
                        ctypes.windll.kernel32.CloseHandle(h_process)
            except Exception as exc:
                logger.debug("Windows handle wait error for PID %s: %s", target_pid, exc)

        # Polling fallback
        try:
            import psutil
            while not self._stop_requested:
                if not psutil.pid_exists(target_pid):
                    break
                time.sleep(0.5)
        except Exception:
            pass
        return 1

    def run(self) -> int:
        """Run the supervisor monitoring loop."""
        if not acquire_supervisor_lock():
            logger.info("%s: Another supervisor instance is already running. Exiting.", SUPERVISOR_NAME)
            return 0

        _set_supervisor_process_identity()
        logger.info("%s started (PID %d). Monitoring %s.", SUPERVISOR_NAME, os.getpid(), APP_NAME)

        def _handle_sig(signum, frame):
            logger.info("%s received signal %s. Shutting down gracefully.", SUPERVISOR_NAME, signum)
            self._stop_requested = True
            try:
                from services.secure_session import SessionStore
                SessionStore().set_clean_shutdown(True)
            except Exception:
                pass
            if self._child_process and self._child_process.poll() is None:
                try:
                    self._child_process.terminate()
                except Exception:
                    pass
            elif self._child_pid:
                try:
                    import psutil
                    if psutil.pid_exists(self._child_pid):
                        psutil.Process(self._child_pid).terminate()
                except Exception:
                    pass

        try:
            signal.signal(signal.SIGINT, _handle_sig)
            signal.signal(signal.SIGTERM, _handle_sig)
        except Exception:
            pass

        # Windows Console Control Handler to gracefully handle Windows Shutdown, Logoff, and Console Close
        _win_ctrl_handler_ref = None
        if sys.platform.startswith("win"):
            try:
                import ctypes
                from ctypes import wintypes
                PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

                def _win_ctrl_handler(ctrl_type: int) -> bool:
                    # 0=CTRL_C, 1=CTRL_BREAK, 2=CTRL_CLOSE, 5=CTRL_LOGOFF, 6=CTRL_SHUTDOWN
                    logger.info("%s received Windows console control event %d. Stopping gracefully.", SUPERVISOR_NAME, ctrl_type)
                    self._stop_requested = True
                    try:
                        from services.secure_session import SessionStore
                        SessionStore().set_clean_shutdown(True)
                    except Exception:
                        pass
                    return True

                _win_ctrl_handler_ref = PHANDLER_ROUTINE(_win_ctrl_handler)
                ctypes.windll.kernel32.SetConsoleCtrlHandler(_win_ctrl_handler_ref, True)
            except Exception as ctrl_err:
                logger.debug("Could not install Windows console control handler: %s", ctrl_err)

        try:
            # Phase 1: If an initial PID was specified, or if an existing desktop is already active:
            monitored_pid = self._initial_pid
            if not monitored_pid or monitored_pid <= 0 or monitored_pid == os.getpid():
                monitored_pid = _find_running_desktop_pid()

            if monitored_pid and monitored_pid > 0 and monitored_pid != os.getpid():
                self._initial_pid = None
                logger.info("%s attached to active %s (PID %d). Monitoring process...", SUPERVISOR_NAME, APP_NAME, monitored_pid)
                exit_code = self._wait_for_pid(monitored_pid)
                logger.info("%s monitored instance (PID %d) exited with code %s.", SUPERVISOR_NAME, monitored_pid, exit_code)

                if self._stop_requested:
                    logger.info("%s stopping upon request.", SUPERVISOR_NAME)
                    return 0

                is_clean = self._is_clean_shutdown()
                if is_clean:
                    logger.info("%s clean shutdown confirmed for PID %d (exit_code=%s). Supervisor exiting.", SUPERVISOR_NAME, monitored_pid, exit_code)
                    return 0

                # Unexpected termination detected!
                recovery_t0 = time.time()
                self._crash_timestamps.append(recovery_t0)
                logger.warning(
                    "%s unexpected termination detected for PID %d (exit_code=%s). Initiating automatic recovery (attempt %d/%d in window)...",
                    APP_NAME,
                    monitored_pid,
                    exit_code,
                    len(self._crash_timestamps),
                    MAX_CRASH_RESTARTS,
                )
                self._report_unexpected_termination(exit_code, monitored_pid)
                self._cleanup_stale_lock()

                backoff_seconds = min(1.5 * len(self._crash_timestamps), 6.0)
                if backoff_seconds > 0:
                    logger.info("%s waiting %.1f seconds before launching recovery instance...", SUPERVISOR_NAME, backoff_seconds)
                    time.sleep(backoff_seconds)

            # Phase 2: Standard monitoring loop (launches and monitors child)
            cmd = self._resolve_executable_command()
            if "--supervised" not in cmd:
                cmd.append("--supervised")

            while not self._stop_requested:
                # Check rate limiting: prune timestamps older than sliding window
                now = time.time()
                self._crash_timestamps = [t for t in self._crash_timestamps if (now - t) < CRASH_WINDOW_SECONDS]

                if len(self._crash_timestamps) >= MAX_CRASH_RESTARTS:
                    logger.error(
                        "%s: Max restart attempts (%d in %d min) reached. Halting supervisor to avoid restart loop.",
                        SUPERVISOR_NAME,
                        MAX_CRASH_RESTARTS,
                        CRASH_WINDOW_SECONDS // 60,
                    )
                    break

                self._cleanup_stale_lock()
                logger.info("%s launching monitored instance: %s", SUPERVISOR_NAME, " ".join(cmd))
                env = dict(os.environ)
                env["IHRMS_SUPERVISED"] = "1"

                try:
                    self._child_pid, self._child_process = spawn_detached_process(cmd, env=env)
                except Exception as launch_err:
                    logger.exception("%s failed to launch child process: %s", SUPERVISOR_NAME, launch_err)
                    time.sleep(3)
                    continue

                if not self._child_pid:
                    logger.error("%s could not determine child PID. Retrying in 3s...", SUPERVISOR_NAME)
                    time.sleep(3)
                    continue

                child_pid = self._child_pid
                logger.info("Monitored %s started with PID %d", APP_NAME, child_pid)

                # Wait for child process to terminate
                try:
                    if self._child_process:
                        exit_code = self._child_process.wait()
                    else:
                        exit_code = self._wait_for_pid(child_pid)
                except KeyboardInterrupt:
                    logger.info("Supervisor interrupted by user.")
                    break

                logger.info("%s (PID %d) exited with code %s", APP_NAME, child_pid, exit_code)

                if self._stop_requested:
                    logger.info("%s stopping upon request.", SUPERVISOR_NAME)
                    break

                # Check if this was an intentional normal exit or logout
                is_clean = self._is_clean_shutdown()
                if is_clean:
                    logger.info(
                        "%s exited cleanly (exit_code=%s, clean_shutdown=True). Supervisor stopping.",
                        APP_NAME,
                        exit_code,
                    )
                    break

                # Unexpected termination / crash
                now = time.time()
                self._crash_timestamps.append(now)
                logger.warning(
                    "%s unexpected termination detected (PID %d, exit_code %s). Attempt %d/%d in window.",
                    APP_NAME,
                    child_pid,
                    exit_code,
                    len(self._crash_timestamps),
                    MAX_CRASH_RESTARTS,
                )

                self._report_unexpected_termination(exit_code, child_pid)
                self._cleanup_stale_lock()

                if len(self._crash_timestamps) < MAX_CRASH_RESTARTS:
                    backoff_seconds = min(1.5 * len(self._crash_timestamps), 6.0)
                    logger.info("%s waiting %.1f seconds before attempting restart recovery...", SUPERVISOR_NAME, backoff_seconds)
                    time.sleep(backoff_seconds)

        finally:
            release_supervisor_lock()
            logger.info("%s finished.", SUPERVISOR_NAME)

        return 0


def run_supervisor(target_args: list[str] | None = None, monitor_pid: int | None = None) -> int:
    """Entry point for running supervisor."""
    supervisor = ProcessSupervisor(target_args=target_args, monitor_pid=monitor_pid)
    return supervisor.run()


def main() -> int:
    """Main CLI entrypoint for iHRMS-Supervisor."""
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


if __name__ == "__main__":
    sys.exit(main())
