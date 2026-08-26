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
    Falls back through progressively weaker sources so a value is always
    produced.
    """

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

    return identifier


def get_device_detail() -> str:
    """
    Return a human-readable description of this machine.

    Sent as ``device_detail``: the desktop equivalent of a handset model.
    """

    machine = platform.machine() or "unknown"

    release = platform.release() or ""

    system = platform.system() or "unknown"

    detail = f"{system} {release} ({machine})".strip()

    return " ".join(detail.split())


def get_device_info() -> dict[str, str]:
    """Return the device fields shared by the login and enrollment APIs."""

    return {
        "device_identifier": get_device_identifier(),
        "device_detail": get_device_detail(),
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "os_username": _safe_username(),
    }


def _safe_username() -> str:
    try:
        return getpass.getuser()

    except Exception:  # noqa: BLE001
        return "unknown"
