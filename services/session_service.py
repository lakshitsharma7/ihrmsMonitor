"""Session manager service for desktop authentication."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class UserSession:
    username: str
    role: str
    full_name: str | None = None
    # ── RBAC / permission fields from server ──────────────────
    user_type: str = ""                # from login API (e.g. "Joined")
    tracking_permitted: bool = True    # from enroll_device / get_settings
    allow_user_device: bool = True     # dynamic from server / DB (User/Device modal)
    allow_logout: bool = True          # dynamic from server / DB (Logout control)
    # ── Auth data returned dynamically by the login API ───────
    indo_code: str | None = None       # employee code from login
    api_key: str | None = None         # auth token from login
    employee_id: str | None = None     # employee id from login
    raw_login_data: Dict[str, Any] = field(default_factory=dict)
    # ── Company context ───────────────────────────────────────
    company_code: str | None = None    # verified company code
    device_token: str | None = None    # device enrollment token
    device_info: Dict[str, str] | None = None  # device information


class SessionService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._current_user = None
            cls._instance.device_token = None
            cls._instance._permission_listeners = []
        return cls._instance

    @property
    def current_user(self) -> UserSession | None:
        return self._current_user

    def login(
        self,
        username: str,
        role: str,
        full_name: str | None = None,
        *,
        user_type: str = "",
        tracking_permitted: bool = True,
        allow_user_device: bool = True,
        allow_logout: bool = True,
        indo_code: str | None = None,
        api_key: str | None = None,
        employee_id: str | None = None,
        company_code: str | None = None,
        device_token: str | None = None,
        raw_login_data: Dict[str, Any] | None = None,
    ) -> None:
        # Strictly associate device_token with the current user session (never inherit from previous user)
        self.device_token = device_token

        self._current_user = UserSession(
            username=username,
            role=role,
            full_name=full_name,
            user_type=user_type,
            tracking_permitted=tracking_permitted,
            allow_user_device=allow_user_device,
            allow_logout=allow_logout,
            indo_code=indo_code,
            api_key=api_key,
            employee_id=employee_id,
            company_code=company_code,
            device_token=device_token,
            raw_login_data=raw_login_data or {},
        )
        self.notify_permission_listeners()

    def restore_session(
        self,
        username: str,
        role: str | None = None,
        full_name: str | None = None,
        *,
        user_type: str = "",
        tracking_permitted: bool = True,
        allow_user_device: bool = True,
        allow_logout: bool = True,
        indo_code: str | None = None,
        api_key: str | None = None,
        employee_id: str | None = None,
        company_code: str | None = None,
        device_token: str | None = None,
    ) -> None:
        """Restore a previously saved session.
        
        Similar to login() but used when restoring from persistent storage.
        """
        self.login(
            username=username,
            role=role or user_type,
            full_name=full_name,
            user_type=user_type,
            tracking_permitted=tracking_permitted,
            allow_user_device=allow_user_device,
            allow_logout=allow_logout,
            indo_code=indo_code,
            api_key=api_key,
            employee_id=employee_id,
            company_code=company_code,
            device_token=device_token,
        )


    def auth_payload(self) -> Dict[str, str]:
        """
        Return the auth fields that downstream APIs expect.

        Built from the values the login API returned for the current
        session, so no caller needs to hold credentials of its own.
        """

        user = self._current_user

        if user is None:
            return {}

        payload: Dict[str, str] = {}

        if user.indo_code:
            payload["indo_code"] = user.indo_code

        if user.api_key:
            payload["key"] = user.api_key

        return payload

    def register_permission_listener(self, callback: Any) -> None:
        """Register a callback invoked whenever permissions change."""
        if not hasattr(self, "_permission_listeners"):
            self._permission_listeners = []
        if callback not in self._permission_listeners:
            self._permission_listeners.append(callback)

    def unregister_permission_listener(self, callback: Any) -> None:
        """Unregister a previously registered permission listener."""
        if hasattr(self, "_permission_listeners") and callback in self._permission_listeners:
            self._permission_listeners.remove(callback)

    def notify_permission_listeners(self) -> None:
        """Notify all listeners that permissions or session state have been updated."""
        if not hasattr(self, "_permission_listeners"):
            self._permission_listeners = []
            return
        for cb in list(self._permission_listeners):
            try:
                cb()
            except Exception:
                pass

    def update_permissions(
        self,
        *,
        tracking_permitted: bool | None = None,
        allow_user_device: bool | None = None,
        allow_logout: bool | None = None,
    ) -> None:
        """Update permission flags dynamically (called when server pushes new settings)."""
        changed = False
        if self._current_user is not None:
            if tracking_permitted is not None and self._current_user.tracking_permitted != tracking_permitted:
                self._current_user.tracking_permitted = tracking_permitted
                changed = True
            if allow_user_device is not None and self._current_user.allow_user_device != allow_user_device:
                self._current_user.allow_user_device = allow_user_device
                changed = True
            if allow_logout is not None and self._current_user.allow_logout != allow_logout:
                self._current_user.allow_logout = allow_logout
                changed = True
        if changed:
            self.notify_permission_listeners()

    def update_tracking_permitted(self, permitted: bool) -> None:
        """Update the tracking permission flag (called when server pushes new settings)."""
        self.update_permissions(tracking_permitted=permitted)

    def logout(self) -> None:
        self._current_user = None
        self.device_token = None
        self.notify_permission_listeners()

    def clear(self) -> None:
        """Explicitly clear all in-memory user and device token state."""
        self.logout()
