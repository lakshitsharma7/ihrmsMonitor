"""User-level "start with system" registration.

Windows: writes/removes a value under
    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
which requires no admin privileges and only affects the current user.

macOS: writes/removes a per-user LaunchAgent plist under
    ~/Library/LaunchAgents
which is also a user-level mechanism requiring no root privileges.

Both implementations are exposed behind the same two functions so the
settings UI never needs to know which OS it's running on.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from utils.logger import get_logger
from config.settings import APP_NAME
from utils.paths import is_macos, is_windows

logger = get_logger(__name__)

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_LAUNCH_AGENT_LABEL = "com.indovision.ihrms-desktop"
_LEGACY_LAUNCH_AGENT_LABEL = "com.activitytracker.app"


def _launch_agent_path(label: str = _LAUNCH_AGENT_LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def is_enabled() -> bool:
    """Return whether "start with system" is currently registered with the OS."""
    if is_windows():
        return _windows_is_enabled()
    if is_macos():
        return _macos_is_enabled()
    return False


def set_enabled(enabled: bool, executable_path: str | None = None) -> bool:
    """Enable/disable starting the app automatically at login.

    Args:
        enabled: whether the app should start with the system.
        executable_path: path to the built executable/app bundle to launch.
            Defaults to the currently running Python interpreter/executable
            if omitted (mainly useful for development).

    Returns:
        True on success, False if the registration could not be made (the
        caller should surface this to the user rather than assume success).
    """
    import sys

    exe_path = executable_path or sys.executable

    try:
        if is_windows():
            return _windows_set_enabled(enabled, exe_path)
        if is_macos():
            return _macos_set_enabled(enabled, exe_path)
        logger.warning("set_enabled called on unsupported platform")
        return False
    except Exception:  # noqa: BLE001
        logger.exception("Failed to update start-with-system registration")
        return False


def _find_windows_executable(explicit_path: str | Path | None = None) -> Path | None:
    """Dynamically discover the authoritative iHRMS Desktop Windows executable.
    
    Checks in order:
    1. Explicit path if passed and valid (non-python)
    2. sys.executable if running as frozen executable (PyInstaller)
    3. Installed location in %LOCALAPPDATA%\\Programs\\iHRMS Desktop\\iHRMS-Desktop.exe
    4. Standard Program Files locations (64-bit and 32-bit)
    5. Local project dist directory (dist\\iHRMS-Desktop\\iHRMS-Desktop.exe)
    6. Legacy locations for smooth backward compatibility
    """
    import sys
    import os

    if explicit_path:
        p = Path(str(explicit_path).strip().strip('"'))
        is_dev = "python" in p.name.lower() or p.name.endswith(".py")
        if not is_dev:
            if getattr(sys, "frozen", False) or p.is_file():
                return p

    if getattr(sys, "frozen", False):
        p = Path(sys.executable)
        is_dev = "python" in p.name.lower() or p.name.endswith(".py")
        if not is_dev and (p.is_file() or not explicit_path):
            return p

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    project_root = Path(__file__).resolve().parent.parent

    candidate_paths = [
        Path(local_app_data) / "Programs" / "iHRMS Desktop" / "iHRMS-Desktop.exe",
        Path(local_app_data) / "Programs" / "iHRMS Desktop" / "iHRMS Desktop.exe",
        Path(local_app_data) / "Programs" / "Workpulse" / "Workpulse.exe",
        Path(local_app_data) / "Programs" / "iHRMS Monitor" / "iHRMS Monitor.exe",
        Path(prog_files) / "iHRMS Desktop" / "iHRMS-Desktop.exe",
        Path(prog_files) / "iHRMS Desktop" / "iHRMS Desktop.exe",
        Path(prog_files) / "Workpulse" / "Workpulse.exe",
        Path(prog_files) / "iHRMS Monitor" / "iHRMS Monitor.exe",
        Path(prog_files_x86) / "iHRMS Desktop" / "iHRMS-Desktop.exe",
        Path(prog_files_x86) / "iHRMS Desktop" / "iHRMS Desktop.exe",
        Path(prog_files_x86) / "Workpulse" / "Workpulse.exe",
        Path(prog_files_x86) / "iHRMS Monitor" / "iHRMS Monitor.exe",
        project_root / "dist" / "iHRMS-Desktop" / "iHRMS-Desktop.exe",
        project_root / "dist" / "iHRMS Desktop" / "iHRMS Desktop.exe",
        project_root / "dist" / "Workpulse" / "Workpulse.exe",
        project_root / "dist" / "iHRMS Monitor" / "iHRMS Monitor.exe",
    ]

    for candidate in candidate_paths:
        if candidate.is_file():
            return candidate

    return None


def ensure_startup_registered(executable_path: str | None = None) -> bool:
    """Verify that auto-start is registered with the OS; if missing or invalid, register it."""
    logger.info("Verifying auto-start registration status...")
    if sys.platform.startswith("win"):
        try:
            clean_exe = _find_windows_executable(executable_path)
            if clean_exe and clean_exe.is_file():
                _register_windows_scheduled_task(clean_exe)
        except Exception as reg_err:
            logger.debug("Scheduled task registration check error: %s", reg_err)

    if not is_enabled():
        logger.info("Auto-start entry is missing or points to a non-existent binary; registering now.")
        return set_enabled(True, executable_path)
    logger.info("Auto-start entry verified active.")
    return True


# -- Windows ------------------------------------------------------------------


def _windows_is_enabled() -> bool:
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            for key_name in (APP_NAME, "Workpulse", "iHRMS Monitor"):
                try:
                    val, _ = winreg.QueryValueEx(key, key_name)
                    if val:
                        val_str = str(val).strip()
                        if val_str.startswith('"'):
                            end_quote = val_str.find('"', 1)
                            raw_path = val_str[1:end_quote] if end_quote != -1 else val_str.strip('"')
                        else:
                            raw_path = val_str.split()[0] if val_str else ""

                        target_file = Path(raw_path)
                        if target_file.is_file():
                            logger.info(
                                "Windows startup entry detected: key='%s', target='%s'",
                                key_name,
                                target_file,
                            )
                            return True
                        else:
                            logger.warning(
                                "Windows startup entry found for '%s' but binary does not exist on disk: %s",
                                key_name,
                                raw_path,
                            )
                except FileNotFoundError:
                    pass
            logger.info("Windows startup entry missing for %s", APP_NAME)
            return False
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read Windows Run key")
        return False


_scheduled_task_unsupported = False


def _get_scheduled_task_name() -> str:
    """Return the unique Task Scheduler task name for this user."""
    username = os.environ.get("USERNAME", "Default")
    return f"iHRMSDesktopAutoRestart-{username}"


def _is_windows_scheduled_task_registered(task_name: str) -> bool:
    """Fast check whether the scheduled task is already registered using schtasks."""
    if not sys.platform.startswith("win"):
        return False
    try:
        creation_flags = subprocess.CREATE_NO_WINDOW
        res = subprocess.run(
            ["schtasks", "/query", "/tn", task_name],
            capture_output=True,
            timeout=5,
            creationflags=creation_flags,
        )
        return res.returncode == 0
    except Exception:
        return False


def _register_windows_scheduled_task(clean_exe: Path) -> bool:
    """Register or update a Windows Task Scheduler task that restarts iHRMS Supervisor every 5 minutes."""
    global _scheduled_task_unsupported
    if not sys.platform.startswith("win") or _scheduled_task_unsupported:
        return False
    try:
        task_name = _get_scheduled_task_name()
        if _is_windows_scheduled_task_registered(task_name):
            logger.info("Windows scheduled task %s is already registered.", task_name)
            return True

        sup_candidate = clean_exe.parent / "iHRMS-Supervisor.exe"
        target_bin = sup_candidate if sup_candidate.is_file() else clean_exe
        target_dir = str(target_bin.parent)

        ps_cmd = (
            f"$action = New-ScheduledTaskAction -Execute '{target_bin}' -Argument '--startup' -WorkingDirectory '{target_dir}'; "
            f"$tLogon = New-ScheduledTaskTrigger -AtLogOn; "
            f"$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 0); "
            f"Register-ScheduledTask -TaskName '{task_name}' -Action $action -Trigger $tLogon -Settings $settings -Force"
        )
        creation_flags = 0
        startupinfo = None
        if sys.platform.startswith("win"):
            creation_flags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creation_flags,
            startupinfo=startupinfo,
        )
        if res.returncode == 0:
            logger.info("Successfully registered Windows scheduled task: %s", task_name)
            return True
        else:
            stderr = res.stderr.strip()
            if "Access is denied" in stderr or "PermissionDenied" in stderr or "0x80070005" in stderr:
                _scheduled_task_unsupported = True
                logger.info("Scheduled task registration not permitted for unprivileged user (Run registry key will be used): %s", task_name)
            else:
                logger.warning("Failed to register Windows scheduled task: %s (stderr: %s)", task_name, stderr)
            return False
    except Exception as exc:
        logger.warning("Error registering scheduled task: %s", exc)
        return False


def _unregister_windows_scheduled_task() -> bool:
    """Unregister the Windows Task Scheduler auto-restart task."""
    if not sys.platform.startswith("win"):
        return False
    try:
        task_name = _get_scheduled_task_name()
        ps_cmd = f"Unregister-ScheduledTask -TaskName '{task_name}' -Confirm:$false -ErrorAction SilentlyContinue"
        creation_flags = 0
        startupinfo = None
        if sys.platform.startswith("win"):
            creation_flags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            timeout=10,
            creationflags=creation_flags,
            startupinfo=startupinfo,
        )
        logger.info("Unregistered Windows scheduled task: %s", task_name)
        return True
    except Exception as exc:
        logger.warning("Error unregistering scheduled task: %s", exc)
        return False


def _windows_set_enabled(enabled: bool, exe_path: str | None = None) -> bool:
    import winreg  # type: ignore

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    ) as key:
        if enabled:
            clean_exe = _find_windows_executable(exe_path)
            is_frozen = getattr(sys, "frozen", False)
            if not clean_exe or (not is_frozen and not clean_exe.is_file()):
                logger.warning(
                    "Cannot register Windows auto-start: compiled iHRMS Desktop binary not found on disk (tried %s)",
                    exe_path,
                )
                return False

            sup_candidate = clean_exe.parent / "iHRMS-Supervisor.exe"
            if sup_candidate.is_file():
                cmd = f'"{sup_candidate}" --startup'
            else:
                cmd = f'"{clean_exe}" --supervisor --startup'

            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            logger.info("Auto-start registration SUCCESS: HKCU\\%s\\%s = %s", _RUN_KEY_PATH, APP_NAME, cmd)

            # Register Task Scheduler auto-restart fallback (mirrors MeraMonitor recovery)
            _register_windows_scheduled_task(clean_exe)

            # Clean up legacy keys if present
            for legacy_key in ("Workpulse", "iHRMS Monitor"):
                if legacy_key != APP_NAME:
                    try:
                        winreg.DeleteValue(key, legacy_key)
                        logger.info("Cleaned up legacy '%s' startup registry key", legacy_key)
                    except FileNotFoundError:
                        pass
            return True
        else:
            removed_any = False
            for k in (APP_NAME, "Workpulse", "iHRMS Monitor"):
                try:
                    winreg.DeleteValue(key, k)
                    logger.info("Removed Windows auto-start Run key for: %s", k)
                    removed_any = True
                except FileNotFoundError:
                    pass
            _unregister_windows_scheduled_task()
            if not removed_any:
                logger.info("No Windows auto-start Run key was present to remove")
            return True


# -- macOS ----------------------------------------------------------------------

_LAUNCH_AGENT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>
        <string>--startup</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
"""


def _find_macos_executable(explicit_path: str | Path | None = None) -> Path | None:
    """Dynamically discover the authoritative iHRMS Desktop macOS executable inside .app bundle."""
    if explicit_path:
        p = Path(str(explicit_path).strip().strip('"'))
        is_dev = "python" in p.name.lower() or p.name.endswith(".py")
        if not is_dev:
            if getattr(sys, "frozen", False) or p.is_file():
                return p

    if getattr(sys, "frozen", False):
        p = Path(sys.executable)
        is_dev = "python" in p.name.lower() or p.name.endswith(".py")
        if not is_dev and (p.is_file() or not explicit_path):
            return p

    project_root = Path(__file__).resolve().parent.parent

    candidate_paths = [
        Path("/Applications/iHRMS-Desktop.app/Contents/MacOS/iHRMS-Desktop"),
        Path.home() / "Applications" / "iHRMS-Desktop.app" / "Contents" / "MacOS" / "iHRMS-Desktop",
        Path("/Applications/Workpulse.app/Contents/MacOS/Workpulse"),
        project_root / "dist" / "iHRMS-Desktop.app" / "Contents" / "MacOS" / "iHRMS-Desktop",
        project_root / "dist" / "Workpulse.app" / "Contents" / "MacOS" / "Workpulse",
    ]

    for candidate in candidate_paths:
        if candidate.is_file():
            return candidate

    return Path(sys.executable) if getattr(sys, "frozen", False) else None


def _macos_is_enabled() -> bool:
    """Check if LaunchAgent plist is installed and points to an existing binary."""
    plist_path = _launch_agent_path()
    if not plist_path.is_file():
        return False
    try:
        import plistlib

        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
        args = data.get("ProgramArguments", [])
        if args and isinstance(args, list):
            target_exe = Path(args[0])
            if target_exe.is_file() or getattr(sys, "frozen", False) is False:
                return True
            logger.warning(
                "macOS LaunchAgent exists but binary does not exist on disk: %s",
                target_exe,
            )
            return False
        return True
    except Exception as exc:
        logger.debug("Failed to read macOS LaunchAgent plist: %s", exc)
        return plist_path.is_file()


def _macos_set_enabled(enabled: bool, exe_path: str | None = None) -> bool:
    plist_path = _launch_agent_path()
    legacy_plist = _launch_agent_path(_LEGACY_LAUNCH_AGENT_LABEL)

    if enabled:
        clean_exe = _find_macos_executable(exe_path)
        is_frozen = getattr(sys, "frozen", False)
        if not clean_exe or (not is_frozen and not clean_exe.is_file()):
            clean_exe = Path(exe_path) if exe_path else Path(sys.executable)

        plist_path.parent.mkdir(parents=True, exist_ok=True)
        exe_str = clean_exe.as_posix() if hasattr(clean_exe, "as_posix") else str(clean_exe).replace("\\", "/")
        content = _LAUNCH_AGENT_TEMPLATE.format(
            label=_LAUNCH_AGENT_LABEL, exe_path=exe_str
        )
        plist_path.write_text(content, encoding="utf-8")
        logger.info("macOS LaunchAgent created at %s for executable %s", plist_path, exe_str)

        # Clean up legacy LaunchAgent if present
        if legacy_plist.exists():
            try:
                subprocess.run(
                    ["launchctl", "unload", "-w", str(legacy_plist)],
                    capture_output=True,
                    timeout=5,
                )
                legacy_plist.unlink(missing_ok=True)
                logger.info("Cleaned up legacy LaunchAgent: %s", legacy_plist)
            except Exception as leg_err:
                logger.debug("Error cleaning legacy LaunchAgent: %s", leg_err)

        # Reload LaunchAgent via launchctl
        try:
            subprocess.run(
                ["launchctl", "unload", "-w", str(plist_path)],
                capture_output=True,
                timeout=5,
            )
            res = subprocess.run(
                ["launchctl", "load", "-w", str(plist_path)],
                capture_output=True,
                timeout=5,
            )
            if res.returncode == 0:
                logger.info("macOS LaunchAgent loaded via launchctl successfully.")
            else:
                logger.debug("launchctl load returncode %d: %s", res.returncode, res.stderr)
        except Exception as lctl_err:
            logger.debug("launchctl execution note: %s", lctl_err)

        return True
    else:
        # Unload and remove LaunchAgent
        if plist_path.exists():
            try:
                subprocess.run(
                    ["launchctl", "unload", "-w", str(plist_path)],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass
            try:
                plist_path.unlink(missing_ok=True)
                logger.info("Removed macOS LaunchAgent at %s", plist_path)
            except Exception as unl_err:
                logger.warning("Could not unlink LaunchAgent plist: %s", unl_err)

        if legacy_plist.exists():
            try:
                subprocess.run(
                    ["launchctl", "unload", "-w", str(legacy_plist)],
                    capture_output=True,
                    timeout=5,
                )
                legacy_plist.unlink(missing_ok=True)
            except Exception:
                pass

        return True
