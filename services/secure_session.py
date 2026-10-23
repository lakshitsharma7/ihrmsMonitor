"""Secure session persistence and restoration.

This module provides encrypted storage of session data to enable automatic
login on app restart while maintaining security. Session data includes:
- Company code (verified from login screen)
- Authentication tokens (indo_code, api_key)
- Device token (from device enrollment)
- Device information (hostname, platform, etc.)

Uses Windows Credential Manager (via win32cred) on Windows for DPAPI-protected,
hardware/user-bound secure credential storage, with encrypted QSettings
fallback for cross-platform compatibility (macOS/Linux) and backward compatibility.

Session validation:
- Checks if stored session matches expected company context
- Attempts to re-enroll device to verify session is still valid
- Falls back to login screen if session is expired/invalid
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from typing import Dict, Any
from PySide6.QtCore import QSettings

from utils.logger import get_logger

logger = get_logger(__name__)

PROD_CRED_TARGET = "iHRMS_Desktop:session"
TEST_CRED_TARGET = "iHRMS_Desktop_Test:session"


def _cred_write(target: str, username: str, data: dict) -> bool:
    """Store credential dictionary securely in Windows Credential Manager or macOS Keychain."""
    if sys.platform.startswith("win"):
        try:
            import win32cred

            blob_str = json.dumps(data)
            cred = {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": target,
                "UserName": username or "iHRMS_User",
                "CredentialBlob": blob_str,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            }
            win32cred.CredWrite(cred)
            return True
        except Exception as exc:
            logger.debug("Windows Credential Manager CredWrite failed: %s", exc)
            return False
    elif sys.platform == "darwin":
        try:
            import subprocess

            blob_str = json.dumps(data)
            cmd = [
                "/usr/bin/security",
                "add-generic-password",
                "-a", username or "iHRMS_User",
                "-s", target,
                "-w", blob_str,
                "-U",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return res.returncode == 0
        except Exception as exc:
            logger.debug("macOS Keychain add-generic-password failed: %s", exc)
            return False
    return False


def _cred_read(target: str) -> dict | None:
    """Retrieve and deserialize credential dictionary from Windows Credential Manager or macOS Keychain."""
    if sys.platform.startswith("win"):
        try:
            import win32cred

            cred = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC)
            raw = cred.get("CredentialBlob")
            if raw is None:
                return None
            if isinstance(raw, bytes):
                try:
                    decoded = raw.decode("utf-16-le")
                except Exception:
                    decoded = raw.decode("utf-8", errors="replace")
            else:
                decoded = str(raw)
            return json.loads(decoded)
        except Exception:
            # Error 1168 (Element not found) or missing target
            return None
    elif sys.platform == "darwin":
        try:
            import subprocess

            cmd = [
                "/usr/bin/security",
                "find-generic-password",
                "-s", target,
                "-w",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout.strip())
        except Exception:
            return None
    return None


def _cred_delete(target: str) -> bool:
    """Remove target credential from Windows Credential Manager or macOS Keychain."""
    if sys.platform.startswith("win"):
        try:
            import win32cred

            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC)
            return True
        except Exception:
            return False
    elif sys.platform == "darwin":
        try:
            import subprocess

            cmd = [
                "/usr/bin/security",
                "delete-generic-password",
                "-s", target,
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=5)
            return res.returncode == 0
        except Exception:
            return False
    return False


class SessionStore:
    """Secure storage and restoration of authenticated sessions.
    
    Uses Windows Credential Manager on Windows (DPAPI user/hardware encryption)
    with encrypted QSettings fallback on non-Windows platforms.
    """

    # QSettings keys for persisted session data
    _KEY_COMPANY_CODE = "session/company_code"
    _KEY_BASE_URL = "session/base_url"
    _KEY_COMPANY_ID = "session/company_id"
    _KEY_PORTAL_URL = "session/portal_url"
    _KEY_LOGO_URL = "session/logo_url"
    _KEY_EMAIL = "session/email"
    _KEY_INDO_CODE = "session/indo_code"
    _KEY_API_KEY = "session/api_key"
    _KEY_DEVICE_TOKEN = "session/device_token"
    _KEY_USERNAME = "session/username"
    _KEY_FULL_NAME = "session/full_name"
    _KEY_USER_TYPE = "session/user_type"
    _KEY_EMPLOYEE_ID = "session/employee_id"
    _KEY_DEVICE_INFO = "session/device_info"
    _KEY_SESSION_CREDENTIAL = "session/session_credential"
    _KEY_TIMESTAMP = "session/timestamp"
    _KEY_TRACKING_PERMITTED = "session/workpulse_permitted"
    _KEY_ALLOW_USER_DEVICE = "session/allow_user_device"
    _KEY_ALLOW_LOGOUT = "session/allow_logout"
    _KEY_ENCRYPTED_CHECKSUM = "session/checksum"
    _KEY_TRACKING_MANUALLY_STOPPED = "session/workpulse_manually_stopped"
    _KEY_TRACKING_ACTIVE = "session/workpulse_active"
    _KEY_TRACKING_PAUSED = "session/workpulse_paused"
    _KEY_CLEAN_SHUTDOWN = "session/clean_shutdown"

    def __init__(self, settings: QSettings | None = None, is_test: bool | None = None) -> None:
        """Initialize session store with test isolation support."""
        if is_test is not None:
            self.is_test = is_test
        else:
            self.is_test = (
                os.environ.get("IHRMS_TEST_MODE") == "1"
                or ("unittest" in sys.modules and not os.environ.get("IHRMS_PRODUCTION_SESSION"))
            )

        if self.is_test:
            self.settings = settings or QSettings("Indovision_Test", "iHRMSMonitor")
            self.cred_target = TEST_CRED_TARGET
        else:
            self.settings = settings or QSettings("Indovision", "iHRMSMonitor")
            self.cred_target = PROD_CRED_TARGET

    def _get_machine_key(self) -> str:
        """Generate a machine-specific encryption key for fallback QSettings encryption."""
        from utils.device import get_device_identifier

        device_id = get_device_identifier()
        key_material = f"ihrms_monitor_{device_id}".encode("utf-8")
        return hashlib.sha256(key_material).hexdigest()[:16]

    def _simple_encrypt(self, data: str) -> str:
        """XOR-based obfuscation with base64 encoding for fallback QSettings."""
        if not data:
            return ""
        key = self._get_machine_key()
        key_bytes = key.encode("utf-8")
        data_bytes = data.encode("utf-8")

        encrypted = bytearray()
        for i, byte in enumerate(data_bytes):
            encrypted.append(byte ^ key_bytes[i % len(key_bytes)])

        return base64.b64encode(encrypted).decode("utf-8")

    def _simple_decrypt(self, encrypted: str) -> str | None:
        """Decrypt data encrypted with _simple_encrypt."""
        if not encrypted:
            return ""
        try:
            key = self._get_machine_key()
            key_bytes = key.encode("utf-8")
            encrypted_bytes = base64.b64decode(encrypted.encode("utf-8"))

            decrypted = bytearray()
            for i, byte in enumerate(encrypted_bytes):
                decrypted.append(byte ^ key_bytes[i % len(key_bytes)])

            return decrypted.decode("utf-8")
        except Exception:
            logger.debug("Failed to decrypt session data", exc_info=True)
            return None

    def save_session(
        self,
        company_code: str,
        indo_code: str,
        api_key: str,
        device_token: str,
        username: str,
        full_name: str | None,
        user_type: str,
        employee_id: str | None,
        device_info: Dict[str, str],
        workpulse_permitted: bool,
        base_url: str | None = None,
        company_id: str | None = None,
        portal_url: str | None = None,
        logo_url: str | None = None,
        email: str | None = None,
        allow_user_device: bool = True,
        allow_logout: bool = True,
        workpulse_manually_stopped: bool | None = None,
        session_credential: str | None = None,
    ) -> bool:
        """Save session data securely in Windows Credential Manager and encrypted QSettings.
        
        Args:
            company_code: Verified company code
            indo_code: Employee/user code from login API
            api_key: Authentication token from login API
            device_token: Device enrollment token
            username: Logged-in username
            full_name: User's full name
            user_type: User type/role from login API
            employee_id: Employee ID
            device_info: Device information dict
            workpulse_permitted: Whether user can be tracked
            base_url: Resolved API backend URL
            company_id: Resolved company ID
            portal_url: Resolved web portal URL
            logo_url: Resolved company logo URL
            email: Employee email
            allow_user_device: Whether User/Device control is enabled
            allow_logout: Whether Logout control is enabled
            workpulse_manually_stopped: Whether user manually stopped workpulse
            session_credential: Optional runtime credential for portal SSO
            
        Returns:
            True if session was saved successfully
        """
        try:
            # 1. Prepare credential blob for Windows Credential Manager
            cred_dict = {
                "company_code": company_code,
                "indo_code": indo_code,
                "api_key": api_key,
                "device_token": device_token,
                "username": username,
                "full_name": full_name or "",
                "user_type": user_type or "User",
                "employee_id": employee_id or "",
                "device_info": device_info or {},
                "workpulse_permitted": bool(workpulse_permitted),
                "base_url": base_url or "",
                "company_id": str(company_id or ""),
                "portal_url": str(portal_url or ""),
                "logo_url": str(logo_url or ""),
                "email": str(email or ""),
                "allow_user_device": bool(allow_user_device),
                "allow_logout": bool(allow_logout),
                "session_credential": session_credential or "",
                "timestamp": int(time.time()),
            }

            _cred_write(self.cred_target, username, cred_dict)

            # 2. Persist in QSettings with simple encryption for cross-platform / fallback support
            self.settings.setValue(self._KEY_COMPANY_CODE, company_code)
            if base_url:
                self.settings.setValue(self._KEY_BASE_URL, base_url)
            if company_id:
                self.settings.setValue(self._KEY_COMPANY_ID, str(company_id))
            if portal_url:
                self.settings.setValue(self._KEY_PORTAL_URL, str(portal_url))
            if logo_url:
                self.settings.setValue(self._KEY_LOGO_URL, str(logo_url))
            if email:
                self.settings.setValue(self._KEY_EMAIL, str(email))

            self.settings.setValue(self._KEY_USERNAME, username)
            self.settings.setValue(self._KEY_FULL_NAME, full_name or "")
            self.settings.setValue(self._KEY_USER_TYPE, user_type)
            self.settings.setValue(self._KEY_EMPLOYEE_ID, employee_id or "")
            self.settings.setValue(self._KEY_TRACKING_PERMITTED, workpulse_permitted)
            self.settings.setValue(self._KEY_ALLOW_USER_DEVICE, allow_user_device)
            self.settings.setValue(self._KEY_ALLOW_LOGOUT, allow_logout)

            if workpulse_manually_stopped is not None:
                self.set_workpulse_manually_stopped(workpulse_manually_stopped)
            self.set_workpulse_active(True)

            device_info_json = json.dumps(device_info or {})
            self.settings.setValue(self._KEY_DEVICE_INFO, device_info_json)

            # Encrypt sensitive tokens in QSettings
            self.settings.setValue(self._KEY_INDO_CODE, self._simple_encrypt(indo_code))
            self.settings.setValue(self._KEY_API_KEY, self._simple_encrypt(api_key))
            self.settings.setValue(self._KEY_DEVICE_TOKEN, self._simple_encrypt(device_token))
            if session_credential:
                self.settings.setValue(self._KEY_SESSION_CREDENTIAL, self._simple_encrypt(session_credential))

            timestamp = str(int(time.time()))
            self.settings.setValue(self._KEY_TIMESTAMP, timestamp)

            # Checksum
            checksum_data = f"{company_code}:{indo_code}:{api_key}"
            checksum = hashlib.sha256(checksum_data.encode()).hexdigest()
            self.settings.setValue(self._KEY_ENCRYPTED_CHECKSUM, self._simple_encrypt(checksum))

            logger.info("Session securely saved for user: %s (company: %s)", username, company_code)
            return True

        except Exception:
            logger.exception("Failed to save session")
            return False

    def update_device_token(self, device_token: str) -> bool:
        """Update only the device token in secure session storage."""
        try:
            # Update Windows Credential Manager
            cred_dict = _cred_read(self.cred_target)
            if cred_dict:
                cred_dict["device_token"] = device_token
                _cred_write(self.cred_target, cred_dict.get("username", "iHRMS_User"), cred_dict)

            # Update QSettings
            self.settings.setValue(self._KEY_DEVICE_TOKEN, self._simple_encrypt(device_token))
            return True
        except Exception:
            logger.exception("Failed to update device token in session store")
            return False

    def load_session(self) -> Dict[str, Any] | None:
        """Load and validate a previously saved session.
        
        Checks Windows Credential Manager first, then falls back to encrypted QSettings.
        """
        try:
            # 1. Attempt loading from Windows Credential Manager
            cred_dict = _cred_read(self.cred_target)
            if cred_dict and isinstance(cred_dict, dict):
                company_code = cred_dict.get("company_code")
                username = cred_dict.get("username")
                indo_code = cred_dict.get("indo_code")
                api_key = cred_dict.get("api_key")
                device_token = cred_dict.get("device_token")

                if company_code and username and indo_code and api_key and device_token:
                    cred_store_name = "Windows Credential Manager" if sys.platform.startswith("win") else "macOS Keychain"
                    logger.info("Loaded valid session from %s: user=%s company=%s", cred_store_name, username, company_code)
                    session = dict(cred_dict)
                    session["workpulse_manually_stopped"] = self.is_workpulse_manually_stopped()
                    session["workpulse_active"] = self.is_workpulse_active()
                    return session

            # 2. Fallback to encrypted QSettings
            company_code = self.settings.value(self._KEY_COMPANY_CODE)
            if not company_code:
                return None

            username = self.settings.value(self._KEY_USERNAME)
            if not username:
                return None

            indo_code_enc = self.settings.value(self._KEY_INDO_CODE)
            api_key_enc = self.settings.value(self._KEY_API_KEY)
            device_token_enc = self.settings.value(self._KEY_DEVICE_TOKEN)

            if not all([indo_code_enc, api_key_enc, device_token_enc]):
                logger.warning("Session missing required encrypted fields in QSettings")
                return None

            indo_code = self._simple_decrypt(indo_code_enc)
            api_key = self._simple_decrypt(api_key_enc)
            device_token = self._simple_decrypt(device_token_enc)

            if not all([indo_code, api_key, device_token]):
                logger.warning("Failed to decrypt session data in QSettings (machine key mismatch?)")
                return None

            # Verify checksum if present
            checksum_stored_enc = self.settings.value(self._KEY_ENCRYPTED_CHECKSUM)
            if checksum_stored_enc:
                checksum_expected = hashlib.sha256(f"{company_code}:{indo_code}:{api_key}".encode()).hexdigest()
                checksum_stored = self._simple_decrypt(checksum_stored_enc)
                if checksum_stored and checksum_stored != checksum_expected:
                    logger.warning("Session checksum mismatch in QSettings - data may be corrupted")
                    return None

            base_url = self.settings.value(self._KEY_BASE_URL) or None
            company_id = self.settings.value(self._KEY_COMPANY_ID) or None
            portal_url = self.settings.value(self._KEY_PORTAL_URL) or None
            logo_url = self.settings.value(self._KEY_LOGO_URL) or None
            email = self.settings.value(self._KEY_EMAIL) or None
            full_name = self.settings.value(self._KEY_FULL_NAME) or None
            user_type = self.settings.value(self._KEY_USER_TYPE) or "User"
            employee_id = self.settings.value(self._KEY_EMPLOYEE_ID) or None

            raw_cred_enc = self.settings.value(self._KEY_SESSION_CREDENTIAL)
            session_credential = self._simple_decrypt(raw_cred_enc) if raw_cred_enc else None

            workpulse_permitted_raw = self.settings.value(self._KEY_TRACKING_PERMITTED, True)
            workpulse_permitted = workpulse_permitted_raw is True or str(workpulse_permitted_raw).lower() in ("true", "1")

            allow_user_device_raw = self.settings.value(self._KEY_ALLOW_USER_DEVICE, True)
            allow_user_device = allow_user_device_raw is True or str(allow_user_device_raw).lower() in ("true", "1")

            allow_logout_raw = self.settings.value(self._KEY_ALLOW_LOGOUT, True)
            allow_logout = allow_logout_raw is True or str(allow_logout_raw).lower() in ("true", "1")

            device_info_json = self.settings.value(self._KEY_DEVICE_INFO, "{}")
            try:
                device_info = json.loads(device_info_json)
            except Exception:
                device_info = {}

            session = {
                "company_code": company_code,
                "base_url": base_url,
                "company_id": company_id,
                "portal_url": portal_url,
                "logo_url": logo_url,
                "email": email,
                "indo_code": indo_code,
                "api_key": api_key,
                "device_token": device_token,
                "username": username,
                "full_name": full_name,
                "user_type": user_type,
                "employee_id": employee_id,
                "device_info": device_info,
                "workpulse_permitted": workpulse_permitted,
                "allow_user_device": allow_user_device,
                "allow_logout": allow_logout,
                "session_credential": session_credential,
                "workpulse_manually_stopped": self.is_workpulse_manually_stopped(),
                "workpulse_active": self.is_workpulse_active(),
            }

            # Migrate / elevate to Windows Credential Manager if on Windows
            _cred_write(self.cred_target, username, session)

            logger.info("Session loaded from QSettings for user: %s (company: %s)", username, company_code)
            return session

        except Exception:
            logger.exception("Failed to load session")
            return None

    def clear_session(self) -> None:
        """Clear all persisted session data from Windows Credential Manager and QSettings."""
        try:
            # Delete from Windows Credential Manager
            _cred_delete(self.cred_target)

            # Clear session keys from QSettings
            self.settings.remove(self._KEY_COMPANY_CODE)
            self.settings.remove(self._KEY_BASE_URL)
            self.settings.remove(self._KEY_COMPANY_ID)
            self.settings.remove(self._KEY_INDO_CODE)
            self.settings.remove(self._KEY_API_KEY)
            self.settings.remove(self._KEY_DEVICE_TOKEN)
            self.settings.remove(self._KEY_USERNAME)
            self.settings.remove(self._KEY_FULL_NAME)
            self.settings.remove(self._KEY_USER_TYPE)
            self.settings.remove(self._KEY_EMPLOYEE_ID)
            self.settings.remove(self._KEY_DEVICE_INFO)
            self.settings.remove(self._KEY_SESSION_CREDENTIAL)
            self.settings.remove(self._KEY_TIMESTAMP)
            self.settings.remove(self._KEY_TRACKING_PERMITTED)
            self.settings.remove(self._KEY_ALLOW_USER_DEVICE)
            self.settings.remove(self._KEY_ALLOW_LOGOUT)
            self.settings.remove(self._KEY_ENCRYPTED_CHECKSUM)
            self.settings.remove(self._KEY_TRACKING_MANUALLY_STOPPED)
            self.settings.remove(self._KEY_TRACKING_ACTIVE)
            self.settings.remove(self._KEY_TRACKING_PAUSED)
            self.settings.remove("last_company_code")
            self.settings.remove("last_username")
            self.settings.remove("last_employee_id")

            logger.info("Session data cleared from Credential Manager and QSettings")
        except Exception:
            logger.exception("Failed to clear session")

    def get_last_company_code(self) -> str | None:
        """Retrieve the last verified company code from an active/saved session."""
        # Check Credential Manager first
        cred_dict = _cred_read(self.cred_target)
        if cred_dict and cred_dict.get("company_code"):
            return str(cred_dict["company_code"]).strip()

        # Check QSettings session
        cc = self.settings.value(self._KEY_COMPANY_CODE)
        if cc and isinstance(cc, str) and cc.strip():
            return cc.strip()

        return None

    def is_workpulse_manually_stopped(self) -> bool:
        """Check if user manually stopped workpulse."""
        raw = self.settings.value(self._KEY_TRACKING_MANUALLY_STOPPED, False)
        return raw is True or str(raw).lower() in ("true", "1")

    def set_workpulse_manually_stopped(self, stopped: bool) -> None:
        """Record whether user manually stopped workpulse."""
        self.settings.setValue(self._KEY_TRACKING_MANUALLY_STOPPED, bool(stopped))

    def is_workpulse_active(self) -> bool:
        """Check if workpulse was actively running."""
        raw = self.settings.value(self._KEY_TRACKING_ACTIVE, False)
        return raw is True or str(raw).lower() in ("true", "1")

    def set_workpulse_active(self, active: bool) -> None:
        """Record whether workpulse is actively running."""
        self.settings.setValue(self._KEY_TRACKING_ACTIVE, bool(active))

    def is_workpulse_paused(self) -> bool:
        """Check if user paused workpulse status."""
        raw = self.settings.value(self._KEY_TRACKING_PAUSED, False)
        return raw is True or str(raw).lower() in ("true", "1")

    def set_workpulse_paused(self, paused: bool) -> None:
        """Record whether user paused workpulse status."""
        self.settings.setValue(self._KEY_TRACKING_PAUSED, bool(paused))

    is_tracking_manually_stopped = is_workpulse_manually_stopped
    set_tracking_manually_stopped = set_workpulse_manually_stopped
    is_tracking_active = is_workpulse_active
    set_tracking_active = set_workpulse_active
    is_tracking_paused = is_workpulse_paused
    set_tracking_paused = set_workpulse_paused

    def is_clean_shutdown(self) -> bool:
        """Check if application previously shut down cleanly."""
        raw = self.settings.value(self._KEY_CLEAN_SHUTDOWN, True)
        return raw is True or str(raw).lower() in ("true", "1")

    def set_clean_shutdown(self, clean: bool) -> None:
        """Record whether application shut down cleanly."""
        self.settings.setValue(self._KEY_CLEAN_SHUTDOWN, bool(clean))

    def validate_session(self) -> bool:
        """Validate that a saved session exists and has essential credentials.
        
        Returns:
            True if session data exists and can be decrypted/loaded, False otherwise.
        """
        session = self.load_session()
        if not session:
            return False
        return bool(
            session.get("company_code")
            and session.get("username")
            and session.get("indo_code")
            and session.get("api_key")
        )
