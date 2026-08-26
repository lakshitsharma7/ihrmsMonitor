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
        raw_login_data: Dict[str, Any] | None = None,
    ) -> None:
        self._current_user = UserSession(
            username=username,
            role=role,
            full_name=full_name,
            user_type=user_type,
            tracking_permitted=tracking_permitted,
            raw_login_data=raw_login_data or {},
        )

    def update_tracking_permitted(self, permitted: bool) -> None:
        """Update the tracking permission flag (called when server pushes new settings)."""
        if self._current_user is not None:
            self._current_user.tracking_permitted = permitted

    def logout(self) -> None:
        self._current_user = None
        self.device_token = None
