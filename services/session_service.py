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
    workpulse_permitted: bool = True    # from enroll_device / get_settings
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
    # ── In-memory portal auth credential (runtime only) ───────
    session_credential: str | None = None  # runtime in-memory credential for web portal SSO

    @property
    def display_name(self) -> str:
        """Return the actual authenticated user's name, username, or employee identifier for display."""
        if self.full_name and str(self.full_name).strip():
            fn = str(self.full_name).strip()
            if fn.lower() != "persisted user":
                return fn

        if self.raw_login_data and isinstance(self.raw_login_data, dict):
            login_data = self.raw_login_data.get("data", {}) if isinstance(self.raw_login_data.get("data"), dict) else {}
            for field in (
                "fullName", "full_name", "name", "employee_name", "emp_name",
                "employeeName", "user_name", "emp_fullname", "username"
            ):
                val = self.raw_login_data.get(field) or login_data.get(field)
                if val and str(val).strip() and str(val).strip().lower() != "persisted user":
                    return str(val).strip()

        if self.username and str(self.username).strip() and str(self.username).strip().lower() != "persisted user":
            return str(self.username).strip()

        if self.employee_id and str(self.employee_id).strip():
            return str(self.employee_id).strip()

        if self.indo_code and str(self.indo_code).strip():
            return str(self.indo_code).strip()

        return "User"


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
        workpulse_permitted: bool = True,
        allow_user_device: bool = True,
        allow_logout: bool = True,
        indo_code: str | None = None,
        api_key: str | None = None,
        employee_id: str | None = None,
        company_code: str | None = None,
        device_token: str | None = None,
        raw_login_data: Dict[str, Any] | None = None,
        session_credential: str | None = None,
    ) -> None:
        # Strictly associate device_token with the current user session (never inherit from previous user)
        self.device_token = device_token

        self._current_user = UserSession(
            username=username,
            role=role,
            full_name=full_name,
            user_type=user_type,
            workpulse_permitted=workpulse_permitted,
            allow_user_device=allow_user_device,
            allow_logout=allow_logout,
            indo_code=indo_code,
            api_key=api_key,
            employee_id=employee_id,
            company_code=company_code,
            device_token=device_token,
            raw_login_data=raw_login_data or {},
            session_credential=session_credential,
        )
        try:
            from services.attendance_service import AttendanceService
            AttendanceService().clear_cache()
        except Exception:
            pass
        self.notify_permission_listeners()

    def restore_session(
        self,
        username: str,
        role: str | None = None,
        full_name: str | None = None,
        *,
        user_type: str = "",
        workpulse_permitted: bool = True,
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
            workpulse_permitted=workpulse_permitted,
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

    def get_portal_credentials(self) -> Dict[str, Any] | None:
        """
        Return the authenticated user's dynamic credentials and details for Workpulse/HRMS portal authentication.

        Returns:
            Dict containing user_name, password (if present in memory), employee_id,
            indo_code, company_code, email, user_type, etc., or None if unauthenticated.
        """
        user = self._current_user
        if not user or not (user.username or user.indo_code or user.employee_id):
            return None

        raw = user.raw_login_data if isinstance(user.raw_login_data, dict) else {}
        raw_data = raw.get("data") if isinstance(raw.get("data"), dict) else {}

        def _find_field(*keys: str) -> str | None:
            for k in keys:
                v = raw.get(k) or raw_data.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            return None

        uname = user.username or _find_field("username", "user_name", "userName", "email") or user.indo_code or ""
        pwd = user.session_credential or ""
        emp_id = user.employee_id or _find_field("employee_id", "employeeId", "user_id", "userId", "id") or ""
        emp_code = user.indo_code or _find_field("emp_code", "employee_code", "indo_code", "empCode") or ""
        company = user.company_code or _find_field("company_code", "companyCode", "company_id", "companyId") or ""
        email = _find_field("email", "user_email", "userEmail") or ""
        full_name = user.full_name or _find_field("fullName", "full_name", "name", "employee_name") or user.display_name
        user_type = user.user_type or _find_field("user_type", "userType", "role") or user.role or ""

        if not uname and not emp_id and not emp_code:
            return None

        return {
            "user_name": uname,
            "password": pwd,
            "username": uname,
            "employee_id": emp_id,
            "employee_code": emp_code,
            "indo_code": emp_code,
            "company_code": company,
            "email": email,
            "full_name": full_name,
            "user_type": user_type,
        }


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
        workpulse_permitted: bool | None = None,
        allow_user_device: bool | None = None,
        allow_logout: bool | None = None,
    ) -> None:
        """Update permission flags dynamically (called when server pushes new settings)."""
        changed = False
        if self._current_user is not None:
            if workpulse_permitted is not None and self._current_user.workpulse_permitted != workpulse_permitted:
                self._current_user.workpulse_permitted = workpulse_permitted
                changed = True
            if allow_user_device is not None and self._current_user.allow_user_device != allow_user_device:
                self._current_user.allow_user_device = allow_user_device
                changed = True
            if allow_logout is not None and self._current_user.allow_logout != allow_logout:
                self._current_user.allow_logout = allow_logout
                changed = True
        if changed:
            self.notify_permission_listeners()

    def update_workpulse_permitted(self, permitted: bool) -> None:
        """Update the workpulse permission flag (called when server pushes new settings)."""
        self.update_permissions(workpulse_permitted=permitted)

    def update_device_token(self, token: str | None) -> None:
        """Update active device_token across both SessionService and the current user session."""
        self.device_token = token
        if self._current_user is not None:
            self._current_user.device_token = token

    def logout(self) -> None:
        self._current_user = None
        self.device_token = None
        try:
            from services.attendance_service import AttendanceService
            AttendanceService().clear_cache()
        except Exception:
            pass
        self.notify_permission_listeners()

    def clear(self) -> None:
        """Explicitly clear all in-memory user and device token state."""
        self.logout()

