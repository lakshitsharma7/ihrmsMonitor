"""Session manager service for desktop authentication."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserSession:
    username: str
    role: str
    full_name: str | None = None


class SessionService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._current_user = None
        return cls._instance

    @property
    def current_user(self) -> UserSession | None:
        return self._current_user

    def login(self, username: str, role: str, full_name: str | None = None) -> None:
        self._current_user = UserSession(username=username, role=role, full_name=full_name)

    def logout(self) -> None:
        self._current_user = None
