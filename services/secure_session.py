"""Secure session persistence and restoration.

This module provides encrypted storage of session data to enable automatic
login on app restart while maintaining security. Session data includes:
- Company code (verified from login screen)
- Authentication tokens (indo_code, api_key)
- Device token (from device enrollment)
- Device information (hostname, platform, etc.)

The session is stored in QSettings and encrypted using a machine-specific key
derived from the device identifier. This is not meant for high-security
scenarios (credentials should never be stored unencrypted), but it prevents
casual inspection of credentials while still allowing auto-login.

Session validation:
- Checks if stored session matches expected company context
- Attempts to re-enroll device to verify session is still valid
- Falls back to login screen if session is expired/invalid
"""

from __future__ import annotations

import json
import hashlib
import base64
from typing import Dict, Any
from PySide6.QtCore import QSettings

from utils.logger import get_logger

logger = get_logger(__name__)


class SessionStore:
    """Secure storage and restoration of authenticated sessions.
    
    Uses QSettings (platform-native secure storage) with simple encryption
    based on machine identifier to protect credentials from casual inspection.
    """

    # QSettings keys for persisted session data
    _KEY_COMPANY_CODE = "session/company_code"
    _KEY_BASE_URL = "session/base_url"
    _KEY_COMPANY_ID = "session/company_id"
    _KEY_INDO_CODE = "session/indo_code"
    _KEY_API_KEY = "session/api_key"
    _KEY_DEVICE_TOKEN = "session/device_token"
    _KEY_USERNAME = "session/username"
    _KEY_FULL_NAME = "session/full_name"
    _KEY_USER_TYPE = "session/user_type"
    _KEY_EMPLOYEE_ID = "session/employee_id"
    _KEY_DEVICE_INFO = "session/device_info"
    _KEY_TIMESTAMP = "session/timestamp"
    _KEY_TRACKING_PERMITTED = "session/tracking_permitted"
    _KEY_ALLOW_USER_DEVICE = "session/allow_user_device"
    _KEY_ALLOW_LOGOUT = "session/allow_logout"
    _KEY_ENCRYPTED_CHECKSUM = "session/checksum"
    _KEY_TRACKING_MANUALLY_STOPPED = "session/tracking_manually_stopped"
    _KEY_TRACKING_ACTIVE = "session/tracking_active"

    def __init__(self) -> None:
        """Initialize session store with QSettings."""
        self.settings = QSettings("Indovision", "iHRMSMonitor")

    def _get_machine_key(self) -> str:
        """Generate a machine-specific encryption key.
        
        This key is derived from the machine's device identifier and is used
        to protect stored session data. It's not cryptographically secure but
        prevents casual inspection of stored credentials.
        
        Returns:
            A hex string suitable for simple encryption/decryption.
        """
        from utils.device import get_device_identifier

        device_id = get_device_identifier()
        # Create a deterministic hash based on device ID
        key_material = f"ihrms_monitor_{device_id}".encode("utf-8")
        key = hashlib.sha256(key_material).hexdigest()[:16]
        return key

    def _simple_encrypt(self, data: str) -> str:
        """Simple XOR-based encryption (not cryptographically secure).
        
        This is used to obfuscate session data in QSettings. For true security,
        use proper encryption libraries. This is sufficient to prevent casual
        inspection of stored credentials.
        """
        key = self._get_machine_key()
        key_bytes = key.encode("utf-8")
        data_bytes = data.encode("utf-8")

        encrypted = bytearray()
        for i, byte in enumerate(data_bytes):
            encrypted.append(byte ^ key_bytes[i % len(key_bytes)])

        return base64.b64encode(encrypted).decode("utf-8")

    def _simple_decrypt(self, encrypted: str) -> str | None:
        """Decrypt data encrypted with _simple_encrypt.
        
        Returns None if decryption fails (e.g., data was encrypted with a
        different machine key).
        """
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
        tracking_permitted: bool,
        base_url: str | None = None,
        company_id: str | None = None,
        allow_user_device: bool = True,
        allow_logout: bool = True,
        tracking_manually_stopped: bool | None = None,
    ) -> bool:
        """Save session data securely.
        
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
            tracking_permitted: Whether user can be tracked
            base_url: Resolved API backend URL
            company_id: Resolved company ID
            allow_user_device: Whether User/Device control is enabled
            allow_logout: Whether Logout control is enabled
            tracking_manually_stopped: Whether user manually stopped tracking
            
        Returns:
            True if session was saved successfully
        """
        try:
            # Store non-sensitive data unencrypted
            self.settings.setValue(self._KEY_COMPANY_CODE, company_code)
            if base_url:
                self.settings.setValue(self._KEY_BASE_URL, base_url)
            if company_id:
                self.settings.setValue(self._KEY_COMPANY_ID, str(company_id))

            self.settings.setValue(self._KEY_USERNAME, username)
            self.settings.setValue(self._KEY_FULL_NAME, full_name or "")
            self.settings.setValue(self._KEY_USER_TYPE, user_type)
            self.settings.setValue(self._KEY_EMPLOYEE_ID, employee_id or "")
            self.settings.setValue(self._KEY_TRACKING_PERMITTED, tracking_permitted)
            self.settings.setValue(self._KEY_ALLOW_USER_DEVICE, allow_user_device)
            self.settings.setValue(self._KEY_ALLOW_LOGOUT, allow_logout)

            if tracking_manually_stopped is not None:
                self.set_tracking_manually_stopped(tracking_manually_stopped)
            self.set_tracking_active(True)

            # Store device info as JSON
            device_info_json = json.dumps(device_info)
            self.settings.setValue(self._KEY_DEVICE_INFO, device_info_json)

            # Encrypt sensitive auth data
            self.settings.setValue(
                self._KEY_INDO_CODE, self._simple_encrypt(indo_code)
            )
            self.settings.setValue(self._KEY_API_KEY, self._simple_encrypt(api_key))
            self.settings.setValue(
                self._KEY_DEVICE_TOKEN, self._simple_encrypt(device_token)
            )

            # Store timestamp for potential session expiration logic
            import time

            timestamp = str(int(time.time()))
            self.settings.setValue(self._KEY_TIMESTAMP, timestamp)

            # Store a checksum to verify data integrity
            checksum_data = f"{company_code}:{indo_code}:{api_key}"
            checksum = hashlib.sha256(checksum_data.encode()).hexdigest()
            self.settings.setValue(
                self._KEY_ENCRYPTED_CHECKSUM, self._simple_encrypt(checksum)
            )

            logger.info("Session saved for user: %s (company: %s)", username, company_code)
            return True

        except Exception:
            logger.exception("Failed to save session")
            return False

    def update_device_token(self, device_token: str) -> bool:
        """Update only the device token in secure session storage."""
        try:
            self.settings.setValue(
                self._KEY_DEVICE_TOKEN, self._simple_encrypt(device_token)
            )
            return True
        except Exception:
            logger.exception("Failed to update device token in session store")
            return False

    def load_session(self) -> Dict[str, Any] | None:
        """Load and validate a previously saved session.
        
        Returns:
            Dict with session data if a valid session is found, None otherwise.
            The dict contains:
            - company_code
            - base_url
            - company_id
            - indo_code
            - api_key
            - device_token
            - username
            - full_name
            - user_type
            - employee_id
            - device_info
            - tracking_permitted
        """
        try:
            company_code = self.settings.value(self._KEY_COMPANY_CODE)
            if not company_code:
                return None

            username = self.settings.value(self._KEY_USERNAME)
            if not username:
                return None

            # Decrypt sensitive data
            indo_code_enc = self.settings.value(self._KEY_INDO_CODE)
            api_key_enc = self.settings.value(self._KEY_API_KEY)
            device_token_enc = self.settings.value(self._KEY_DEVICE_TOKEN)

            if not all([indo_code_enc, api_key_enc, device_token_enc]):
                logger.warning("Session missing required encrypted fields")
                return None

            indo_code = self._simple_decrypt(indo_code_enc)
            api_key = self._simple_decrypt(api_key_enc)
            device_token = self._simple_decrypt(device_token_enc)

            if not all([indo_code, api_key, device_token]):
                logger.warning("Failed to decrypt session data (machine key mismatch?)")
                return None

            # Verify data integrity via checksum
            checksum_expected = hashlib.sha256(
                f"{company_code}:{indo_code}:{api_key}".encode()
            ).hexdigest()
            checksum_stored_enc = self.settings.value(self._KEY_ENCRYPTED_CHECKSUM)
            if checksum_stored_enc:
                checksum_stored = self._simple_decrypt(checksum_stored_enc)
                if checksum_stored != checksum_expected:
                    logger.warning("Session checksum mismatch - data may be corrupted")
                    return None

            base_url = self.settings.value(self._KEY_BASE_URL) or None
            company_id = self.settings.value(self._KEY_COMPANY_ID) or None
            full_name = self.settings.value(self._KEY_FULL_NAME) or None
            user_type = self.settings.value(self._KEY_USER_TYPE) or "User"
            employee_id = self.settings.value(self._KEY_EMPLOYEE_ID) or None
            tracking_permitted_raw = self.settings.value(self._KEY_TRACKING_PERMITTED, True)
            tracking_permitted = (
                tracking_permitted_raw is True
                or str(tracking_permitted_raw).lower() in ("true", "1")
            )
            allow_user_device_raw = self.settings.value(self._KEY_ALLOW_USER_DEVICE, True)
            allow_user_device = (
                allow_user_device_raw is True
                or str(allow_user_device_raw).lower() in ("true", "1")
            )
            allow_logout_raw = self.settings.value(self._KEY_ALLOW_LOGOUT, True)
            allow_logout = (
                allow_logout_raw is True
                or str(allow_logout_raw).lower() in ("true", "1")
            )

            device_info_json = self.settings.value(self._KEY_DEVICE_INFO, "{}")
            try:
                device_info = json.loads(device_info_json)
            except Exception:
                device_info = {}

            session = {
                "company_code": company_code,
                "base_url": base_url,
                "company_id": company_id,
                "indo_code": indo_code,
                "api_key": api_key,
                "device_token": device_token,
                "username": username,
                "full_name": full_name,
                "user_type": user_type,
                "employee_id": employee_id,
                "device_info": device_info,
                "tracking_permitted": tracking_permitted,
                "allow_user_device": allow_user_device,
                "allow_logout": allow_logout,
                "tracking_manually_stopped": self.is_tracking_manually_stopped(),
                "tracking_active": self.is_tracking_active(),
            }

            logger.info(
                "Session loaded for user: %s (company: %s)",
                username,
                company_code,
            )
            return session

        except Exception:
            logger.exception("Failed to load session")
            return None

    def clear_session(self) -> None:
        """Clear all persisted session data."""
        try:
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
            self.settings.remove(self._KEY_TIMESTAMP)
            self.settings.remove(self._KEY_TRACKING_PERMITTED)
            self.settings.remove(self._KEY_ALLOW_USER_DEVICE)
            self.settings.remove(self._KEY_ALLOW_LOGOUT)
            self.settings.remove(self._KEY_ENCRYPTED_CHECKSUM)
            self.settings.remove(self._KEY_TRACKING_MANUALLY_STOPPED)
            self.settings.remove(self._KEY_TRACKING_ACTIVE)

            logger.info("Session data cleared")
        except Exception:
            logger.exception("Failed to clear session")

    def is_tracking_manually_stopped(self) -> bool:
        """Check if user manually stopped tracking."""
        raw = self.settings.value(self._KEY_TRACKING_MANUALLY_STOPPED, False)
        return raw is True or str(raw).lower() in ("true", "1")

    def set_tracking_manually_stopped(self, stopped: bool) -> None:
        """Record whether user manually stopped tracking."""
        self.settings.setValue(self._KEY_TRACKING_MANUALLY_STOPPED, bool(stopped))

    def is_tracking_active(self) -> bool:
        """Check if tracking was actively running."""
        raw = self.settings.value(self._KEY_TRACKING_ACTIVE, False)
        return raw is True or str(raw).lower() in ("true", "1")

    def set_tracking_active(self, active: bool) -> None:
        """Record whether tracking is actively running."""
        self.settings.setValue(self._KEY_TRACKING_ACTIVE, bool(active))

    def validate_session(self) -> bool:
        """Validate that a saved session can be decrypted.
        
        This checks if the machine key can decrypt stored data without
        attempting to verify server-side validity.
        
        Returns:
            True if session data exists and can be decrypted, False otherwise.
        """
        session = self.load_session()
        return session is not None
