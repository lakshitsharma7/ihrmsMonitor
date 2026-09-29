"""SMTP-based Error & Support Reporting Service for Workpulse.

Collects and securely dispatches error reports and notifications to the configured
support email via direct SMTP.

SMTP Delivery Architecture:
---------------------------
1. **Direct SMTP Delivery** (primary)
   The report context is formatted into a standard RFC 2822 MIME email message
   with structured diagnostic metadata and sanitized log tails.
   The message is securely transmitted over TLS/STARTTLS to the configured SMTP
   server (smtp.gmail.com:587).

2. **Local Log File Fallback** (offline resilience)
   If the SMTP server is unreachable (offline, network timeout, authentication error),
   the full diagnostic report is preserved locally in ``error_reports.log`` in the
   application data directory.

Features:
1. Gathers logged-in user details, device/hostname, app version, error info,
   timestamp, and recent sanitized application logs.
2. Sanitizes sensitive data (passwords, tokens, API keys) before reporting.
3. Implements deduplication and cooldown (1-hour window) to prevent duplicate reports.
4. Asynchronous delivery on a background daemon thread (ErrorReportWorker) so it
   NEVER blocks or impacts UI responsiveness, tracking, sync, or updates.
5. Fails gracefully without interrupting the core application.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import re
import smtplib
import socket
import ssl
import sys
import threading
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any

from config.settings import APP_NAME, APP_VERSION, get_running_app_version
from utils.logger import get_logger
from utils.paths import get_log_file_path

logger = get_logger(__name__)

# ==============================================================
# AUTHORITATIVE SMTP CONFIGURATION
# ==============================================================

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_USER = "ivsdevmail@gmail.com"
DEFAULT_SMTP_PASS = "cfecsqtvdprmofys"
DEFAULT_SMTP_TLS = True
DEFAULT_SMTP_FROM = "ivsdevmail@gmail.com"
DEFAULT_SUPPORT_EMAIL = "support-hrms@indovisionservices.in"
DEFAULT_SMTP_TIMEOUT_SECONDS = 12

# Redaction patterns for sensitive information
SENSITIVE_PATTERNS = [
    (re.compile(r'(?i)(password|pass|passwd|pwd)["\']?\s*[:=]\s*["\']?([^"\'\s&,]+)', re.IGNORECASE), r'\1: [REDACTED]'),
    (re.compile(r'(?i)(key|api_key|apikey|token|device_token|bearer)["\']?\s*[:=]\s*["\']?([^"\'\s&,]+)', re.IGNORECASE), r'\1: [REDACTED]'),
    (re.compile(r'(?i)(authorization:\s*bearer\s+)([a-zA-Z0-9_\-\.]+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(?i)(https?://[^:\s]+:)([^@\s]+)(@)', re.IGNORECASE), r'\1[REDACTED]\3'),
]


def sanitize_text(text: str) -> str:
    """Mask credentials, passwords, and tokens from error messages and logs."""
    if not text:
        return ""
    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        try:
            sanitized = pattern.sub(replacement, sanitized)
        except Exception:
            pass
    return sanitized


class ErrorReportService:
    """Centralized Error & Support Reporting Service using direct secure SMTP."""

    _instance: ErrorReportService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ErrorReportService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_service()
            return cls._instance

    def _init_service(self) -> None:
        """Initialize SMTP configuration, listener list, and deduplication caches."""
        self._smtp_host = os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST).strip()
        port_val = os.environ.get("SMTP_PORT", str(DEFAULT_SMTP_PORT)).strip()
        self._smtp_port = int(port_val) if port_val.isdigit() else DEFAULT_SMTP_PORT
        self._smtp_user = os.environ.get("SMTP_USERNAME", os.environ.get("SMTP_USER", DEFAULT_SMTP_USER)).strip()
        self._smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", DEFAULT_SMTP_PASS)).strip()
        tls_env = os.environ.get("SMTP_USE_TLS", os.environ.get("SMTP_TLS", "true")).strip().lower()
        self._smtp_use_tls = tls_env in ("true", "1", "yes")
        self._smtp_from = os.environ.get("SMTP_FROM", DEFAULT_SMTP_FROM).strip() or self._smtp_user
        self._support_email = os.environ.get("SUPPORT_EMAIL", DEFAULT_SUPPORT_EMAIL).strip()

        # UI listeners registered for immediate dashboard status updates
        self._listeners: list[Any] = []

        # Cooldown cache: maps hash(signature) -> last_sent_timestamp
        self._sent_reports: dict[str, float] = {}
        self._cooldown_seconds = 3600.0  # 1 hour cooldown per unique error signature

    def register_listener(self, callback: Any) -> None:
        """Register a callback listener to receive error notifications immediately."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unregister_listener(self, callback: Any) -> None:
        """Unregister an error notification listener."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    # ==============================================================
    # DEDUPLICATION
    # ==============================================================

    def _get_error_signature(self, error_type: str, error_message: str) -> str:
        """Compute a normalized fingerprint hash for the error to prevent duplicate reports."""
        clean_msg = re.sub(r"\d+", "N", error_message.strip().lower())
        raw_key = f"{error_type.strip().upper()}::{clean_msg}"
        return hashlib.sha256(raw_key.encode("utf-8", errors="ignore")).hexdigest()

    def _is_duplicate(self, signature: str) -> bool:
        """Return True if this error was already reported recently."""
        now = time.time()
        last_sent = self._sent_reports.get(signature)
        if last_sent is not None and (now - last_sent) < self._cooldown_seconds:
            return True
        return False

    def _record_sent(self, signature: str) -> None:
        """Record the timestamp an error report was dispatched."""
        self._sent_reports[signature] = time.time()
        # Prune old cache entries
        now = time.time()
        self._sent_reports = {
            sig: ts for sig, ts in self._sent_reports.items()
            if (now - ts) < (self._cooldown_seconds * 2)
        }

    # ==============================================================
    # CONTEXT COLLECTION
    # ==============================================================

    def _collect_context(
        self,
        error_type: str,
        error_message: str,
        exc: Exception | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Collect all relevant diagnostic information dynamically."""
        # 1. User / Employee details
        user_details = {
            "full_name": "Not Available",
            "employee_code": "Not Available",
            "employee_id": "Not Available",
            "username": "Not Available",
            "company_code": "Not Available",
            "role": "Not Available",
        }
        try:
            from services.session_service import SessionService
            session = SessionService().current_user
            if session:
                user_details["full_name"] = getattr(session, "full_name", None) or "Not Available"
                emp_code = getattr(session, "employee_code", None) or getattr(session, "employee_id", None) or "Not Available"
                user_details["employee_code"] = emp_code
                user_details["employee_id"] = getattr(session, "employee_id", None) or emp_code
                user_details["username"] = getattr(session, "username", None) or "Not Available"
                user_details["company_code"] = getattr(session, "company_code", None) or "Not Available"
                user_details["role"] = getattr(session, "role", None) or "Not Available"
            else:
                from services.secure_session import SessionStore
                saved = SessionStore().load_session()
                if saved and isinstance(saved, dict):
                    user_details["full_name"] = saved.get("full_name") or saved.get("name") or "Not Available"
                    emp_code = saved.get("employee_code") or saved.get("employee_id") or "Not Available"
                    user_details["employee_code"] = emp_code
                    user_details["employee_id"] = saved.get("employee_id") or emp_code
                    user_details["username"] = saved.get("username") or saved.get("email") or "Not Available"
                    user_details["company_code"] = saved.get("company_code") or "Not Available"
                    user_details["role"] = saved.get("user_type") or saved.get("role") or "Not Available"
        except Exception:
            pass

        # 2. Host and Device details
        hostname = "Unknown"
        try:
            hostname = socket.gethostname()
        except Exception:
            pass

        os_username = "Unknown"
        try:
            os_username = getpass.getuser()
        except Exception:
            pass

        device_details = {
            "hostname": hostname,
            "os_user": os_username,
            "platform": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": sys.version.split()[0],
        }

        # 3. Dynamic System Health
        system_health = {}
        try:
            from utils.system_health import get_system_health
            system_health = get_system_health()
        except Exception:
            pass

        # 4. Stack trace
        traceback_str = ""
        if exc is not None:
            import traceback
            traceback_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        # 5. Extract explicit API & HTTP diagnostics if provided
        endpoint = "N/A"
        http_status = "N/A"
        response_error = "N/A"
        operation = "N/A"
        if extra_context:
            if extra_context.get("endpoint"):
                endpoint = str(extra_context["endpoint"])
            elif extra_context.get("api_url"):
                endpoint = str(extra_context["api_url"])

            if extra_context.get("http_status") is not None:
                http_status = str(extra_context["http_status"])
            elif extra_context.get("status_code") is not None:
                http_status = str(extra_context["status_code"])

            if extra_context.get("response_error") is not None:
                response_error = str(extra_context["response_error"])
            elif extra_context.get("server_response") is not None:
                response_error = str(extra_context["server_response"])

            if extra_context.get("operation"):
                operation = str(extra_context["operation"])

        # 6. Extract module and function where error originated
        calling_module = "N/A"
        calling_function = "N/A"
        try:
            if extra_context and extra_context.get("module"):
                calling_module = str(extra_context["module"])
            if extra_context and extra_context.get("function"):
                calling_function = str(extra_context["function"])

            if calling_module == "N/A" or calling_function == "N/A":
                import inspect
                stack = inspect.stack()
                for frame_info in stack[1:]:
                    fn = frame_info.filename
                    if "error_report_service" not in fn:
                        calling_module = Path(fn).name
                        calling_function = frame_info.function
                        break
        except Exception:
            pass

        # 7. Current application status (tracking, sync, update)
        tracking_status = "Unknown"
        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            if store.is_tracking_manually_stopped():
                tracking_status = "Manually Stopped"
            elif store.is_tracking_active():
                tracking_status = "Active"
            else:
                tracking_status = "Inactive"
        except Exception:
            pass

        sync_status = "Unknown"
        try:
            from services.sync_service import SyncService
            sync_status = f"{SyncService.last_sync_status} (Last success: {SyncService.last_successful_sync_time})"
        except Exception:
            pass

        update_status = "Unknown"
        try:
            from services.device_registry_service import DeviceRegistryService
            from utils.device import get_device_identifier
            for d in DeviceRegistryService().get_all_devices():
                if d.get("device_identifier") == get_device_identifier():
                    update_status = d.get("update_status", "Updated")
                    break
        except Exception:
            pass

        # 8. Recent application log lines
        recent_logs = self._get_recent_logs(max_lines=60)

        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            "app_name": APP_NAME,
            "app_version": get_running_app_version(),
            "error_type": error_type,
            "error_message": sanitize_text(error_message),
            "calling_module": sanitize_text(calling_module),
            "calling_function": sanitize_text(calling_function),
            "operation": sanitize_text(operation),
            "endpoint": sanitize_text(endpoint),
            "http_status": sanitize_text(http_status),
            "response_error": sanitize_text(response_error),
            "tracking_status": tracking_status,
            "sync_status": sync_status,
            "update_status": update_status,
            "traceback": sanitize_text(traceback_str),
            "timestamp_local": now_local,
            "timestamp_utc": now_utc,
            "user_details": user_details,
            "device_details": device_details,
            "system_health": system_health,
            "recent_logs": sanitize_text(recent_logs),
            "extra_context": sanitize_text(str(extra_context or {})),
        }

    def _get_recent_logs(self, max_lines: int = 60) -> str:
        """Extract the tail lines from the application log file."""
        try:
            log_path = get_log_file_path()
            if not log_path.exists():
                return "Log file does not exist yet."
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                tail = lines[-max_lines:] if len(lines) > max_lines else lines
                return "".join(tail)
        except Exception as err:
            return f"Failed to read application logs: {err}"

    # ==============================================================
    # REPORT FORMATTING
    # ==============================================================

    def _build_report_text(self, context: dict[str, Any]) -> str:
        """Construct a structured plain-text report body with real-time system health."""
        user = context.get("user_details", {})
        device = context.get("device_details", {})
        health = context.get("system_health", {})

        emp_name = user.get("full_name") or "Not Available"
        emp_code = user.get("employee_code") or user.get("employee_id") or "Not Available"
        hostname = device.get("hostname") or "Unknown"

        error_type = context.get("error_type", "ERROR_REPORT")
        error_message = context.get("error_message", "N/A")
        date_time_str = f"{context.get('timestamp_local', 'N/A')} (UTC: {context.get('timestamp_utc', 'N/A')})"
        
        module_str = context.get("calling_module", "N/A")
        if context.get("calling_function") and context.get("calling_function") != "N/A":
            module_str += f" ({context.get('calling_function')})"
        
        api_action = context.get("endpoint") or context.get("operation") or "N/A"
        if api_action == "N/A" and context.get("operation") and context.get("operation") != "N/A":
            api_action = context.get("operation")

        # Dynamic System Health Metrics collected at error time
        cpu_data = health.get("cpu", {})
        ram_data = health.get("ram", {})
        disk_data = health.get("disk", {})

        cpu_usage_str = f"{cpu_data.get('usage_percent', health.get('cpu_usage_percent', 'N/A'))}%" if ('usage_percent' in cpu_data or 'cpu_usage_percent' in health) else "N/A"
        cpu_cores_str = f"{cpu_data.get('cores', health.get('cpu_physical_cores', 'N/A'))} Physical, {cpu_data.get('logical_processors', health.get('cpu_logical_cores', 'N/A'))} Logical" if ('cores' in cpu_data or 'cpu_physical_cores' in health) else "N/A"

        ram_usage_str = f"{ram_data.get('usage_percent', health.get('ram_usage_percent', 'N/A'))}%" if ('usage_percent' in ram_data or 'ram_usage_percent' in health) else "N/A"
        ram_used_str = str(ram_data.get("used") or (f"{health.get('ram_used_mb')} MB" if health.get('ram_used_mb') else "N/A"))
        ram_avail_str = str(ram_data.get("available") or (f"{health.get('ram_available_mb')} MB" if health.get('ram_available_mb') else "N/A"))
        ram_total_str = str(ram_data.get("total") or (f"{health.get('ram_total_mb')} MB" if health.get('ram_total_mb') else "N/A"))
        
        disk_usage_str = f"{disk_data.get('usage_percent', health.get('disk_usage_percent', 'N/A'))}%" if ('usage_percent' in disk_data or 'disk_usage_percent' in health) else "N/A"
        disk_used_str = str(disk_data.get("used") or (f"{health.get('disk_used_gb')} GB" if health.get('disk_used_gb') else "N/A"))
        disk_free_str = str(disk_data.get("free") or (f"{health.get('disk_free_gb')} GB" if health.get('disk_free_gb') else "N/A"))
        disk_total_str = str(disk_data.get("total") or (f"{health.get('disk_total_gb')} GB" if health.get('disk_total_gb') else "N/A"))

        os_name = device.get("platform") or platform.system()
        os_version = device.get("os_version") or platform.version()
        architecture = device.get("architecture") or platform.machine()
        python_version = device.get("python_version") or sys.version.split()[0]
        app_name = context.get("app_name", APP_NAME)
        app_version = context.get("app_version", get_running_app_version())

        return (
            "==================================================\n"
            "WORKPULSE ERROR REPORT\n"
            f"{app_name} - Critical Error Report\n"
            "==================================================\n\n"
            f"Employee Name : {emp_name}\n"
            f"Employee Code : {emp_code}\n"
            f"Host Name     : {hostname}\n\n"
            "==================================================\n"
            "ERROR DETAILS\n"
            "==================================================\n\n"
            f"Error Type    : {error_type}\n"
            f"Error Message : {error_message}\n"
            f"Module        : {module_str}\n"
            f"API/Action    : {api_action}\n"
            f"HTTP Status   : {context.get('http_status', 'N/A')}\n"
            f"Response Err  : {context.get('response_error', 'N/A')}\n"
            f"Date & Time   : {date_time_str}\n\n"
            "==================================================\n"
            "CURRENT SYSTEM HEALTH AT ERROR TIME\n"
            "==================================================\n\n"
            f"CPU Usage        : {cpu_usage_str}\n"
            f"CPU Cores        : {cpu_cores_str}\n\n"
            f"RAM Usage        : {ram_usage_str}\n"
            f"RAM Used         : {ram_used_str}\n"
            f"RAM Available    : {ram_avail_str}\n"
            f"RAM Total        : {ram_total_str}\n\n"
            f"Disk Usage       : {disk_usage_str}\n"
            f"Disk Used        : {disk_used_str}\n"
            f"Disk Free        : {disk_free_str}\n"
            f"Disk Total       : {disk_total_str}\n\n"
            f"Operating System : {os_name}\n"
            f"OS Version       : {os_version}\n"
            f"Architecture     : {architecture}\n"
            f"Python Version   : {python_version}\n"
            f"Workpulse Version: {app_version}\n\n"
            "==================================================\n"
            "ADDITIONAL DIAGNOSTICS\n"
            "==================================================\n\n"
            f"Application   : {app_name} v{app_version}\n"
            f"Username      : {user.get('username', 'N/A')}\n"
            f"Company Code  : {user.get('company_code', 'N/A')}\n"
            f"Role          : {user.get('role', 'N/A')}\n"
            f"OS User       : {device.get('os_user', 'N/A')}\n"
            f"Tracking State: {context.get('tracking_status', 'Unknown')}\n"
            f"Sync State    : {context.get('sync_status', 'Unknown')}\n"
            f"Update State  : {context.get('update_status', 'Unknown')}\n\n"
            "--- Traceback ---\n"
            f"{context.get('traceback') or 'No traceback available.'}\n\n"
            "--- Extra Context ---\n"
            f"{context.get('extra_context')}\n\n"
            "--- Recent Application Logs (Tail) ---\n"
            f"{context.get('recent_logs')}\n\n"
            "==================================================\n"
            "End of Error Report\n"
            "==================================================\n"
        )

    def _build_report_html(self, context: dict[str, Any]) -> str:
        """Construct a clean, professional HTML error report body."""
        user = context.get("user_details", {})
        device = context.get("device_details", {})
        health = context.get("system_health", {})

        emp_name = user.get("full_name") or "Not Available"
        emp_code = user.get("employee_code") or user.get("employee_id") or "Not Available"
        hostname = device.get("hostname") or "Unknown"

        error_type = context.get("error_type", "ERROR_REPORT")
        error_message = context.get("error_message", "N/A")
        date_time_str = f"{context.get('timestamp_local', 'N/A')} (UTC: {context.get('timestamp_utc', 'N/A')})"
        now_local = context.get('timestamp_local', 'N/A')

        module_str = context.get("calling_module", "N/A")
        if context.get("calling_function") and context.get("calling_function") != "N/A":
            module_str += f" ({context.get('calling_function')})"

        api_action = context.get("endpoint") or context.get("operation") or "N/A"
        if api_action == "N/A" and context.get("operation") and context.get("operation") != "N/A":
            api_action = context.get("operation")

        cpu_data = health.get("cpu", {})
        ram_data = health.get("ram", {})
        disk_data = health.get("disk", {})

        cpu_usage_str = f"{cpu_data.get('usage_percent', health.get('cpu_usage_percent', 'N/A'))}%" if ('usage_percent' in cpu_data or 'cpu_usage_percent' in health) else "N/A"
        cpu_cores_str = f"{cpu_data.get('cores', health.get('cpu_physical_cores', 'N/A'))} Physical, {cpu_data.get('logical_processors', health.get('cpu_logical_cores', 'N/A'))} Logical" if ('cores' in cpu_data or 'cpu_physical_cores' in health) else "N/A"

        ram_usage_str = f"{ram_data.get('usage_percent', health.get('ram_usage_percent', 'N/A'))}%" if ('usage_percent' in ram_data or 'ram_usage_percent' in health) else "N/A"
        ram_used_str = str(ram_data.get("used") or (f"{health.get('ram_used_mb')} MB" if health.get('ram_used_mb') else "N/A"))
        ram_avail_str = str(ram_data.get("available") or (f"{health.get('ram_available_mb')} MB" if health.get('ram_available_mb') else "N/A"))
        ram_total_str = str(ram_data.get("total") or (f"{health.get('ram_total_mb')} MB" if health.get('ram_total_mb') else "N/A"))
        
        disk_usage_str = f"{disk_data.get('usage_percent', health.get('disk_usage_percent', 'N/A'))}%" if ('usage_percent' in disk_data or 'disk_usage_percent' in health) else "N/A"
        disk_used_str = str(disk_data.get("used") or (f"{health.get('disk_used_gb')} GB" if health.get('disk_used_gb') else "N/A"))
        disk_free_str = str(disk_data.get("free") or (f"{health.get('disk_free_gb')} GB" if health.get('disk_free_gb') else "N/A"))
        disk_total_str = str(disk_data.get("total") or (f"{health.get('disk_total_gb')} GB" if health.get('disk_total_gb') else "N/A"))

        os_name = device.get("platform") or platform.system()
        os_version = device.get("os_version") or platform.version()
        architecture = device.get("architecture") or platform.machine()
        python_version = device.get("python_version") or sys.version.split()[0]
        app_name = context.get("app_name", APP_NAME)
        app_version = context.get("app_version", get_running_app_version())

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f6f8; color: #202124; margin: 0; padding: 20px; }}
.container {{ max-width: 760px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #dadce0; overflow: hidden; box-shadow: 0 2px 6px rgba(0,0,0,0.06); }}
.header {{ background: #1F4E79; color: #ffffff; padding: 20px 24px; }}
.header h1 {{ margin: 0; font-size: 20px; letter-spacing: 0.5px; font-weight: 600; }}
.header p {{ margin: 4px 0 0 0; font-size: 13px; opacity: 0.85; }}
.section {{ padding: 18px 24px; border-bottom: 1px solid #eeeeee; }}
.section:last-child {{ border-bottom: none; }}
.section-title {{ font-size: 14px; font-weight: 700; color: #1F4E79; text-transform: uppercase; margin-bottom: 12px; letter-spacing: 0.5px; }}
.badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; background: #ea4335; color: #ffffff; }}
table.meta-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
table.meta-table td {{ padding: 6px 0; vertical-align: top; }}
table.meta-table td.label {{ width: 170px; color: #5f6368; font-weight: 600; }}
table.meta-table td.val {{ color: #202124; font-family: inherit; }}
pre.code-block {{ background: #282c34; color: #abb2bf; padding: 12px; border-radius: 6px; font-size: 12px; overflow-x: auto; font-family: 'Consolas', 'Courier New', monospace; line-height: 1.4; }}
.footer {{ background: #f8f9fa; padding: 12px 24px; font-size: 12px; color: #70757a; text-align: center; border-top: 1px solid #eeeeee; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>WORKPULSE ERROR REPORT</h1>
    <p>Application Diagnostics & Automated Support Dispatch</p>
  </div>
  
  <div class="section">
    <div class="section-title">Employee Information</div>
    <table class="meta-table">
      <tr><td class="label">Employee Name</td><td class="val"><strong>{emp_name}</strong></td></tr>
      <tr><td class="label">Employee Code</td><td class="val"><strong>{emp_code}</strong></td></tr>
      <tr><td class="label">Host Name</td><td class="val"><code>{hostname}</code></td></tr>
    </table>
  </div>

  <div class="section">
    <div class="section-title">Error Details</div>
    <table class="meta-table">
      <tr><td class="label">Error Type</td><td class="val"><span class="badge">{error_type}</span></td></tr>
      <tr><td class="label">Error Message</td><td class="val" style="color: #c5221f; font-weight: 600;">{error_message}</td></tr>
      <tr><td class="label">Module</td><td class="val">{module_str}</td></tr>
      <tr><td class="label">API / Action</td><td class="val"><code>{api_action}</code></td></tr>
      <tr><td class="label">HTTP Status</td><td class="val">{context.get('http_status', 'N/A')}</td></tr>
      <tr><td class="label">Response Error</td><td class="val">{context.get('response_error', 'N/A')}</td></tr>
      <tr><td class="label">Date & Time</td><td class="val">{date_time_str}</td></tr>
    </table>
  </div>

  <div class="section">
    <div class="section-title">Current System Health at Error Time</div>
    <table class="meta-table">
      <tr><td class="label">CPU Usage</td><td class="val">{cpu_usage_str}</td></tr>
      <tr><td class="label">CPU Cores</td><td class="val">{cpu_cores_str}</td></tr>
      <tr><td class="label">RAM Usage</td><td class="val">{ram_usage_str}</td></tr>
      <tr><td class="label">RAM Used</td><td class="val">{ram_used_str}</td></tr>
      <tr><td class="label">RAM Available</td><td class="val">{ram_avail_str}</td></tr>
      <tr><td class="label">RAM Total</td><td class="val">{ram_total_str}</td></tr>
      <tr><td class="label">Disk Usage</td><td class="val">{disk_usage_str}</td></tr>
      <tr><td class="label">Disk Used</td><td class="val">{disk_used_str}</td></tr>
      <tr><td class="label">Disk Free</td><td class="val">{disk_free_str}</td></tr>
      <tr><td class="label">Disk Total</td><td class="val">{disk_total_str}</td></tr>
      <tr><td class="label">Operating System</td><td class="val">{os_name}</td></tr>
      <tr><td class="label">OS Version</td><td class="val">{os_version}</td></tr>
      <tr><td class="label">Architecture</td><td class="val">{architecture}</td></tr>
      <tr><td class="label">Python Version</td><td class="val">{python_version}</td></tr>
      <tr><td class="label">Workpulse Version</td><td class="val"><strong>v{app_version}</strong></td></tr>
    </table>
  </div>

  <div class="section">
    <div class="section-title">Additional Diagnostics</div>
    <table class="meta-table">
      <tr><td class="label">Application</td><td class="val">{app_name} v{app_version}</td></tr>
      <tr><td class="label">Username</td><td class="val">{user.get('username', 'N/A')}</td></tr>
      <tr><td class="label">Company Code</td><td class="val">{user.get('company_code', 'N/A')}</td></tr>
      <tr><td class="label">Role</td><td class="val">{user.get('role', 'N/A')}</td></tr>
      <tr><td class="label">OS User</td><td class="val">{device.get('os_user', 'N/A')}</td></tr>
      <tr><td class="label">Tracking State</td><td class="val">{context.get('tracking_status', 'Unknown')}</td></tr>
      <tr><td class="label">Sync State</td><td class="val">{context.get('sync_status', 'Unknown')}</td></tr>
      <tr><td class="label">Update State</td><td class="val">{context.get('update_status', 'Unknown')}</td></tr>
    </table>
    
    <div style="margin-top: 14px; font-weight: 600; font-size: 13px; color: #5f6368;">Traceback:</div>
    <pre class="code-block">{context.get('traceback') or 'No traceback available.'}</pre>

    <div style="margin-top: 14px; font-weight: 600; font-size: 13px; color: #5f6368;">Recent Application Logs:</div>
    <pre class="code-block">{context.get('recent_logs')}</pre>
  </div>

  <div class="footer">
    Workpulse v{app_version} &bull; Confidential Support Diagnostic Report &bull; {now_local}
  </div>
</div>
</body>
</html>"""

    # ==============================================================
    # DELIVERY — DIRECT SECURE SMTP DISPATCH
    # ==============================================================

    def _dispatch_via_smtp(self, context: dict[str, Any]) -> bool:
        """
        Transmit the formatted error/support report to the support email address via direct SMTP.

        Returns True on successful delivery, False on connection, auth, or network failure.
        """
        host = os.environ.get("SMTP_HOST", self._smtp_host).strip()
        port_val = os.environ.get("SMTP_PORT", str(self._smtp_port)).strip()
        port = int(port_val) if port_val.isdigit() else DEFAULT_SMTP_PORT
        username = os.environ.get("SMTP_USERNAME", os.environ.get("SMTP_USER", self._smtp_user)).strip()
        password = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", self._smtp_pass)).strip()
        tls_val = os.environ.get("SMTP_USE_TLS", os.environ.get("SMTP_TLS", str(self._smtp_use_tls))).strip().lower()
        use_tls = tls_val in ("true", "1", "yes")
        from_addr = os.environ.get("SMTP_FROM", self._smtp_from).strip() or username
        to_addr = os.environ.get("SUPPORT_EMAIL", self._support_email).strip()

        if not host or not to_addr:
            logger.warning("SMTP configuration error: host or recipient not specified.")
            return False

        app_name = context.get("app_name", APP_NAME)
        app_version = context.get("app_version", get_running_app_version())
        error_type = context.get("error_type", "ERROR_REPORT")

        # Construct email subject
        if context.get("subject"):
            subject = str(context["subject"]).strip()
        else:
            msg_first_line = str(context.get("error_message") or "").strip().split("\n")[0]
            if msg_first_line:
                subject = f"[{app_name}] {error_type}: {msg_first_line[:65]}"
            else:
                subject = f"[{app_name} v{app_version}] {error_type}"

        # Construct RFC 2822 MIME message (multipart/alternative with both plain-text and HTML)
        body_text = context.get("body_text") or self._build_report_text(context)
        body_html = self._build_report_html(context)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Date"] = formatdate(localtime=True)
        domain_part = host if "." in host else "workpulse.local"
        msg["Message-ID"] = make_msgid(domain=domain_part)
        msg["X-Priority"] = "2" if any(k in error_type.upper() for k in ("CRASH", "CRITICAL", "UNINSTALLED")) else "3"
        msg["X-Mailer"] = f"{app_name}/{app_version}"

        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        masked_user = f"{username[:3]}***@{username.split('@')[-1]}" if "@" in username else "***"
        logger.info(
            "SMTP email send started: host=%s, port=%d, TLS=%s, user=%s, recipient=%s, subject=%s",
            host, port, use_tls, masked_user, to_addr, subject
        )

        try:
            ssl_ctx = ssl.create_default_context()
            if port == 465 and not use_tls:
                with smtplib.SMTP_SSL(host, port, timeout=DEFAULT_SMTP_TIMEOUT_SECONDS, context=ssl_ctx) as server:
                    if username and password:
                        server.login(username, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=DEFAULT_SMTP_TIMEOUT_SECONDS) as server:
                    server.ehlo()
                    if use_tls:
                        server.starttls(context=ssl_ctx)
                        server.ehlo()
                    if username and password:
                        server.login(username, password)
                    server.send_message(msg)

            logger.info("SMTP email sent successfully to %s: %s", to_addr, subject)
            return True

        except smtplib.SMTPAuthenticationError as auth_err:
            logger.warning(
                "SMTP authentication failed for user %s: %s",
                masked_user,
                auth_err.smtp_error if hasattr(auth_err, "smtp_error") else auth_err,
            )
        except smtplib.SMTPConnectError as conn_err:
            logger.warning("SMTP connection failed to %s:%d: %s", host, port, conn_err)
        except (socket.timeout, TimeoutError):
            logger.warning("SMTP connection timed out connecting to %s:%d", host, port)
        except Exception as smtp_err:
            logger.warning("SMTP send failed to %s:%d: %s", host, port, smtp_err)

        return False

    def _dispatch_to_local_log(self, context: dict[str, Any]) -> None:
        """
        Append the full error report to a local ``error_reports.log`` file.

        This is the last-resort fallback when SMTP delivery fails or the network is offline.
        """
        try:
            log_dir = get_log_file_path().parent
            report_log = log_dir / "error_reports.log"
            report_text = self._build_report_text(context)
            with open(report_log, "a", encoding="utf-8") as f:
                f.write(report_text)
                f.write("\n")
            logger.info(
                "ErrorReportService: error report written to local file: %s",
                report_log,
            )
        except Exception as file_err:
            logger.warning(
                "ErrorReportService: could not write error report to local log: %s",
                file_err,
            )

    def _dispatch_report(self, context: dict[str, Any]) -> None:
        """
        Deliver the error report via SMTP with automatic local-file fallback.

        Delivery order:
          1. Direct SMTP transmission to ``SUPPORT_EMAIL``.
          2. If SMTP delivery fails (offline, auth error, timeout), append to local ``error_reports.log``.
        """
        delivered = self._dispatch_via_smtp(context)
        if not delivered:
            logger.info(
                "ErrorReportService: SMTP delivery unavailable; "
                "falling back to local log file."
            )
            self._dispatch_to_local_log(context)

    # --------------------------------------------------------------
    # Backward Compatibility Aliases
    # --------------------------------------------------------------

    def _build_email_body(self, context: dict[str, Any]) -> str:
        """Alias for _build_report_text to maintain interface compatibility."""
        return self._build_report_text(context)

    def _dispatch_email(self, context: dict[str, Any]) -> bool:
        """Alias for dispatching report via SMTP."""
        return self._dispatch_via_smtp(context)

    def _dispatch_via_backend(self, context: dict[str, Any]) -> bool:
        """Compatibility alias routing legacy backend dispatch calls to SMTP."""
        return self._dispatch_via_smtp(context)

    # ==============================================================
    # PUBLIC API
    # ==============================================================

    def report_error(
        self,
        error_type: str,
        error_message: str,
        exc: Exception | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> None:
        """
        Record and dispatch an error report to the support email address via SMTP.

        Runs asynchronously on a background daemon thread so it NEVER blocks caller
        execution, UI rendering, tracking, or network sync.
        Deduplicates identical errors within a 1-hour window.
        """
        try:
            # Collect context synchronously to capture state at time of error
            context = self._collect_context(
                error_type=error_type,
                error_message=error_message,
                exc=exc,
                extra_context=extra_context,
            )

            # Immediately notify registered UI listeners (e.g. Dashboard)
            with self._lock:
                listeners = list(self._listeners)
            for listener in listeners:
                try:
                    listener(error_type, error_message, context)
                except Exception as listener_err:
                    logger.debug(
                        "Error notification listener failed: %s", listener_err
                    )

            sig = self._get_error_signature(error_type, error_message)
            if self._is_duplicate(sig):
                logger.debug(
                    "Suppressing duplicate error report for signature: %s (%s)",
                    sig, error_type,
                )
                return

            self._record_sent(sig)

            # Dispatch asynchronously — never block the calling thread
            def _async_send() -> None:
                try:
                    self._dispatch_report(context)
                except Exception as async_err:
                    logger.debug(
                        "Async error report dispatch failed: %s", async_err
                    )

            t = threading.Thread(
                target=_async_send, name="ErrorReportWorker", daemon=True
            )
            t.start()

        except Exception as err:
            logger.warning(
                "ErrorReportService.report_error encountered an internal issue: %s",
                err,
            )
