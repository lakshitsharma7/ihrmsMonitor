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
    # ── Auth data returned dynamically by the login API ───────
    indo_code: str | None = None       # employee code from login
    api_key: str | None = None         # auth token from login
    employee_id: str | None = None     # employee id from login
    raw_login_data: Dict[str, Any] = field(default_factory=dict)


class SessionService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._current_user = None
            cls._instance.device_token = None
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
        indo_code: str | None = None,
        api_key: str | None = None,
        employee_id: str | None = None,
        raw_login_data: Dict[str, Any] | None = None,
    ) -> None:
        self._current_user = UserSession(
            username=username,
            role=role,
            full_name=full_name,
            user_type=user_type,
            tracking_permitted=tracking_permitted,
            indo_code=indo_code,
            api_key=api_key,
            employee_id=employee_id,
            raw_login_data=raw_login_data or {},
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

    def update_tracking_permitted(self, permitted: bool) -> None:
        """Update the tracking permission flag (called when server pushes new settings)."""
        if self._current_user is not None:
            self._current_user.tracking_permitted = permitted

    def logout(self) -> None:
        self._current_user = None
        self.device_token = None
