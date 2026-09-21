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


# -- Windows ------------------------------------------------------------------


def _windows_is_enabled() -> bool:
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            for key_name in (APP_NAME, "iHRMS Monitor"):
                try:
                    val, _ = winreg.QueryValueEx(key, key_name)
                    if val:
                        return True
                except FileNotFoundError:
                    pass
            return False
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read Windows Run key")
        return False


def _windows_set_enabled(enabled: bool, exe_path: str) -> bool:
    import sys
    import winreg  # type: ignore

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    ) as key:
        if enabled:
            clean_exe = str(exe_path).strip().strip('"')
            # Only register auto-start for packaged/frozen builds or compiled Workpulse.exe.
            # Never register bare python.exe or development scripts.
            is_dev_python = "python" in Path(clean_exe).name.lower() or clean_exe.endswith(".py")
            if not getattr(sys, "frozen", False) and is_dev_python:
                # Check if a compiled binary exists in standard locations
                candidate_paths = [
                    Path(r"C:\Program Files\Workpulse\Workpulse.exe"),
                    Path(r"C:\Program Files (x86)\Workpulse\Workpulse.exe"),
                    Path(__file__).resolve().parent.parent / "dist" / "Workpulse" / "Workpulse.exe",
                    Path(r"C:\Program Files\iHRMS Monitor\iHRMS Monitor.exe"),
                    Path(r"C:\Program Files (x86)\iHRMS Monitor\iHRMS Monitor.exe"),
                    Path(__file__).resolve().parent.parent / "dist" / "iHRMS Monitor" / "iHRMS Monitor.exe",
                ]
                compiled_exe = next((p for p in candidate_paths if p.is_file()), None)
                if compiled_exe:
                    clean_exe = str(compiled_exe)
                    logger.info("Found compiled executable for Windows startup registration: %s", clean_exe)
                else:
                    logger.info(
                        "Skipping Windows startup registration for development interpreter: %s",
                        clean_exe,
                    )
                    for k in (APP_NAME, "iHRMS Monitor"):
                        try:
                            winreg.DeleteValue(key, k)
                        except FileNotFoundError:
                            pass
                    return True

            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{clean_exe}"')
            logger.info("Registered Windows auto-start Run key for: %s", clean_exe)
        else:
            for k in (APP_NAME, "iHRMS Monitor"):
                try:
                    winreg.DeleteValue(key, k)
                    logger.info("Removed Windows auto-start Run key for: %s", k)
                except FileNotFoundError:
                    pass
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
