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
import sys
from pathlib import Path

from utils.logger import get_logger
from utils.paths import APP_NAME, is_macos, is_windows

logger = get_logger(__name__)

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_LAUNCH_AGENT_LABEL = "com.activitytracker.app"


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCH_AGENT_LABEL}.plist"


def is_enabled() -> bool:
    """Return whether "start with system" is currently registered with the OS."""
    if is_windows():
        return _windows_is_enabled()
    if is_macos():
        return _launch_agent_path().exists()
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
    """Dynamically discover the authoritative Workpulse Windows executable.
    
    Checks in order:
    1. Explicit path if passed and valid (non-python)
    2. sys.executable if running as frozen executable (PyInstaller)
    3. Installed location in %LOCALAPPDATA%\\Programs\\Workpulse\\Workpulse.exe
    4. Standard Program Files locations (64-bit and 32-bit)
    5. Local project dist directory (dist\\Workpulse\\Workpulse.exe)
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
    logger.info("Verifying Windows auto-start registration status...")
    if not is_enabled():
        logger.info("Auto-start entry is missing or points to a non-existent binary; registering now.")
        return set_enabled(True, executable_path)
    logger.info("Windows auto-start entry verified active.")
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
                    "Cannot register Windows auto-start: compiled Workpulse binary not found on disk (tried %s)",
                    exe_path,
                )
                return False

            cmd = f'"{clean_exe}" --startup'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            logger.info("Auto-start registration SUCCESS: HKCU\\%s\\%s = %s", _RUN_KEY_PATH, APP_NAME, cmd)

            # Clean up legacy key if present
            try:
                winreg.DeleteValue(key, "iHRMS Monitor")
                logger.info("Cleaned up legacy 'iHRMS Monitor' startup registry key")
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
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""


def _macos_set_enabled(enabled: bool, exe_path: str) -> bool:
    plist_path = _launch_agent_path()
    if enabled:
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(
            _LAUNCH_AGENT_TEMPLATE.format(label=_LAUNCH_AGENT_LABEL, exe_path=exe_path)
        )
    else:
        if plist_path.exists():
            plist_path.unlink()
    return True
