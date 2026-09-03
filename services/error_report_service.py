"""Error Reporting Service for iHRMS Monitor.

Collects and securely dispatches error reports to the configured support email
(support-hrms@indovisionservices.in) ONLY when an actual error occurs.

Features:
1. Gathers logged-in user details, device/hostname, app version, error info, timestamp,
   and recent sanitized application logs.
2. Sanitizes sensitive data (passwords, tokens, API keys, credentials) before reporting.
3. Implements deduplication and cooldown to prevent spamming duplicate reports.
4. Asynchronous delivery on a background daemon thread to never block or impact performance.
5. Fails gracefully without interrupting the core application.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import platform
import re
import smtplib
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from config.settings import APP_NAME, APP_VERSION, get_running_app_version
from utils.logger import get_logger
from utils.paths import get_log_file_path

logger = get_logger(__name__)

# Configured support email
DEFAULT_SUPPORT_EMAIL = "support-hrms@indovisionservices.in"
DEFAULT_SMTP_HOST = "indovisionservices-in.mail.protection.outlook.com"
DEFAULT_SMTP_PORT = 25

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
        """Initialize reporting configuration and deduplication caches."""
        self._support_email = os.environ.get("SUPPORT_EMAIL", DEFAULT_SUPPORT_EMAIL).strip()
        self._smtp_host = os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST).strip()
        self._smtp_port = int(os.environ.get("SMTP_PORT", str(DEFAULT_SMTP_PORT)).strip())
        self._smtp_user = os.environ.get("SMTP_USER", "").strip()
        self._smtp_pass = os.environ.get("SMTP_PASS", "").strip()
        self._smtp_from = os.environ.get("SMTP_FROM", f"ihrms-monitor@{socket.gethostname().lower()}.local").strip()

        # Cooldown cache: maps hash(signature) -> last_sent_timestamp
        self._sent_reports: dict[str, float] = {}
        self._cooldown_seconds = 3600.0  # 1 hour cooldown per unique error signature

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

        # 4. Recent application log lines
        recent_logs = self._get_recent_logs(max_lines=60)

        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return {
            "app_name": APP_NAME,
            "app_version": get_running_app_version(),
            "error_type": error_type,
            "error_message": sanitize_text(error_message),
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
    # EMAIL FORMATTING & DISPATCH
    # ==============================================================

    def _build_email_body(self, context: dict[str, Any]) -> str:
        """Construct a formatted text email body for the support report."""
        user = context.get("user_details", {})
        device = context.get("device_details", {})

        return (
            f"==========================================================\n"
            f"iHRMS Monitor - Critical Error Report\n"
            f"==========================================================\n"
            f"Application : {context.get('app_name')} v{context.get('app_version')}\n"
            f"Time (Local): {context.get('timestamp_local')}\n"
            f"Time (UTC)  : {context.get('timestamp_utc')}\n"
            f"Error Type  : {context.get('error_type')}\n"
            f"Error Msg   : {context.get('error_message')}\n\n"
            f"--- User / Employee Context ---\n"
            f"Username    : {user.get('username', 'N/A')}\n"
            f"Employee ID : {user.get('employee_id', 'N/A')}\n"
            f"Full Name   : {user.get('full_name', 'N/A')}\n"
            f"Company Code: {user.get('company_code', 'N/A')}\n"
            f"Role        : {user.get('role', 'N/A')}\n\n"
            f"--- Device / Host Context ---\n"
            f"Hostname    : {device.get('hostname', 'N/A')}\n"
            f"OS User     : {device.get('os_user', 'N/A')}\n"
            f"Platform    : {device.get('platform', 'N/A')} {device.get('os_release', '')} ({device.get('os_version', '')})\n"
            f"Architecture: {device.get('architecture', 'N/A')}\n\n"
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

    def _dispatch_email(self, context: dict[str, Any]) -> bool:
        """Send the formatted error report via SMTP in the background."""
        error_type = context.get("error_type", "ERROR")
        version = context.get("app_version") or get_running_app_version()
        hostname = context.get("device_details", {}).get("hostname", "Unknown")
        emp_id = context.get("user_details", {}).get("employee_id", "N/A")

        subject = f"[iHRMS Monitor Error] {error_type} (v{version} on {hostname}, Emp: {emp_id})"
        body_text = self._build_email_body(context)

        msg = MIMEMultipart()
        msg["From"] = self._smtp_from
        msg["To"] = self._support_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        try:
            # 1. Check if configured with credentials
            if self._smtp_user and self._smtp_pass:
                with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=15) as server:
                    server.ehlo()
                    try:
                        server.starttls()
                        server.ehlo()
                    except Exception:
                        pass
                    server.login(self._smtp_user, self._smtp_pass)
                    server.sendmail(self._smtp_from, [self._support_email], msg.as_string())
                    logger.info("Error report successfully emailed to %s", self._support_email)
                    return True

            # 2. Attempt standard direct SMTP dispatch to support mail exchanger
            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=12) as server:
                server.ehlo()
                try:
                    server.starttls()
                    server.ehlo()
                except Exception:
                    pass
                server.sendmail(self._smtp_from, [self._support_email], msg.as_string())
                logger.info("Error report successfully emailed via direct SMTP to %s", self._support_email)
                return True

        except Exception as send_err:
            logger.warning(
                "Could not send error report email to %s via SMTP (%s): %s",
                self._support_email,
                self._smtp_host,
                send_err,
            )
            return False

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

        Runs asynchronously on a background thread so it NEVER blocks caller execution.
        Deduplicates identical errors within a 1-hour window.
        """
        try:
            sig = self._get_error_signature(error_type, error_message)
            if self._is_duplicate(sig):
                logger.debug("Suppressing duplicate error report for signature: %s (%s)", sig, error_type)
                return

            self._record_sent(sig)

            # Collect context synchronously to capture state at time of error
            context = self._collect_context(
                error_type=error_type,
                error_message=error_message,
                exc=exc,
                extra_context=extra_context,
            )

            # Dispatch asynchronously
            def _async_send():
                try:
                    self._dispatch_email(context)
                except Exception as async_err:
                    logger.debug("Async error report dispatch failed: %s", async_err)

            t = threading.Thread(target=_async_send, name="ErrorReportWorker", daemon=True)
            t.start()

        except Exception as err:
            logger.warning("ErrorReportService.report_error encountered an internal issue: %s", err)
