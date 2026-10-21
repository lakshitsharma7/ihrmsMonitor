"""SMTP-based Error & Support Reporting Service for Workpulse.

Collects and securely dispatches error reports and notifications to the configured
support email via direct SMTP.

SMTP Delivery Architecture:
---------------------------
1. **Direct SMTP Delivery** (primary when online)
   The report context is formatted into a standard RFC 2822 MIME email message
   with structured diagnostic metadata, system health metrics, and sanitized log tails.
   The message is securely transmitted over TLS/STARTTLS to the configured SMTP
   server (smtp.gmail.com:587).

2. **Persistent Offline Queue** (offline resilience)
   If the network is offline, the report is saved locally in ``queued_reports.json``
   without attempting immediate SMTP or throwing error popups.
   As soon as network connectivity is restored, the queued reports are automatically
   processed and sent to the support email.

3. **Local Log File Fallback** (secondary fallback)
   If SMTP transmission fails, reports are appended locally to ``error_reports.log``.

Features:
1. Gathers logged-in user details, device/hostname, app version, error info,
   network status, sync status, timestamps, system health (CPU, RAM, Disk),
   and recent sanitized application logs.
2. Sanitizes sensitive data (passwords, tokens, API keys, credentials) before reporting.
3. Implements deduplication and cooldown to prevent duplicate report spam.
4. Asynchronous delivery on background daemon threads so it NEVER blocks UI responsiveness,
   workpulse tracking, sync, or updates.
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

import requests

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

# Redaction patterns for sensitive information (passwords, tokens, API keys, credentials)
SENSITIVE_PATTERNS = [
    (re.compile(r'(?i)(password|pass|passwd|pwd)["\']?\s*[:=]\s*["\']?([^"\'\s&,]+)', re.IGNORECASE), r'\1: [REDACTED]'),
    (re.compile(r'(?i)(key|api_key|apikey|token|device_token|bearer)["\']?\s*[:=]\s*["\']?([^"\'\s&,]+)', re.IGNORECASE), r'\1: [REDACTED]'),
    (re.compile(r'(?i)(authorization:\s*bearer\s+)([a-zA-Z0-9_\-\.]+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(?i)(https?://[^:\s]+:)([^@\s]+)(@)', re.IGNORECASE), r'\1[REDACTED]\3'),
    (re.compile(r'(?i)(cookie|session_id|sessionid|auth_token)["\']?\s*[:=]\s*["\']?([^"\'\s&,]+)', re.IGNORECASE), r'\1: [REDACTED]'),
]


def sanitize_text(text: str) -> str:
    """Mask credentials, passwords, cookies, headers, and tokens from error messages and logs."""
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
    """Centralized Error & Support Reporting Service using direct secure SMTP and offline queue."""

    _instance: ErrorReportService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ErrorReportService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_service()
            return cls._instance

    def _init_service(self) -> None:
        """Initialize SMTP configuration, listener list, queue lock, and deduplication caches."""
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

        # In-memory recent error audit records
        self._reported_errors: list[Any] = []

        # Cooldown cache: maps hash(signature) -> last_sent_timestamp
        self._sent_reports: dict[str, float] = {}
        self._cooldown_seconds = 3600.0  # 1 hour cooldown per unique error signature

        # Offline persistent queue lock
        self._queue_lock = threading.Lock()

        # Last dispatch audit results for test and verification monitoring
        self._last_api_request: dict[str, Any] | None = None
        self._last_api_response: dict[str, Any] | None = None
        self._last_smtp_result: bool | None = None

        # Connect to centralized NetworkReachabilityMonitor for automatic queued report flushing
        try:
            from services.network_monitor import NetworkReachabilityMonitor
            monitor = NetworkReachabilityMonitor()
            monitor.register_listener(self._on_connectivity_changed)
            if monitor.is_online:
                # If already online at startup, attempt background flush of any previously queued reports
                threading.Thread(
                    target=self.flush_queued_reports,
                    name="StartupQueuedReportFlusher",
                    daemon=True,
                ).start()
        except Exception:
            pass

    @classmethod
    def is_production_build(cls) -> bool:
        """
        Dynamically determine if the application is running in a production packaged build.

        Returns:
            True: If running as a frozen executable (e.g. PyInstaller packaged Windows EXE)
                  or if explicitly configured for production via WORKPULSE_ENV/APP_ENV='production'.
            False: If running directly in a local Python development environment.
        """
        env_override = (os.environ.get("WORKPULSE_ENV") or os.environ.get("APP_ENV") or "").strip().lower()
        if env_override:
            return env_override in ("prod", "production")
        return bool(getattr(sys, "frozen", False))

    def should_send_email(self, context: dict[str, Any] | None = None) -> bool:
        """
        Determine if support emails should be dispatched via direct SMTP.

        Support emails are sent ONLY in production / packaged builds.
        In local Python development runs, support emails are suppressed to prevent
        accidentally polluting the production support mailbox.
        Can be explicitly enabled for intentional testing by setting context['_force_email']=True
        or the WORKPULSE_FORCE_EMAIL=1 environment variable.
        """
        if context and context.get("_force_email") is True:
            return True
        if os.environ.get("WORKPULSE_FORCE_EMAIL", "").strip().lower() in ("1", "true", "yes"):
            return True
        return self.is_production_build()

    def should_send_api(self, context: dict[str, Any] | None = None) -> bool:
        """
        Determine if error reports should be dispatched to the Workpulse report_error API.

        In production / packaged builds, real errors are dispatched to the API.
        In local Python development runs, normal errors do NOT trigger the production API
        to prevent accidental error pollution during development.
        Intentional test triggers (context['_force_api']=True or context['_is_test']=True)
        or explicit configuration (WORKPULSE_ENABLE_DEV_API=1, custom IHRMS_REPORT_ERROR_API_URL)
        allow API dispatch during development.
        """
        if context and (context.get("_force_api") is True or context.get("_is_test") is True):
            return True
        if os.environ.get("WORKPULSE_ENABLE_DEV_API", "").strip().lower() in ("1", "true", "yes"):
            return True
        if os.environ.get("IHRMS_REPORT_ERROR_API_URL"):
            return True
        return self.is_production_build()

    def _on_connectivity_changed(self, is_online: bool) -> None:
        """When network connectivity returns, automatically flush any offline queued reports."""
        if is_online:
            try:
                threading.Thread(
                    target=self.flush_queued_reports,
                    name="QueuedReportFlusher",
                    daemon=True,
                ).start()
            except Exception:
                pass

    # ==============================================================
    # OFFLINE PERSISTENT QUEUE
    # ==============================================================

    def _get_queue_file_path(self) -> Path:
        """Return the path to the persistent offline queued reports file."""
        if getattr(self, "_custom_queue_file", None):
            return Path(self._custom_queue_file)
        log_dir = get_log_file_path().parent
        return log_dir / "queued_reports.json"

    def _load_queued_reports(self) -> list[dict[str, Any]]:
        """Load queued reports from local disk."""
        queue_path = self._get_queue_file_path()
        if not queue_path.exists():
            return []
        try:
            with open(queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as err:
            logger.debug("ErrorReportService: Failed to read queued reports: %s", err)
        return []

    def _save_queued_reports(self, reports: list[dict[str, Any]]) -> None:
        """Save queued reports to local disk atomically."""
        queue_path = self._get_queue_file_path()
        try:
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            with open(queue_path, "w", encoding="utf-8") as f:
                json.dump(reports, f, indent=2)
        except Exception as err:
            logger.warning("ErrorReportService: Failed to save queued reports: %s", err)

    def _queue_report(self, context: dict[str, Any]) -> None:
        """Add an error report to the local persistent queue (preventing duplicate items)."""
        with self._queue_lock:
            reports = self._load_queued_reports()
            sig = self._get_error_signature(
                context.get("error_type", "ERROR_REPORT"),
                context.get("error_message", "N/A"),
            )
            for r in reports:
                if r.get("_signature") == sig:
                    logger.debug("ErrorReportService: Report already queued; skipping duplicate: %s", sig)
                    return

            context["_signature"] = sig
            context["_queued_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            reports.append(context)
            self._save_queued_reports(reports)
            logger.info("ErrorReportService: Queued support report locally in %s (offline mode): %s", self._get_queue_file_path(), context.get("error_type"))

    def flush_queued_reports(self) -> int:
        """
        Process and transmit any locally queued reports when internet connection is restored.
        Retries both Error Reporting API and SMTP support email independently based on their delivery flags.
        Returns the number of completely sent reports.
        """
        try:
            from services.network_monitor import NetworkReachabilityMonitor
            if not NetworkReachabilityMonitor().is_online:
                logger.debug("flush_queued_reports skipped: Network is currently offline.")
                return 0
        except Exception:
            pass

        with self._queue_lock:
            reports = self._load_queued_reports()
            if not reports:
                return 0

            logger.info("ErrorReportService: Flushing %d queued offline support reports...", len(reports))
            remaining: list[dict[str, Any]] = []
            sent_count = 0

            for report in reports:
                send_api = self.should_send_api(report)
                send_email = self.should_send_email(report)

                # 1. Flush API if not yet sent and permitted in current environment
                if not report.get("_api_sent", False):
                    if send_api:
                        try:
                            report["_api_sent"] = self._dispatch_via_api(report)
                        except Exception as api_err:
                            logger.debug("ErrorReportService: Failed to dispatch queued API report: %s", api_err)
                            report["_api_sent"] = False
                    else:
                        report["_api_sent"] = True

                # 2. Flush SMTP if not yet sent and permitted in current environment
                if not report.get("_smtp_sent", False):
                    if send_email:
                        try:
                            report["_smtp_sent"] = self._dispatch_via_smtp(report)
                        except Exception as smtp_err:
                            logger.debug("ErrorReportService: Failed to dispatch queued SMTP report: %s", smtp_err)
                            report["_smtp_sent"] = False
                    else:
                        report["_smtp_sent"] = True

                # If both delivered or resolved, count as success and do not keep in queue
                if report.get("_api_sent", False) and report.get("_smtp_sent", False):
                    sent_count += 1
                else:
                    remaining.append(report)

            self._save_queued_reports(remaining)
            if sent_count > 0:
                logger.info("ErrorReportService: Successfully transmitted %d queued support reports.", sent_count)
            return sent_count

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
        now = time.time()
        self._sent_reports = {
            sig: ts for sig, ts in self._sent_reports.items()
            if (now - ts) < (self._cooldown_seconds * 2)
        }

    def clear_error_history(self) -> None:
        """Clear sent report cooldown history and audit state (useful for tests and resets)."""
        with self._lock:
            self._sent_reports.clear()
            self._reported_errors.clear()
            self._last_api_request = None
            self._last_api_response = None
            self._last_smtp_result = None

    def get_recent_errors(self, limit: int = 10) -> list[Any]:
        """Return recent in-memory error reports for diagnostic monitoring."""
        with self._lock:
            return list(self._reported_errors[-limit:])


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

        # 4. Dynamic Exception & Caller Stack Trace Details
        if exc is None:
            try:
                _, active_exc, _ = sys.exc_info()
                if active_exc is not None:
                    exc = active_exc
            except Exception:
                pass

        exception_type = "N/A"
        err_file = "N/A"
        err_file_path = "N/A"
        err_line = None
        err_function = "N/A"
        err_module = "N/A"
        traceback_str = ""

        if exc is not None:
            exception_type = type(exc).__name__
            import traceback
            traceback_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

            # Extract deepest / origin frame where exception was raised
            tb = exc.__traceback__
            deepest_tb = tb
            while tb:
                deepest_tb = tb
                tb = tb.tb_next
            if deepest_tb:
                frame = deepest_tb.tb_frame
                err_line = deepest_tb.tb_lineno
                err_file_path = str(Path(frame.f_code.co_filename).resolve())
                err_file = Path(err_file_path).name
                err_function = frame.f_code.co_name
                err_module = frame.f_globals.get("__name__") or Path(err_file_path).stem
        else:
            # Dynamically inspect caller stack outside ErrorReportService
            try:
                import inspect
                stack = inspect.stack()
                for frame_info in stack[1:]:
                    fn = frame_info.filename
                    if "error_report_service" not in fn:
                        err_file_path = str(Path(fn).resolve())
                        err_file = Path(err_file_path).name
                        err_line = frame_info.lineno
                        err_function = frame_info.function
                        err_module = frame_info.frame.f_globals.get("__name__") or Path(err_file_path).stem
                        break
            except Exception:
                pass

        # Allow extra_context to supplement or override any explicit items
        if extra_context:
            if extra_context.get("exception_type"):
                exception_type = str(extra_context["exception_type"])
            elif extra_context.get("exception"):
                exception_type = str(extra_context["exception"])

            if extra_context.get("file_path"):
                err_file_path = str(extra_context["file_path"])
            if extra_context.get("file"):
                err_file = str(extra_context["file"])
            if extra_context.get("line") is not None:
                try:
                    err_line = int(extra_context["line"])
                except (ValueError, TypeError):
                    pass
            if extra_context.get("function"):
                err_function = str(extra_context["function"])
            if extra_context.get("module"):
                err_module = str(extra_context["module"])
            if extra_context.get("traceback"):
                traceback_str = str(extra_context["traceback"])

        if exception_type == "N/A" or not exception_type:
            exception_type = error_type

        if not traceback_str:
            try:
                import traceback
                traceback_str = "".join(traceback.format_stack()[:-1])
            except Exception:
                traceback_str = "No traceback available."

        # 5. Extract HTTP diagnostics, retry count, file size, operation, and endpoint
        http_status_val = None
        if extra_context:
            for k in ("http_status", "status_code", "status"):
                if extra_context.get(k) is not None:
                    try:
                        http_status_val = int(extra_context[k])
                        break
                    except (ValueError, TypeError):
                        http_status_val = extra_context[k]
                        break
        if http_status_val is None and exc is not None:
            resp = getattr(exc, "response", None)
            if resp is not None and getattr(resp, "status_code", None) is not None:
                http_status_val = resp.status_code
            elif getattr(exc, "status_code", None) is not None:
                http_status_val = exc.status_code

        retry_val = None
        if extra_context:
            for k in ("retry", "retry_count", "attempt", "retries"):
                if extra_context.get(k) is not None:
                    try:
                        retry_val = int(extra_context[k])
                        break
                    except (ValueError, TypeError):
                        retry_val = extra_context[k]
                        break

        file_size_val = None
        if extra_context:
            for k in ("file_size", "size", "bytes", "filesize"):
                if extra_context.get(k) is not None:
                    try:
                        file_size_val = int(extra_context[k])
                        break
                    except (ValueError, TypeError):
                        file_size_val = extra_context[k]
                        break

        endpoint = "N/A"
        operation = "N/A"
        response_error = "N/A"

        if extra_context:
            if extra_context.get("endpoint"):
                endpoint = str(extra_context["endpoint"])
            elif extra_context.get("api_url"):
                endpoint = str(extra_context["api_url"])

            if extra_context.get("operation"):
                operation = str(extra_context["operation"])
            elif extra_context.get("action"):
                operation = str(extra_context["action"])

            if extra_context.get("response_error") is not None:
                response_error = str(extra_context["response_error"])
            elif extra_context.get("server_response") is not None:
                response_error = str(extra_context["server_response"])

        if operation == "N/A":
            operation = err_function if err_function != "N/A" else "workpulse_operation"
        if endpoint == "N/A":
            endpoint = operation

        # 6. Current application status (workpulse, sync, network, update)
        workpulse_status = "Unknown"
        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            if store.is_workpulse_manually_stopped():
                workpulse_status = "Manually Stopped"
            elif store.is_workpulse_active():
                workpulse_status = "Active"
            else:
                workpulse_status = "Inactive"
        except Exception:
            pass

        sync_status = "Unknown"
        last_successful_sync_time = "Never"
        try:
            from services.sync_service import SyncService
            sync_status = SyncService.last_sync_status
            last_successful_sync_time = SyncService.get_last_successful_sync_time()
        except Exception:
            pass

        network_status = "Unknown"
        try:
            from services.network_monitor import NetworkReachabilityMonitor
            network_status = "Online" if NetworkReachabilityMonitor().is_online else "Offline"
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

        # 7. Recent application log lines
        recent_logs = self._get_recent_logs(max_lines=60)

        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        context_dict = {
            "app_name": APP_NAME,
            "app_version": get_running_app_version(),
            "error_type": error_type,
            "error_message": sanitize_text(error_message),
            "exception_type": exception_type,
            "module": err_module,
            "file": err_file,
            "file_path": err_file_path,
            "function": err_function,
            "line": err_line,
            "calling_module": sanitize_text(err_module),
            "calling_function": sanitize_text(err_function),
            "operation": sanitize_text(operation),
            "endpoint": sanitize_text(endpoint),
            "http_status": str(http_status_val) if http_status_val is not None else "N/A",
            "retry": retry_val,
            "file_size": file_size_val,
            "response_error": sanitize_text(response_error),
            "workpulse_status": workpulse_status,
            "sync_status": sync_status,
            "network_status": network_status,
            "last_successful_sync_time": last_successful_sync_time,
            "sync_failure_time": now_local,
            "update_status": update_status,
            "traceback": sanitize_text(traceback_str),
            "timestamp_local": now_local,
            "timestamp_utc": now_utc,
            "user_details": user_details,
            "device_details": device_details,
            "system_health": system_health,
            "recent_logs": sanitize_text(recent_logs),
            "extra_context": sanitize_text(str(extra_context or {})),
            "extra_context_dict": dict(extra_context or {}),
        }
        context_dict["error_payload"] = self._build_error_payload(context_dict)
        return context_dict

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
        """Construct a structured plain-text report body with real-time system health and sync diagnostics."""
        user = context.get("user_details", {})
        device = context.get("device_details", {})
        health = context.get("system_health", {})

        emp_name = user.get("full_name") or "Not Available"
        emp_code = user.get("employee_code") or user.get("employee_id") or "Not Available"
        emp_id = user.get("employee_id") or emp_code
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
            "iHRMS DESKTOP / WORKPULSE ERROR REPORT\n"
            f"{app_name} - Critical Error Report\n"
            "==================================================\n\n"
            f"Employee Name            : {emp_name}\n"
            f"Employee Code / ID       : {emp_code} (ID: {emp_id})\n"
            f"Device / Host Name       : {hostname}\n"
            f"OS / Platform            : {os_name} {os_version} ({architecture})\n"
            f"{app_name} Version       : v{app_version} (Workpulse App Version: v{app_version})\n\n"
            "==================================================\n"
            "CONNECTIVITY & SYNC DIAGNOSTICS\n"
            "==================================================\n\n"
            f"Network Status           : {context.get('network_status', 'Unknown')}\n"
            f"Sync Status              : {context.get('sync_status', 'Unknown')}\n"
            f"Last Successful Sync Time: {context.get('last_successful_sync_time', 'Never')}\n"
            f"Current Failure Time     : {context.get('sync_failure_time', context.get('timestamp_local', 'N/A'))}\n"
            f"Current Date & Time      : {date_time_str}\n\n"
            "==================================================\n"
            "ERROR / FAILURE DETAILS\n"
            "==================================================\n\n"
            f"Error Type               : {error_type}\n"
            f"Error / Failure Reason   : {error_message}\n"
            f"Module Origin            : {module_str}\n"
            f"API Endpoint / Action    : {api_action}\n"
            f"HTTP Status              : {context.get('http_status', 'N/A')}\n"
            f"Response Details         : {context.get('response_error', 'N/A')}\n\n"
            "==================================================\n"
            "SYSTEM HEALTH & RESOURCES\n"
            "==================================================\n\n"
            f"CPU Usage                : {cpu_usage_str}\n"
            f"CPU Cores                : {cpu_cores_str}\n\n"
            f"RAM Usage                : {ram_usage_str}\n"
            f"RAM Used                 : {ram_used_str}\n"
            f"RAM Available            : {ram_avail_str}\n"
            f"RAM Total                : {ram_total_str}\n\n"
            f"Disk Usage               : {disk_usage_str}\n"
            f"Disk Used                : {disk_used_str}\n"
            f"Disk Free                : {disk_free_str}\n"
            f"Disk Total               : {disk_total_str}\n\n"
            "==================================================\n"
            "ADDITIONAL DETAILS\n"
            "==================================================\n\n"
            f"Username                 : {user.get('username', 'N/A')}\n"
            f"Company Code             : {user.get('company_code', 'N/A')}\n"
            f"Role                     : {user.get('role', 'N/A')}\n"
            f"OS User                  : {device.get('os_user', 'N/A')}\n"
            f"Tracking State (WorkPulse) : {context.get('workpulse_status', 'Unknown')}\n"
            f"Update State             : {context.get('update_status', 'Unknown')}\n"
            f"Python Version           : {python_version}\n\n"
            "--- Traceback ---\n"
            f"{context.get('traceback') or 'No traceback available.'}\n\n"
            "--- Root Cause Error Payload (API JSON) ---\n"
            f"{context.get('error_payload') or self._build_error_payload(context)}\n\n"
            "--- Extra Context ---\n"
            f"{context.get('extra_context')}\n\n"
            "--- Recent Application Logs (Tail) ---\n"
            f"{context.get('recent_logs')}\n\n"
            "==================================================\n"
            "End of Support Report\n"
            "==================================================\n"
        )

    def _build_report_html(self, context: dict[str, Any]) -> str:
        """Construct a clean, professional HTML error report body."""
        user = context.get("user_details", {})
        device = context.get("device_details", {})
        health = context.get("system_health", {})

        emp_name = user.get("full_name") or "Not Available"
        emp_code = user.get("employee_code") or user.get("employee_id") or "Not Available"
        emp_id = user.get("employee_id") or emp_code
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

        network_status = context.get("network_status", "Unknown")
        net_badge_color = "#188038" if network_status.lower() == "online" else "#ea4335"

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
.badge-net {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; background: {net_badge_color}; color: #ffffff; }}
table.meta-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
table.meta-table td {{ padding: 6px 0; vertical-align: top; }}
table.meta-table td.label {{ width: 190px; color: #5f6368; font-weight: 600; }}
table.meta-table td.val {{ color: #202124; font-family: inherit; }}
pre.code-block {{ background: #282c34; color: #abb2bf; padding: 12px; border-radius: 6px; font-size: 12px; overflow-x: auto; font-family: 'Consolas', 'Courier New', monospace; line-height: 1.4; }}
.footer {{ background: #f8f9fa; padding: 12px 24px; font-size: 12px; color: #70757a; text-align: center; border-top: 1px solid #eeeeee; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>iHRMS DESKTOP / WORKPULSE SUPPORT REPORT</h1>
    <p>Application Diagnostics & Network/Sync Failure Incident Report</p>
  </div>
  
  <div class="section">
    <div class="section-title">Employee & Device Information</div>
    <table class="meta-table">
      <tr><td class="label">Employee Name</td><td class="val"><strong>{emp_name}</strong></td></tr>
      <tr><td class="label">Employee Code / ID</td><td class="val"><strong>{emp_code}</strong> (ID: {emp_id})</td></tr>
      <tr><td class="label">Device / Host Name</td><td class="val"><code>{hostname}</code></td></tr>
      <tr><td class="label">OS / Platform</td><td class="val">{os_name} {os_version} ({architecture})</td></tr>
      <tr><td class="label">{app_name} Version</td><td class="val"><strong>v{app_version}</strong> (Workpulse Version: v{app_version})</td></tr>
    </table>
  </div>

  <div class="section">
    <div class="section-title">Connectivity & Sync Diagnostics</div>
    <table class="meta-table">
      <tr><td class="label">Network Status</td><td class="val"><span class="badge-net">{network_status}</span></td></tr>
      <tr><td class="label">Sync Status</td><td class="val"><strong>{context.get('sync_status', 'Unknown')}</strong></td></tr>
      <tr><td class="label">Last Successful Sync Time</td><td class="val">{context.get('last_successful_sync_time', 'Never')}</td></tr>
      <tr><td class="label">Current Failure Time</td><td class="val">{context.get('sync_failure_time', date_time_str)}</td></tr>
      <tr><td class="label">Current Date & Time</td><td class="val">{date_time_str}</td></tr>
    </table>
  </div>

  <div class="section">
    <div class="section-title">Error & Failure Details</div>
    <table class="meta-table">
      <tr><td class="label">Error Type</td><td class="val"><span class="badge">{error_type}</span></td></tr>
      <tr><td class="label">Error / Failure Reason</td><td class="val" style="color: #c5221f; font-weight: 600;">{error_message}</td></tr>
      <tr><td class="label">Module Origin</td><td class="val">{module_str}</td></tr>
      <tr><td class="label">API Endpoint / Action</td><td class="val"><code>{api_action}</code></td></tr>
      <tr><td class="label">HTTP Status</td><td class="val">{context.get('http_status', 'N/A')}</td></tr>
      <tr><td class="label">Response Details</td><td class="val">{context.get('response_error', 'N/A')}</td></tr>
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
      <tr><td class="label">WorkPulse State</td><td class="val">{context.get('workpulse_status', 'Unknown')}</td></tr>
      <tr><td class="label">Update State</td><td class="val">{context.get('update_status', 'Unknown')}</td></tr>
      <tr><td class="label">Python Version</td><td class="val">{python_version}</td></tr>
    </table>
    
    <div style="margin-top: 14px; font-weight: 600; font-size: 13px; color: #5f6368;">Traceback:</div>
    <pre class="code-block">{context.get('traceback') or 'No traceback available.'}</pre>

    <div style="margin-top: 14px; font-weight: 600; font-size: 13px; color: #5f6368;">Root Cause Error Payload (API JSON):</div>
    <pre class="code-block">{context.get('error_payload') or self._build_error_payload(context)}</pre>

    <div style="margin-top: 14px; font-weight: 600; font-size: 13px; color: #5f6368;">Recent Application Logs:</div>
    <pre class="code-block">{context.get('recent_logs')}</pre>
  </div>

  <div class="footer">
    {app_name} v{app_version} &bull; Confidential Support Diagnostic Report &bull; {now_local}
  </div>
</div>
</body>
</html>"""

    # ==============================================================
    # DELIVERY — DIRECT SECURE SMTP DISPATCH & OFFLINE QUEUE
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
            self._last_smtp_result = True
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

        self._last_smtp_result = False
        return False

    # ==============================================================
    # ERROR REPORTING API DISPATCH
    # ==============================================================

    def _resolve_api_url(self) -> str:
        """Resolve the Error Reporting API endpoint URL dynamically."""
        env_url = os.environ.get("IHRMS_REPORT_ERROR_API_URL", "").strip()
        if env_url:
            return env_url

        try:
            from config.api_config import ApiConfig
            cfg = ApiConfig()
            if not cfg.is_verified:
                from PySide6.QtCore import QSettings
                st = QSettings("Indovision", "iHRMSMonitor")
                company_code = st.value("last_company_code") or st.value("ApiConfig/last_verified_code")
                if company_code:
                    cfg.load(company_code=str(company_code).strip())
            if cfg.is_verified:
                return cfg.report_error_url
        except Exception:
            pass

        try:
            from services.secure_session import SessionStore
            session = SessionStore().load_session()
            if session and isinstance(session, dict):
                base_url = session.get("base_url")
                if base_url:
                    return f"{str(base_url).rstrip('/')}/workpulse/report_error"
        except Exception:
            pass

        try:
            from PySide6.QtCore import QSettings
            st = QSettings("Indovision", "iHRMSMonitor")
            cached_url = st.value("ApiConfig/last_base_url") or st.value("session/base_url")
            if cached_url:
                return f"{str(cached_url).rstrip('/')}/workpulse/report_error"
        except Exception:
            pass

        try:
            from config.api_config import ApiConfig
            cfg = ApiConfig()
            if getattr(cfg, "_base_url", None):
                return f"{str(cfg._base_url).rstrip('/')}/workpulse/report_error"
        except Exception:
            pass

        return "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/workpulse/report_error"

    def _resolve_device_token(self, context: dict[str, Any]) -> str:
        """Resolve the enrolled device token dynamically."""
        extra = context.get("extra_context_dict") or {}
        if extra.get("device_token"):
            return str(extra["device_token"]).strip()
        if context.get("device_token"):
            return str(context["device_token"]).strip()

        try:
            from services.session_service import SessionService
            svc = SessionService()
            if getattr(svc, "device_token", None):
                return str(svc.device_token).strip()
            if getattr(svc, "current_user", None) and getattr(svc.current_user, "device_token", None):
                return str(svc.current_user.device_token).strip()
        except Exception:
            pass

        try:
            from services.secure_session import SessionStore
            session = SessionStore().load_session()
            if session and isinstance(session, dict):
                tok = session.get("device_token")
                if tok:
                    return str(tok).strip()
        except Exception:
            pass

        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            enc_tok = store.settings.value(store._KEY_DEVICE_TOKEN)
            if enc_tok:
                dec_tok = store._simple_decrypt(enc_tok)
                if dec_tok:
                    return str(dec_tok).strip()
        except Exception:
            pass

        try:
            from services.sync_service import SyncService
            token = SyncService.re_enroll_device_static()
            if token:
                return str(token).strip()
        except Exception:
            pass

        try:
            from services.device_registry_service import DeviceRegistryService
            from utils.device import get_device_identifier
            dev_id = get_device_identifier()
            for d in DeviceRegistryService().get_all_devices():
                if d.get("device_identifier") == dev_id and d.get("device_token"):
                    return str(d["device_token"]).strip()
        except Exception:
            pass

        try:
            from config.api_config import get_device_id
            dev_id = get_device_id()
            if dev_id:
                return str(dev_id).strip()
        except Exception:
            pass

        return ""

    def _derive_severity(self, error_type: str, extra: dict[str, Any]) -> str:
        """Derive severity level ('critical', 'error', 'warning', 'info')."""
        if extra.get("severity"):
            sev = str(extra["severity"]).strip().lower()
            if sev in ("critical", "error", "warning", "info"):
                return sev

        et_upper = error_type.upper()
        if any(k in et_upper for k in ("CRASH", "CRITICAL", "FATAL", "UNINSTALLED", "CORRUPT")):
            return "critical"
        if any(k in et_upper for k in ("WARN", "WARNING", "DEPRECATED")):
            return "warning"
        if any(k in et_upper for k in ("INFO", "NOTIFICATION", "HEARTBEAT")):
            return "info"
        return "error"

    def _derive_category(
        self,
        error_type: str,
        endpoint: str,
        operation: str,
        extra: dict[str, Any],
    ) -> str:
        """Derive category ('upload', 'sync', 'auth', 'update', 'tracking', 'attendance', 'network', 'general')."""
        if extra.get("error_category"):
            return str(extra["error_category"]).strip().lower()
        if extra.get("category"):
            return str(extra["category"]).strip().lower()

        combined = f"{error_type} {endpoint} {operation} {extra.get('action', '')}".lower()

        if any(k in combined for k in ("screenshot", "upload", "s3", "storage")):
            return "upload"
        if any(k in combined for k in ("sync", "batch", "activity")):
            return "sync"
        if any(k in combined for k in ("login", "auth", "token", "enroll", "credential", "unauthorized")):
            return "auth"
        if any(k in combined for k in ("update", "installer", "version", "download")):
            return "update"
        if any(k in combined for k in ("track", "window", "idle", "hook", "keyboard", "mouse", "capture")):
            return "tracking"
        if any(k in combined for k in ("attendance", "punch", "leave", "timesheet", "kra")):
            return "attendance"
        if any(k in combined for k in ("network", "connection", "dns", "socket", "timeout", "offline", "unreachable")):
            return "network"
        return "general"

    def _derive_agent_endpoint(self, context: dict[str, Any], extra: dict[str, Any]) -> str:
        """Derive clean agent_endpoint string."""
        if extra.get("agent_endpoint"):
            return str(extra["agent_endpoint"]).strip()

        endpoint = context.get("endpoint")
        if endpoint and endpoint != "N/A":
            clean = endpoint.strip().lstrip("/")
            if "/" in clean:
                clean = clean.split("/")[-1]
            return clean

        operation = context.get("operation")
        if operation and operation != "N/A":
            return operation.strip()

        calling_module = context.get("calling_module")
        if calling_module and calling_module != "N/A":
            return calling_module.strip()

        return "workpulse"

    def _build_error_payload(self, context: dict[str, Any]) -> str:
        """Construct JSON string representation for error_payload parameter with all root-cause metrics."""
        user = context.get("user_details", {})
        device = context.get("device_details", {})
        extra = context.get("extra_context_dict", {})

        payload: dict[str, Any] = {}

        # 1. Root-cause fields required by specification
        if context.get("http_status") is not None and context.get("http_status") != "N/A":
            try:
                payload["http_status"] = int(context["http_status"])
            except (ValueError, TypeError):
                payload["http_status"] = context["http_status"]
        elif extra.get("http_status") is not None:
            try:
                payload["http_status"] = int(extra["http_status"])
            except (ValueError, TypeError):
                payload["http_status"] = extra["http_status"]

        if context.get("retry") is not None and context.get("retry") != "N/A":
            try:
                payload["retry"] = int(context["retry"])
            except (ValueError, TypeError):
                payload["retry"] = context["retry"]
        elif extra.get("retry") is not None:
            try:
                payload["retry"] = int(extra["retry"])
            except (ValueError, TypeError):
                payload["retry"] = extra["retry"]

        if context.get("file_size") is not None and context.get("file_size") != "N/A":
            try:
                payload["file_size"] = int(context["file_size"])
            except (ValueError, TypeError):
                payload["file_size"] = context["file_size"]
        elif extra.get("file_size") is not None:
            try:
                payload["file_size"] = int(extra["file_size"])
            except (ValueError, TypeError):
                payload["file_size"] = extra["file_size"]

        payload["exception_type"] = (
            context.get("exception_type")
            or extra.get("exception_type")
            or extra.get("exception")
            or context.get("error_type")
            or "N/A"
        )
        payload["module"] = (
            context.get("module")
            or extra.get("module")
            or context.get("calling_module")
            or "N/A"
        )
        payload["file"] = (
            context.get("file")
            or extra.get("file")
            or (Path(context.get("file_path", "")).name if context.get("file_path") and context.get("file_path") != "N/A" else "N/A")
        )
        payload["file_path"] = (
            context.get("file_path")
            or extra.get("file_path")
            or "N/A"
        )
        payload["function"] = (
            context.get("function")
            or extra.get("function")
            or context.get("calling_function")
            or "N/A"
        )

        line_val = context.get("line") if context.get("line") is not None else extra.get("line")
        if line_val is not None:
            try:
                payload["line"] = int(line_val)
            except (ValueError, TypeError):
                payload["line"] = line_val
        else:
            payload["line"] = None

        payload["message"] = (
            context.get("error_message")
            or extra.get("message")
            or "N/A"
        )
        payload["operation"] = (
            context.get("operation")
            or extra.get("operation")
            or payload["function"]
        )
        payload["endpoint"] = (
            context.get("endpoint")
            or extra.get("endpoint")
            or payload["operation"]
        )
        payload["traceback"] = (
            context.get("traceback")
            or extra.get("traceback")
            or "No traceback available."
        )
        payload["app_version"] = (
            context.get("app_version")
            or extra.get("app_version")
            or get_running_app_version()
        )
        payload["platform"] = (
            context.get("platform")
            or device.get("platform")
            or platform.system()
        )
        payload["occurred_at"] = (
            context.get("timestamp_local")
            or extra.get("occurred_at")
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        # 2. Diagnostics & metadata
        if context.get("response_error") and context.get("response_error") != "N/A":
            payload["response_error"] = context["response_error"]

        if user.get("employee_code") and user.get("employee_code") != "Not Available":
            payload["employee_code"] = user["employee_code"]
        if user.get("employee_id") and user.get("employee_id") != "Not Available":
            payload["employee_id"] = user["employee_id"]
        if user.get("username") and user.get("username") != "Not Available":
            payload["username"] = user["username"]
        if user.get("company_code") and user.get("company_code") != "Not Available":
            payload["company_code"] = user["company_code"]

        if device.get("hostname") and device.get("hostname") != "Unknown":
            payload["hostname"] = device["hostname"]

        if context.get("system_health"):
            payload["system_health"] = context["system_health"]

        if context.get("network_status") and context.get("network_status") != "Unknown":
            payload["network_status"] = context["network_status"]
        if context.get("sync_status") and context.get("sync_status") != "Unknown":
            payload["sync_status"] = context["sync_status"]
        if context.get("workpulse_status") and context.get("workpulse_status") != "Unknown":
            payload["workpulse_status"] = context["workpulse_status"]

        # Support extra error_payload dictionary if supplied
        if isinstance(extra.get("error_payload"), dict):
            for k, v in extra["error_payload"].items():
                if k not in payload:
                    payload[k] = v

        # 3. Merge additional non-secret extra keys
        SECRET_KEYS = (
            "device_token", "password", "auth_token", "bearer", "api_key",
            "secret", "token", "cookie", "cookies", "authorization", "key"
        )
        for k, v in extra.items():
            k_lower = str(k).lower()
            if any(sk in k_lower for sk in SECRET_KEYS) or k in ("error_payload",):
                continue
            if k not in payload:
                if isinstance(v, str):
                    payload[k] = sanitize_text(v)
                else:
                    payload[k] = v

        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception as e:
            logger.debug("Failed to serialize error_payload: %s", e)
            return json.dumps({"error": "Failed to serialize payload"}, ensure_ascii=False)

    def _dispatch_via_api(self, context: dict[str, Any]) -> bool:
        """
        Transmit the error details to the Workpulse Error Reporting API:
        POST /hrms_api/ci4/api/workpulse/report_error

        Returns True on successful delivery (HTTP 200/201), False otherwise.
        """
        url = self._resolve_api_url()
        device_token = self._resolve_device_token(context)
        error_type = context.get("error_type", "ERROR_REPORT")
        error_msg = context.get("error_message", "N/A")
        extra = context.get("extra_context_dict", {})

        severity = extra.get("severity") or self._derive_severity(error_type, extra)
        category = self._derive_category(
            error_type,
            str(context.get("endpoint", "")),
            str(context.get("operation", "")),
            extra,
        )
        agent_endpoint = self._derive_agent_endpoint(context, extra)
        app_version = context.get("app_version", get_running_app_version())
        platform_name = context.get("device_details", {}).get("platform") or platform.system()
        occurred_at = context.get("timestamp_local") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_payload = context.get("error_payload") or self._build_error_payload(context)

        # If device_token is missing or placeholder, attempt dynamic re-enrollment first
        if not device_token or device_token in ("UNKNOWN_DEVICE", "<saved from enroll_device>"):
            try:
                from services.sync_service import SyncService
                re_tok = SyncService.re_enroll_device_static()
                if re_tok:
                    device_token = re_tok
            except Exception:
                pass

        post_data = {
            "device_token": device_token,
            "error_code": error_type,
            "error_message": error_msg,
            "severity": severity,
            "error_category": category,
            "agent_endpoint": agent_endpoint,
            "app_version": app_version,
            "platform": platform_name,
            "occurred_at": occurred_at,
            "error_payload": error_payload,
        }

        masked_token = f"{device_token[:4]}***{device_token[-4:]}" if len(device_token) >= 8 else "***"
        logger.info(
            "Error Reporting API request started: url=%s, error_code=%s, severity=%s, category=%s, endpoint=%s, device_token=%s",
            url, error_type, severity, category, agent_endpoint, masked_token,
        )

        self._last_api_request = dict(post_data)

        try:
            response = requests.post(
                url,
                data=post_data,
                timeout=10,
                headers={"User-Agent": f"Workpulse/{app_version}"},
            )

            status_code = response.status_code
            try:
                res_json = response.json()
            except Exception:
                res_json = {}

            # Handle 401 Unauthorized / Token rejection -> Auto re-enroll and retry once
            if status_code == 401 or "Device not recognized" in response.text or "revoked" in response.text:
                logger.warning(
                    "Error Reporting API rejected device token (HTTP %d). Attempting automatic re-enrollment...",
                    status_code,
                )
                try:
                    from services.sync_service import SyncService
                    new_token = SyncService.re_enroll_device_static()
                    if new_token:
                        new_masked = f"{new_token[:4]}***{new_token[-4:]}" if len(new_token) >= 8 else "***"
                        logger.info("Retrying Error Reporting API with refreshed device_token: %s", new_masked)
                        post_data["device_token"] = new_token
                        context["device_token"] = new_token
                        self._last_api_request = dict(post_data)
                        response = requests.post(
                            url,
                            data=post_data,
                            timeout=10,
                            headers={"User-Agent": f"Workpulse/{app_version}"},
                        )
                        status_code = response.status_code
                        try:
                            res_json = response.json()
                        except Exception:
                            res_json = {}
                except Exception as retry_err:
                    logger.warning("Error Reporting API re-enrollment retry failed: %s", retry_err)

            self._last_api_response = {
                "status_code": status_code,
                "body": res_json if res_json else (response.text if hasattr(response, "text") else ""),
            }

            if status_code in (200, 201) and (not res_json or res_json.get("response") != "Failed"):
                logger.info(
                    "Error Reporting API request succeeded: status=%d, error_code=%s, response=%s",
                    status_code, error_type, res_json.get("message", "Success"),
                )
                return True
            else:
                safe_body = sanitize_text(response.text[:200]) if response.text else "N/A"
                logger.warning(
                    "Error Reporting API returned error status %d: %s",
                    status_code, safe_body,
                )
                return False

        except requests.exceptions.Timeout:
            logger.warning("Error Reporting API request timed out for url: %s", url)
            self._last_api_response = {"status_code": 0, "error": "Request timed out"}
        except requests.exceptions.ConnectionError as conn_err:
            logger.warning("Error Reporting API connection failed for url %s: %s", url, conn_err)
            self._last_api_response = {"status_code": 0, "error": f"Connection error: {conn_err}"}
        except Exception as api_err:
            logger.warning("Error Reporting API dispatch failed for url %s: %s", url, api_err)
            self._last_api_response = {"status_code": 0, "error": str(api_err)}

        return False

    def _dispatch_to_local_log(self, context: dict[str, Any]) -> None:
        """
        Append the full error report to a local ``error_reports.log`` file.

        This is the last-resort fallback when delivery fails or the network is offline.
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
        Deliver the error report via BOTH direct SMTP (support email) and Error Reporting API.

        Environment Policy:
          - Production / Packaged Build (Windows EXE):
              Dispatches BOTH support email and Workpulse Error API.
          - Developer / Local Python Run:
              Suppresses support emails completely to prevent pollution of the support mailbox.
              Suppresses unprompted production API calls for normal developer errors.
              Writes all error diagnostic details to the local error report log file for debugging.
        """
        send_email = self.should_send_email(context)
        send_api = self.should_send_api(context)

        # In developer mode where neither channel is dispatched, record to local log and return cleanly
        if not send_email and not send_api:
            logger.info(
                "ErrorReportService: Error dispatch skipped in developer runtime (support emails and production API are active in packaged builds only): %s",
                context.get("error_type"),
            )
            context["_smtp_sent"] = True
            context["_smtp_skipped_dev"] = True
            context["_api_sent"] = True
            context["_api_skipped_dev"] = True
            self._last_smtp_result = False
            self._last_api_response = {
                "status_code": 0,
                "status": "skipped_dev",
                "message": "API dispatch skipped in development runtime",
            }
            self._dispatch_to_local_log(context)
            return

        is_online = True
        try:
            from services.network_monitor import NetworkReachabilityMonitor
            is_online = NetworkReachabilityMonitor().is_online
        except Exception:
            is_online = True

        if not is_online:
            logger.info("ErrorReportService: Network is offline. Queuing support report locally without attempting network transmission.")
            context["_smtp_sent"] = not send_email
            context["_api_sent"] = not send_api
            if send_email or send_api:
                self._queue_report(context)
            self._dispatch_to_local_log(context)
            return

        # 1. Attempt SMTP Support Email (Production / explicitly forced test only)
        smtp_sent = False
        if not send_email:
            logger.info("ErrorReportService: Support email skipped (development runtime detected: emails enabled in packaged production builds only).")
            smtp_sent = True
            context["_smtp_skipped_dev"] = True
            self._last_smtp_result = False
        elif not context.get("_smtp_sent"):
            try:
                smtp_sent = self._dispatch_via_smtp(context)
            except Exception as smtp_err:
                logger.warning("ErrorReportService: SMTP dispatch error: %s", smtp_err)
                smtp_sent = False
        else:
            smtp_sent = True

        # 2. Attempt Error Reporting API
        api_sent = False
        if not send_api:
            logger.info("ErrorReportService: API dispatch skipped (development runtime detected: production API active in packaged builds).")
            api_sent = True
            context["_api_skipped_dev"] = True
            self._last_api_response = {
                "status_code": 0,
                "status": "skipped_dev",
                "message": "API dispatch skipped in development runtime",
            }
        elif not context.get("_api_sent"):
            try:
                api_sent = self._dispatch_via_api(context)
            except Exception as api_err:
                logger.warning("ErrorReportService: API dispatch error: %s", api_err)
                api_sent = False
        else:
            api_sent = True

        # 3. Always record in local error log for developer debugging
        self._dispatch_to_local_log(context)

        # 4. Check delivery status & offline queue
        if smtp_sent and api_sent:
            if not context.get("_smtp_skipped_dev") and not context.get("_api_skipped_dev"):
                logger.info("ErrorReportService: Report successfully delivered via both SMTP and API.")
            else:
                logger.info("ErrorReportService: Report handled in development mode (logged locally).")
        else:
            logger.info(
                "ErrorReportService: Partial or failed delivery (SMTP=%s, API=%s); queuing remaining for retry.",
                smtp_sent, api_sent,
            )
            context["_smtp_sent"] = smtp_sent
            context["_api_sent"] = api_sent
            self._queue_report(context)

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
        """Alias for dispatching report via Error API."""
        return self._dispatch_via_api(context)

    # ==============================================================
    # PUBLIC API
    # ==============================================================

    def report_sync_failure(
        self,
        error_message: str,
        endpoint: str = "/workpulse/save_activity_batch",
        http_status: int | str | None = None,
        response_error: Any = None,
        exc: Exception | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> None:
        """
        Record and report a sync failure against backend APIs.
        Dispatches report via SMTP if online, or queues in local storage if offline.
        """
        ctx = dict(extra_context or {})
        ctx["endpoint"] = endpoint
        if http_status is not None:
            ctx["http_status"] = str(http_status)
        if response_error is not None:
            ctx["response_error"] = str(response_error)

        self.report_error(
            error_type="SYNC_FAILURE",
            error_message=error_message,
            exc=exc,
            extra_context=ctx,
        )

    def report_error(
        self,
        error_type: str,
        error_message: str,
        exc: Exception | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> None:
        """
        Record and dispatch an error report to the support email address via SMTP or offline queue.

        Runs asynchronously on a background daemon thread so it NEVER blocks caller
        execution, UI rendering, workpulse, or network sync.
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

            import types
            error_record = types.SimpleNamespace(
                error_type=error_type,
                error_message=error_message,
                context=context,
                timestamp=time.time(),
            )
            with self._lock:
                self._reported_errors.append(error_record)
                if len(self._reported_errors) > 100:
                    self._reported_errors.pop(0)


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

    # ==============================================================
    # TEMPORARY TEST ERROR TRIGGER
    # ==============================================================

    def trigger_test_error(
        self,
        synchronous: bool = True,
        force_email: bool = False,
        force_api: bool = True,
        clear_cooldown: bool = False,
    ) -> dict[str, Any]:
        """
        TEMPORARY TEST ONLY: Trigger a real test error to verify Workpulse error reporting.

        When the test is triggered:
          - In production / packaged builds (or if force_email=True):
            Sends the SAME test error through both support email and report_error API.
          - In developer / local Python run (when force_email=False):
            Dispatches report_error API and suppresses support email to protect the production inbox.

        Specifications:
          error_code: TEST_ERROR
          error_message: Workpulse error reporting integration test
          severity: error
          error_category: test

        Captures real dynamic exception, module, file, function, line, and traceback.
        """
        try:
            # Raise an actual test exception to dynamically capture frame, file, line, function, traceback
            raise RuntimeError("Workpulse error reporting integration test")
        except RuntimeError as test_exc:
            extra = {
                "severity": "error",
                "error_category": "test",
                "endpoint": "/workpulse/report_error",
                "operation": "test_error_reporting",
            }
            context = self._collect_context(
                error_type="TEST_ERROR",
                error_message="Workpulse error reporting integration test",
                exc=test_exc,
                extra_context=extra,
            )
            if force_email:
                context["_force_email"] = True
            if force_api:
                context["_force_api"] = True
            context["_is_test"] = True

            sig = self._get_error_signature("TEST_ERROR", "Workpulse error reporting integration test")
            if clear_cooldown:
                self._sent_reports.pop(sig, None)

            is_prod = self.is_production_build()

            if self._is_duplicate(sig):
                logger.info("TEST_ERROR duplicate suppressed by cooldown window.")
                return {
                    "status": "deduplicated",
                    "duplicate_suppressed": True,
                    "message": "Duplicate error suppressed by cooldown window. No duplicate email/API report generated.",
                    "signature": sig,
                    "environment": "production_packaged" if is_prod else "developer_unfrozen",
                    "test_error": {
                        "error_code": "TEST_ERROR",
                        "error_message": "Workpulse error reporting integration test",
                        "severity": "error",
                        "error_category": "test",
                    },
                    "api_request_payload": self._last_api_request,
                    "api_response": self._last_api_response,
                    "email_result": self._last_smtp_result,
                    "email_status": "skipped_in_dev" if not (is_prod or force_email) else ("sent" if self._last_smtp_result else "failed"),
                    "both_working": bool(
                        (self._last_smtp_result if (is_prod or force_email) else True)
                        and self._last_api_response
                        and self._last_api_response.get("status_code") in (200, 201)
                    ),
                }

            self._record_sent(sig)

            if synchronous:
                self._dispatch_report(context)
            else:
                def _async_send() -> None:
                    try:
                        self._dispatch_report(context)
                    except Exception as async_err:
                        logger.debug("Async test error dispatch failed: %s", async_err)

                t = threading.Thread(
                    target=_async_send, name="TestErrorReportWorker", daemon=True
                )
                t.start()
                t.join(timeout=15.0)

            parsed_payload = {}
            try:
                parsed_payload = json.loads(context.get("error_payload", "{}"))
            except Exception:
                pass

            email_sent = bool(self._last_smtp_result)
            email_skipped = bool(context.get("_smtp_skipped_dev", False))
            api_ok = bool(
                self._last_api_response
                and self._last_api_response.get("status_code") in (200, 201)
            )

            # In production (or when force_email is requested): both email and API must be successful.
            # In developer mode (with force_email=False): API must be successful and email must be safely skipped.
            if is_prod or force_email:
                both_working = bool(email_sent and api_ok)
                email_status = "sent" if email_sent else "failed"
            else:
                both_working = bool(api_ok and email_skipped)
                email_status = "skipped_in_dev"

            return {
                "status": "dispatched",
                "duplicate_suppressed": False,
                "environment": "production_packaged" if is_prod else "developer_unfrozen",
                "test_error": {
                    "error_code": context.get("error_type"),
                    "error_message": context.get("error_message"),
                    "severity": extra.get("severity"),
                    "error_category": extra.get("error_category"),
                    "exception_type": parsed_payload.get("exception_type"),
                    "module": parsed_payload.get("module"),
                    "file": parsed_payload.get("file"),
                    "file_path": parsed_payload.get("file_path"),
                    "function": parsed_payload.get("function"),
                    "line": parsed_payload.get("line"),
                    "message": parsed_payload.get("message"),
                    "traceback": parsed_payload.get("traceback"),
                    "endpoint": parsed_payload.get("endpoint"),
                    "operation": parsed_payload.get("operation"),
                    "app_version": parsed_payload.get("app_version"),
                    "platform": parsed_payload.get("platform"),
                    "occurred_at": parsed_payload.get("occurred_at"),
                },
                "api_request_payload": self._last_api_request,
                "api_response": self._last_api_response,
                "email_result": self._last_smtp_result,
                "email_status": email_status,
                "both_working": both_working,
            }
