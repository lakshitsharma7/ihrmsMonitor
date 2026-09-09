"""Device identity helpers.

The login API expects a device identifier and a device description. On a
phone those are the IMEI and the handset model; on a desktop the equivalent
is a stable per-machine id plus the machine/OS description. These are read
from the current machine so that no device value is hardcoded.
"""

from __future__ import annotations

import getpass
import platform
import socket
import uuid

from utils.logger import get_logger


logger = get_logger(__name__)


def _windows_machine_guid() -> str | None:
    """Return the Windows MachineGuid, which is stable per installation."""

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            value, _ = winreg.QueryValueEx(
                key,
                "MachineGuid",
            )

        value = str(value).strip()

        return value or None

    except Exception:  # noqa: BLE001
        logger.debug(
            "MachineGuid unavailable",
            exc_info=True,
        )

        return None


def _macos_hardware_uuid() -> str | None:
    """Return the macOS hardware UUID, which is stable per machine."""

    try:
        import subprocess

        output = subprocess.check_output(
            [
                "ioreg",
                "-d2",
                "-c",
                "IOPlatformExpertDevice",
            ],
            text=True,
            timeout=5,
        )

        for line in output.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2].strip() or None

    except Exception:  # noqa: BLE001
        logger.debug(
            "IOPlatformUUID unavailable",
            exc_info=True,
        )

    return None


def get_device_identifier() -> str:
    """
    Return a stable identifier for this machine.

    Sent as ``imei_number``: the desktop equivalent of a handset IMEI.
    Persisted via QSettings to ensure consistent identity across restarts,
    logins, and background sync without generating duplicate devices.
    """
    try:
        from PySide6.QtCore import QSettings

        settings = QSettings("Indovision", "iHRMSMonitor")
        saved_id = str(settings.value("device/device_identifier") or "").strip()
        if saved_id:
            return saved_id
    except Exception:
        settings = None

    system = platform.system()

    if system == "Windows":
        identifier = _windows_machine_guid()

    elif system == "Darwin":
        identifier = _macos_hardware_uuid()

    else:
        identifier = None

    if not identifier:
        # uuid.getnode() is derived from the MAC address when one is
        # available, and is stable for the life of the interface.
        identifier = f"{uuid.getnode():012x}"

    if identifier and settings:
        try:
            settings.setValue("device/device_identifier", identifier)
        except Exception:
            pass

    return identifier


def get_dynamic_os_type() -> str:
    """
    Return dynamic operating-system type matching backend API expectations.

    The backend expects 'window' on Windows (singular lowercase),
    'macos' on macOS, and 'linux' on Linux.
    """
    system = platform.system().lower()
    if "win" in system:
        return "window"
    elif "darwin" in system or "mac" in system:
        return "macos"
    elif "linux" in system:
        return "linux"
    return system


def get_device_detail() -> str:
    """
    Return a dynamically detected, human-readable description of this machine
    (e.g., 'Dell Inc. Latitude 7490', 'Samsung PC', or 'MacBookPro18,1').

    Sent as ``device_detail``: the desktop equivalent of a handset model.
    """
    system = platform.system()

    if system == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\BIOS",
            ) as key:
                try:
                    mfg, _ = winreg.QueryValueEx(key, "SystemManufacturer")
                except Exception:
                    mfg = ""
                try:
                    prod, _ = winreg.QueryValueEx(key, "SystemProductName")
                except Exception:
                    prod = ""

            mfg = str(mfg or "").strip()
            prod = str(prod or "").strip()

            # Ignore generic placeholders
            generic = ("system manufacturer", "system product name", "to be filled by o.e.m.", "default string")
            parts = []
            if mfg and mfg.lower() not in generic:
                parts.append(mfg)
            if prod and prod.lower() not in generic:
                parts.append(prod)

            if parts:
                return " ".join(" ".join(parts).split())
        except Exception:
            pass

    elif system == "Darwin":
        try:
            import subprocess
            model = subprocess.check_output(["sysctl", "-n", "hw.model"], text=True, timeout=3).strip()
            if model:
                return f"Apple {model}"
        except Exception:
            pass

    # Fallback to system and machine architecture
    machine = platform.machine() or "unknown"
    release = platform.release() or ""
    detail = f"{system} {release} ({machine})".strip()
    return " ".join(detail.split())


def get_device_info() -> dict[str, str]:
    """Return the device fields shared by the login and enrollment APIs."""

    return {
        "device_identifier": get_device_identifier(),
        "device_detail": get_device_detail(),
        "os_type": get_dynamic_os_type(),
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "os_username": _safe_username(),
    }


def _safe_username() -> str:
    try:
        return getpass.getuser()

    except Exception:  # noqa: BLE001
        return "unknown"

