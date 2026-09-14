"""Error Reporting Service for iHRMS Monitor.

Collects and securely dispatches error reports to the configured support email
(support-hrms@indovisionservices.in) ONLY when an actual error occurs.

Delivery architecture
---------------------
Error reports are delivered in two stages, in order:

1. **Backend HTTP POST** (primary — no SMTP from EXE)
   The report is serialised to JSON and POSTed to the existing iHRMS backend
   at ``tracking/report_error``.  The backend server handles the final email
   delivery, so the desktop EXE never opens an SMTP socket.  This is the same
   HTTP mechanism used for activity sync and screenshot upload, which Seqrite
   Endpoint Protection already permits.

2. **Local log file** (fallback — backend unreachable)
   If the backend POST fails (no network, server down, endpoint not yet
   deployed), the full report is appended to ``error_reports.log`` in the
   application data directory.  No SMTP connection is attempted from the EXE
   under any circumstances.

Why no direct SMTP?
   Seqrite Endpoint Protection intercepts any process that opens a raw SMTP
   socket and blocks it unless the EXE is whitelisted as a "Trusted Email
   Client".  iHRMS Monitor is a monitoring tool, not a mail client, so it
   should never be treated as one.  Removing smtplib calls from the EXE
   eliminates the popup entirely without weakening security.

Features:
1. Gathers logged-in user details, device/hostname, app version, error info,
   timestamp, and recent sanitized application logs.
2. Sanitizes sensitive data (passwords, tokens, API keys) before reporting.
3. Implements deduplication and cooldown to prevent spamming duplicate reports.
4. Asynchronous delivery on a background daemon thread to never block or
   impact performance.
5. Fails gracefully without interrupting the core application.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import re
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import APP_NAME, APP_VERSION, get_running_app_version
from utils.logger import get_logger
from utils.paths import get_log_file_path

logger = get_logger(__name__)

# Configured support email — kept for documentation and backend payload.
# The desktop EXE no longer connects to any SMTP host directly.
DEFAULT_SUPPORT_EMAIL = "support-hrms@indovisionservices.in"
DEFAULT_SMTP_HOST = "indovisionservices-in.mail.protection.outlook.com"   # backend reference only
FALLBACK_SMTP_HOST = "mail.indovisionservices.in"                          # backend reference only
DEFAULT_SMTP_PORT = 25                                                      # backend reference only
DEFAULT_SMTP_FROM = "noreply-ihrms@indovisionservices.in"

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
    """Centralized Error Reporting Service."""

    _instance: ErrorReportService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ErrorReportService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_service()
            return cls._instance

    def _init_service(self) -> None:
        """Initialize reporting configuration, listener list, and deduplication caches."""
        self._support_email = os.environ.get("SUPPORT_EMAIL", DEFAULT_SUPPORT_EMAIL).strip()
        # SMTP fields retained for documentation / backend payload metadata only.
        # The EXE itself does NOT connect to any SMTP server.
        self._smtp_from = os.environ.get("SMTP_FROM", DEFAULT_SMTP_FROM).strip()

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
        """Collect all relevant diagnostic information."""
        # 1. User details
        user_details = {}
        try:
            from services.session_service import SessionService
            session = SessionService().current_user
            if session:
                user_details = {
                    "username": session.username,
                    "full_name": session.full_name or "N/A",
                    "employee_id": session.employee_id or "N/A",
                    "company_code": session.company_code or "N/A",
                    "role": session.role or "N/A",
                }
            else:
                from services.secure_session import SessionStore
                saved = SessionStore().load_session()
                if saved:
                    user_details = {
                        "username": saved.get("username", "N/A"),
                        "full_name": saved.get("full_name", "N/A"),
                        "employee_id": saved.get("employee_id", "N/A"),
                        "company_code": saved.get("company_code", "N/A"),
                        "role": saved.get("user_type", "N/A"),
                    }
        except Exception:
            user_details = {"error": "Could not extract user details"}

        # 2. Device details
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
        }

        # 3. Stack trace
        traceback_str = ""
        if exc is not None:
            import traceback
            traceback_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        # 4. Extract explicit API & HTTP diagnostics if provided
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

        # 5. Extract module and function where error originated
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

        # 6. Current application status (tracking, sync, update)
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

        # 7. Recent application log lines
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
        """Construct a formatted plain-text report body."""
        user = context.get("user_details", {})
        device = context.get("device_details", {})

        return (
            f"==========================================================\n"
            f"iHRMS Monitor - Critical Error Report\n"
            f"==========================================================\n"
            f"Application   : {context.get('app_name')} v{context.get('app_version')}\n"
            f"Time (Local)  : {context.get('timestamp_local')}\n"
            f"Time (UTC)    : {context.get('timestamp_utc')}\n"
            f"Error Type    : {context.get('error_type')}\n"
            f"Error Msg     : {context.get('error_message')}\n\n"
            f"--- Module & Operation Diagnostics ---\n"
            f"Module / File : {context.get('calling_module', 'N/A')}\n"
            f"Function      : {context.get('calling_function', 'N/A')}\n"
            f"Operation     : {context.get('operation', 'N/A')}\n"
            f"Endpoint / URL: {context.get('endpoint', 'N/A')}\n"
            f"HTTP Status   : {context.get('http_status', 'N/A')}\n"
            f"Response Err  : {context.get('response_error', 'N/A')}\n\n"
            f"--- Application State ---\n"
            f"Tracking State: {context.get('tracking_status', 'Unknown')}\n"
            f"Sync State    : {context.get('sync_status', 'Unknown')}\n"
            f"Update State  : {context.get('update_status', 'Unknown')}\n\n"
            f"--- User / Employee Context ---\n"
            f"Username      : {user.get('username', 'N/A')}\n"
            f"Employee ID   : {user.get('employee_id', 'N/A')}\n"
            f"Full Name     : {user.get('full_name', 'N/A')}\n"
            f"Company Code  : {user.get('company_code', 'N/A')}\n"
            f"Role          : {user.get('role', 'N/A')}\n\n"
            f"--- Device / Host Context ---\n"
            f"Hostname      : {device.get('hostname', 'N/A')}\n"
            f"OS User       : {device.get('os_user', 'N/A')}\n"
            f"Platform      : {device.get('platform', 'N/A')} {device.get('os_release', '')} ({device.get('os_version', '')})\n"
            f"Architecture  : {device.get('architecture', 'N/A')}\n\n"
            f"--- Traceback ---\n"
            f"{context.get('traceback') or 'No traceback available.'}\n\n"
            f"--- Extra Context ---\n"
            f"{context.get('extra_context')}\n\n"
            f"--- Recent Application Logs (Tail) ---\n"
            f"{context.get('recent_logs')}\n\n"
            f"==========================================================\n"
            f"End of Error Report\n"
            f"==========================================================\n"
        )

    # ==============================================================
    # DELIVERY — BACKEND HTTP POST (NO SMTP FROM EXE)
    # ==============================================================

    def _dispatch_via_backend(self, context: dict[str, Any]) -> bool:
        """
        POST the error report to the iHRMS backend endpoint
        ``tracking/report_error``.

        The backend is responsible for forwarding the report to the configured
        support email address.  The desktop EXE never opens an SMTP socket, so
        Seqrite Endpoint Protection's "Trusted Email Client" check is never
        triggered.

        Returns True on success, False if the backend is unreachable or
        the endpoint is not yet deployed.
        """
        try:
            from config.api_config import ApiConfig
            report_url = ApiConfig().report_error_url
        except Exception:
            logger.debug(
                "ErrorReportService: no verified API base URL available; "
                "skipping backend dispatch."
            )
            return False

        # Build a compact form-data payload — consistent with other tracking
        # endpoints that already use requests.post(data=...).
        payload: dict[str, Any] = {
            "support_email": self._support_email,
            "from_address": self._smtp_from,
            "app_name": context.get("app_name", APP_NAME),
            "app_version": context.get("app_version", get_running_app_version()),
            "error_type": context.get("error_type", ""),
            "error_message": context.get("error_message", ""),
            "timestamp_local": context.get("timestamp_local", ""),
            "timestamp_utc": context.get("timestamp_utc", ""),
            "calling_module": context.get("calling_module", ""),
            "calling_function": context.get("calling_function", ""),
            "endpoint": context.get("endpoint", ""),
            "http_status": context.get("http_status", ""),
            "response_error": context.get("response_error", ""),
            "tracking_status": context.get("tracking_status", ""),
            "sync_status": context.get("sync_status", ""),
            "update_status": context.get("update_status", ""),
            "user_details": json.dumps(context.get("user_details", {})),
            "device_details": json.dumps(context.get("device_details", {})),
            "traceback": context.get("traceback", ""),
            "extra_context": context.get("extra_context", ""),
            # Limit recent_logs to last 30 lines to avoid oversized payloads
            "recent_logs": "\n".join(
                context.get("recent_logs", "").splitlines()[-30:]
            ),
        }

        # Attach device token so the backend can authenticate the request
        # using the same mechanism as the sync endpoints.
        try:
            from services.session_service import SessionService
            device_token = SessionService().device_token
            if device_token:
                payload["device_token"] = device_token
        except Exception:
            pass

        try:
            import requests as _requests
            response = _requests.post(report_url, data=payload, timeout=12)
            if 200 <= response.status_code < 300:
                logger.info(
                    "ErrorReportService: backend accepted error report "
                    "(HTTP %d) at %s",
                    response.status_code,
                    report_url,
                )
                return True
            logger.warning(
                "ErrorReportService: backend returned HTTP %d for error report at %s",
                response.status_code,
                report_url,
            )
        except Exception as http_err:
            logger.debug(
                "ErrorReportService: backend HTTP dispatch failed: %s", http_err
            )

        return False

    def _dispatch_to_local_log(self, context: dict[str, Any]) -> None:
        """
        Append the full error report to a local ``error_reports.log`` file.

        This is the last-resort fallback when the backend is unreachable.
        No SMTP connection is opened under any circumstances.
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
        Deliver the error report without opening any SMTP socket.

        Delivery order:
          1. HTTP POST to ``tracking/report_error`` on the iHRMS backend.
             The backend emails the report; the EXE never touches SMTP.
          2. If the backend is unreachable, append to local ``error_reports.log``.
             The report is preserved for the next support session.
        """
        delivered = self._dispatch_via_backend(context)
        if not delivered:
            logger.info(
                "ErrorReportService: backend unavailable; "
                "falling back to local log file."
            )
            self._dispatch_to_local_log(context)

    # --------------------------------------------------------------
    # Compatibility aliases
    # --------------------------------------------------------------

    def _build_email_body(self, context: dict[str, Any]) -> str:
        """Alias for _build_report_text to maintain interface compatibility."""
        return self._build_report_text(context)

    def _dispatch_email(self, context: dict[str, Any]) -> bool:
        """Alias for dispatching report via backend HTTP API."""
        return self._dispatch_via_backend(context)

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
        Record and dispatch an error report to support-hrms@indovisionservices.in.

        Runs asynchronously on a background thread so it NEVER blocks caller
        execution.  Deduplicates identical errors within a 1-hour window.

        Delivery is via HTTP POST to the iHRMS backend (no SMTP from EXE),
        with local-file fallback when the backend is unreachable.
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
