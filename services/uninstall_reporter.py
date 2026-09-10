"""Uninstall detection and reporting service for iHRMS Monitor.

Handles:
1. Collecting full user and device details at the moment of uninstallation:
   - User ID / Employee ID
   - Username
   - Company code / name
   - Device identifier / Device ID
   - Hostname & Operating System
   - Application version
   - Exact uninstall timestamp (Local & UTC)
2. Immediate dispatch if internet connectivity is available.
3. Offline queueing: If internet is unavailable during uninstallation, stores the event
   in a persistent location (%LOCALAPPDATA%\\iHRMS Monitor\\pending_uninstall.json)
   and configures a lightweight scheduled task to retry automatically once internet
   is restored.
4. Guaranteed single delivery (deduplication): Cleans up the queue and scheduled task
   immediately upon successful delivery.
5. Strict isolation: Normal offline events, network disconnections, app crashes,
   or system restarts NEVER trigger an uninstall alert.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import APP_NAME, APP_VERSION, get_running_app_version
from utils.device import get_device_identifier
from utils.logger import get_logger
from utils.paths import get_app_data_directory

logger = get_logger(__name__)

PENDING_UNINSTALL_FILENAME = "pending_uninstall.json"


def get_pending_uninstall_path() -> Path:
    """Return the filesystem path for the pending uninstall event file."""
    try:
        data_dir = get_app_data_directory()
    except Exception:
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        data_dir = Path(base) / APP_NAME
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / PENDING_UNINSTALL_FILENAME


def collect_uninstall_context(
    employee_id: Optional[str] = None,
    username: Optional[str] = None,
    company_code: Optional[str] = None,
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Gather all required user and device context for the uninstall report."""
    # 1. Resolve User & Session Details
    resolved_emp_id = employee_id
    resolved_username = username
    resolved_company = company_code

    if not (resolved_emp_id and resolved_username and resolved_company):
        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            saved = store.load_session()
            if saved:
                resolved_emp_id = resolved_emp_id or saved.get("employee_id")
                resolved_username = resolved_username or saved.get("username")
                resolved_company = resolved_company or saved.get("company_code")
            
            # Additional fallback to direct settings keys
            if not resolved_emp_id:
                resolved_emp_id = store.settings.value("session/employee_id") or store.settings.value("last_employee_id")
            if not resolved_username:
                resolved_username = store.settings.value("session/username") or store.settings.value("last_username")
            if not resolved_company:
                resolved_company = store.settings.value("session/company_code") or store.settings.value("last_company_code")
        except Exception:
            pass

    if not (resolved_emp_id and resolved_username and resolved_company):
        try:
            from services.session_service import SessionService
            cur = SessionService().current_user
            if cur:
                resolved_emp_id = resolved_emp_id or getattr(cur, "employee_id", None)
                resolved_username = resolved_username or getattr(cur, "username", None)
                resolved_company = resolved_company or getattr(cur, "company_code", None)
        except Exception:
            pass

    # 2. Resolve Device & Host Context
    dev_id = device_id or get_device_identifier()
    try:
        host = socket.gethostname()
    except Exception:
        host = os.environ.get("COMPUTERNAME", "Unknown")

    try:
        os_user = getpass.getuser()
    except Exception:
        os_user = os.environ.get("USERNAME", "Unknown")

    os_info = f"{platform.system()} {platform.release()} ({platform.version()})"
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now()

    return {
        "event_type": "APPLICATION_UNINSTALLED",
        "app_name": APP_NAME,
        "app_version": get_running_app_version(),
        "employee_id": str(resolved_emp_id or "N/A"),
        "username": str(resolved_username or os_user or "Unknown"),
        "company_code": str(resolved_company or "N/A"),
        "device_id": str(dev_id),
        "hostname": str(host),
        "os_user": str(os_user),
        "os": str(os_info),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "uninstall_time_local": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        "uninstall_time_utc": now_utc.isoformat(),
    }


def record_uninstall_event(context: Optional[Dict[str, Any]] = None) -> Path:
    """Record an uninstallation event to the persistent pending queue file."""
    ctx = context or collect_uninstall_context()
    target_path = get_pending_uninstall_path()
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(ctx, f, indent=2)
        logger.info("Recorded pending uninstall event at %s", target_path)
    except Exception as e:
        logger.warning("Could not write pending uninstall event: %s", e)
    return target_path


def is_uninstall_pending() -> bool:
    """Check if an uninstalled event is waiting to be reported."""
    return get_pending_uninstall_path().exists()


def dispatch_uninstall_report(context: Optional[Dict[str, Any]] = None) -> bool:
    """
    Attempt to dispatch the uninstall report immediately to Support via the backend.
    
    Returns True if successfully delivered, False if offline / unreachable.
    """
    ctx = context or collect_uninstall_context()
    error_msg = (
        f"iHRMS Monitor UNINSTALLED by user '{ctx.get('username')}' "
        f"(Employee ID: {ctx.get('employee_id')}, Company: {ctx.get('company_code')}) "
        f"on device '{ctx.get('hostname')}' ({ctx.get('device_id')}) running {ctx.get('os')}."
    )

    try:
        from services.error_report_service import ErrorReportService
        svc = ErrorReportService()
        report_ctx = svc._collect_context(
            error_type="APPLICATION_UNINSTALLED",
            error_message=error_msg,
            extra_context={
                "user_details": {
                    "employee_id": ctx.get("employee_id"),
                    "username": ctx.get("username"),
                    "company_code": ctx.get("company_code"),
                },
                "device_details": {
                    "device_id": ctx.get("device_id"),
                    "hostname": ctx.get("hostname"),
                    "os": ctx.get("os"),
                    "os_user": ctx.get("os_user"),
                    "installed_version": ctx.get("app_version"),
                    "uninstall_time_local": ctx.get("uninstall_time_local"),
                    "uninstall_time_utc": ctx.get("uninstall_time_utc"),
                },
                "operation": "Application Uninstallation",
            },
        )
        delivered = svc._dispatch_via_backend(report_ctx)
        if delivered:
            logger.info("Uninstall report successfully dispatched to backend.")
            return True
        else:
            logger.debug("Backend unreachable; uninstall report delivery deferred.")
            return False
    except Exception as err:
        logger.warning("Failed to dispatch uninstall report: %s", err)
        return False


def process_pending_uninstall_reports() -> bool:
    """
    Process any pending uninstall reports in the queue.
    
    If connectivity is restored, dispatches the email and cleans up the queue file.
    Returns True if an event was processed and cleared, False if none or still offline.
    """
    path = get_pending_uninstall_path()
    if not path.exists():
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            ctx = json.load(f)
    except Exception as err:
        logger.warning("Could not read pending uninstall file %s: %s", path, err)
        return False

    success = dispatch_uninstall_report(ctx)
    if success:
        try:
            path.unlink(missing_ok=True)
            logger.info("Pending uninstall report delivered and queue file removed.")
            cleanup_offline_delivery_task()
            return True
        except Exception as e:
            logger.debug("Could not remove pending uninstall file: %s", e)
            return True

    return False


def setup_offline_delivery_task() -> None:
    """
    Set up a lightweight Windows scheduled task to retry delivering the
    uninstall report when internet becomes available.
    """
    if sys.platform != "win32":
        return

    task_name = "iHRMS_Monitor_Uninstall_Notifier"
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "uninstall_notifier.ps1"

    if not script_path.exists():
        return

    try:
        import subprocess
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command",
            (
                f"$action = New-ScheduledTaskAction -Execute 'powershell.exe' "
                f"-Argument '-NoProfile -ExecutionPolicy Bypass -File \"{script_path}\"'; "
                f"$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
                f"-RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 7); "
                f"$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; "
                f"Register-ScheduledTask -TaskName '{task_name}' -Action $action -Trigger $trigger -Settings $settings -Force"
            ),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        logger.info("Scheduled task %s configured for offline uninstall delivery.", task_name)
    except Exception as e:
        logger.debug("Could not register scheduled task: %s", e)


def cleanup_offline_delivery_task() -> None:
    """Remove the scheduled task once the uninstall report has been delivered."""
    if sys.platform != "win32":
        return

    task_name = "iHRMS_Monitor_Uninstall_Notifier"
    try:
        import subprocess
        cmd = [
            "schtasks.exe",
            "/Delete",
            "/TN", task_name,
            "/F",
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        pass


def execute_uninstaller_routine() -> None:
    """
    Entry point executed during Inno Setup uninstallation.
    
    1. Collects context.
    2. Writes pending_uninstall.json.
    3. Attempts immediate online delivery.
    4. If offline, schedules background retry task.
    """
    ctx = collect_uninstall_context()
    record_uninstall_event(ctx)
    delivered = dispatch_uninstall_report(ctx)
    if delivered:
        # Delivered immediately
        get_pending_uninstall_path().unlink(missing_ok=True)
    else:
        # Schedule background retry
        setup_offline_delivery_task()


if __name__ == "__main__":
    if "--process-pending" in sys.argv:
        process_pending_uninstall_reports()
    else:
        execute_uninstaller_routine()
