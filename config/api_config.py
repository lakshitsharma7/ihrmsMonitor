"""Centralized API configuration, resolved from the entered Company Code.

No Company Code and no company details are hardcoded. The user types a
Company Code on the login screen; it is posted to the existing App
Controller endpoint, which returns that company's API base URL and details:

    POST <APP_CONTROLLER_URL>
    controller_id=<Company Code entered by the user>

    {
        "response": "Success",
        "status": 200,
        "data": {
            "fk_company_id": "1",
            "base_url": "https://.../hrms_api/ci4/api/",
            "logo_url": "https://.../logo.png",
            ...
        }
    }

Every other module asks this module for the base URL instead of holding its
own copy, so every API call automatically targets the verified company.

Until a company has been verified there is no base URL at all: callers get
an ApiConfigError rather than a fallback to any default company. That is
deliberate - a fallback is how one company's data reaches another company's
session.
"""

from __future__ import annotations

import os
import sys
import threading

import requests

from utils.logger import get_logger


logger = get_logger(__name__)


# ==================================================================
# COMPANY VERIFICATION ENDPOINT
#
# The address of the existing verification API. The Company Code posted to
# it is always supplied by the user - there is no default and no fallback.
# ==================================================================

APP_CONTROLLER_URL = os.environ.get(
    "IHRMS_APP_CONTROLLER_URL",
    "https://info.indovisionservices.in/dev/v15/hrms_api/v7/api/appcontroller/appcontroller",
)

# How long to wait for the App Controller bootstrap call.
# Kept short so DNS failures are surfaced quickly rather than making
# the user wait the full default socket timeout.
APP_CONTROLLER_TIMEOUT_SECONDS = 8


# ==================================================================
# DEVICE PROVISIONING
#
# The backend treats ``imei_number`` as the device identity and binds an
# account to it. Logging in with a value it has not enrolled is rejected
# with "Either Duplicate Device Or Invalid Device", so this is a
# provisioning value that must match the backend - not a value the client
# is free to generate.
#
# Set IHRMS_DEVICE_ID to give a machine its own identity once that machine
# has been enrolled on the backend. utils.device.get_device_identifier()
# returns the machine's own stable id, which is what should be enrolled.
# ==================================================================

ENROLLED_DEVICE_ID = "357327072154830"

DEVICE_ID_ENV_VAR = "IHRMS_DEVICE_ID"


def get_device_id() -> str:
    """
    Return the device identity to send as ``imei_number``.

    Uses the per-machine override when one is configured, otherwise the
    unique machine identifier from utils.device.get_device_identifier().
    """

    override = os.environ.get(DEVICE_ID_ENV_VAR, "").strip()

    if override:
        logger.info(
            "Using device id from %s",
            DEVICE_ID_ENV_VAR,
        )

        return override

    try:
        from utils.device import get_device_identifier

        machine_id = get_device_identifier()
        if machine_id:
            return machine_id
    except Exception:
        pass

    return ENROLLED_DEVICE_ID


def _service_message(payload: dict) -> str:
    """Return the message the configuration service gave for a failure."""

    message = str(payload.get("message") or "").strip()

    return message or "This Company Code could not be verified."


class ApiConfigError(RuntimeError):
    """Raised when the API configuration could not be resolved."""


class ApiConfig:
    """
    Resolves and caches the backend configuration for this company.

    The App Controller is called once per process; the resolved values are
    cached because they are deployment configuration, not runtime data.
    """

    _instance: ApiConfig | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ApiConfig:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clear_state()
        return cls._instance

    def _clear_state(self) -> None:
        """Drop every value belonging to a previously resolved company."""

        self._base_url = None
        self._company_id = None
        self._logo_url = None
        self._company_code = None
        self._details = {}
        self._loaded_from_cache = False

    def reset(self) -> None:
        """
        Forget the currently resolved company.

        Called when the user changes the Company Code so that no part of the
        previous company's configuration can be reused.
        """

        with self._lock:
            self._clear_state()

        logger.info("Resolved company configuration cleared")

    # --------------------------------------------------------------
    # BOOTSTRAP
    # --------------------------------------------------------------

    def load(
        self,
        *,
        company_code: str | None = None,
        force: bool = False,
    ) -> None:
        """
        Verify ``company_code`` and adopt that company's configuration.

        The code is required. On failure nothing is retained, so a rejected
        code can never leave a previously verified company in place.
        Re-verifying the same code is a no-op unless ``force`` is set.
        """

        with self._lock:
            cc = str(company_code or "").strip()

            # There is no default company to fall back on.
            if not cc:
                raise ApiConfigError(
                    "A Company Code is required."
                )

            # Already verified this exact company; nothing to redo.
            if self._company_code == cc and self._base_url and not force:
                return

            # Discard the previous company before contacting the service, so
            # a failure below cannot leave stale details behind for the login
            # request to use.
            self._clear_state()

            logger.info(
                "Verifying company code %s",
                cc,
            )

            try:
                response = requests.post(
                    APP_CONTROLLER_URL,
                    data={
                        "controller_id": cc,
                    },
                    timeout=APP_CONTROLLER_TIMEOUT_SECONDS,
                )

                response.raise_for_status()

                payload = response.json()

            except Exception as exc:  # noqa: BLE001
                exc_str = str(exc)
                # Detect DNS resolution failures specifically so the error message
                # is more actionable than a generic "check your connection" prompt.
                is_dns_failure = (
                    "getaddrinfo failed" in exc_str
                    or "Name or service not known" in exc_str
                    or "nodename nor servname" in exc_str
                    or "Errno 11001" in exc_str   # Windows WSAHOST_NOT_FOUND
                    or "Errno 11002" in exc_str   # Windows WSATRY_AGAIN
                )

                logger.warning(
                    "App Controller request failed (%s): %s",
                    "DNS failure" if is_dns_failure else "network error",
                    exc,
                )

                # If network fails, check if we have cached configuration for this exact company
                try:
                    from PySide6.QtCore import QSettings
                    st = QSettings("Indovision", "iHRMSMonitor")
                    cached_cc = st.value("ApiConfig/last_verified_code")
                    cached_url = st.value("ApiConfig/last_base_url")
                    if cached_cc == cc and cached_url:
                        self._company_code = cc
                        self._base_url = str(cached_url).rstrip("/")
                        self._company_id = st.value("ApiConfig/last_company_id") or None
                        self._logo_url = st.value("ApiConfig/last_logo_url") or None
                        import json
                        raw_det = st.value("ApiConfig/last_details", "{}")
                        self._details = json.loads(raw_det) if isinstance(raw_det, str) else {}
                        self._loaded_from_cache = True
                        logger.info(
                            "Verification service unreachable; using cached configuration "
                            "for company %s: %s",
                            cc,
                            self._base_url,
                        )
                        return
                    else:
                        logger.warning(
                            "No cached configuration found for company code '%s' "
                            "(cached code is '%s'). Cannot proceed offline.",
                            cc,
                            cached_cc,
                        )
                except Exception as cache_err:
                    logger.debug("Could not read cached config: %s", cache_err)

                # Never fall back to another company's configuration.
                self._clear_state()

                if is_dns_failure:
                    raise ApiConfigError(
                        "Cannot reach the verification server "
                        "(DNS resolution failed for the server address). "
                        "Please check your internet connection and try again."
                    ) from exc

                raise ApiConfigError(
                    "Could not reach the verification service. "
                    "Please check your connection and try again."
                ) from exc

            data = payload.get("data") or {}

            base_url = str(
                data.get("base_url") or ""
            ).strip()

            # The service answers HTTP 200 for unknown company codes and
            # signals the outcome in the body (status 200 + base_url on
            # success, status 201 with a message on failure), so the body is
            # what decides whether this company is verified.
            if not base_url:
                self._clear_state()

                raise ApiConfigError(
                    _service_message(payload)
                )

            self._base_url = base_url.rstrip("/")

            company_id = data.get("fk_company_id")

            self._company_id = (
                str(company_id)
                if company_id is not None
                else None
            )

            logo_url = data.get("logo_url")

            self._logo_url = (
                str(logo_url)
                if logo_url
                else None
            )

            self._company_code = cc

            self._details = dict(data)

            # Persist successfully verified company config
            try:
                from PySide6.QtCore import QSettings
                st = QSettings("Indovision", "iHRMSMonitor")
                st.setValue("ApiConfig/last_verified_code", self._company_code)
                st.setValue("ApiConfig/last_base_url", self._base_url)
                if self._company_id:
                    st.setValue("ApiConfig/last_company_id", self._company_id)
                if self._logo_url:
                    st.setValue("ApiConfig/last_logo_url", self._logo_url)
                import json
                st.setValue("ApiConfig/last_details", json.dumps(self._details))
            except Exception as cache_save_err:
                logger.debug("Could not cache company configuration: %s", cache_save_err)

            logger.info(
                "Company verified: code=%s company_id=%s base_url=%s",
                self._company_code,
                self._company_id,
                self._base_url,
            )

    def set_cached_configuration(
        self,
        company_code: str,
        base_url: str,
        company_id: str | None = None,
        logo_url: str | None = None,
        details: dict | None = None,
    ) -> None:
        """Adopt pre-verified company configuration from persistent cache."""
        with self._lock:
            self._company_code = str(company_code).strip()
            self._base_url = str(base_url).rstrip("/")
            self._company_id = str(company_id) if company_id is not None else None
            self._logo_url = str(logo_url) if logo_url else None
            self._details = dict(details) if details else {}
            logger.info(
                "Company configuration adopted from cache: code=%s company_id=%s base_url=%s",
                self._company_code,
                self._company_id,
                self._base_url,
            )

    # --------------------------------------------------------------
    # RESOLVED VALUES
    # --------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """
        Return the verified company's API base URL.

        Raises ApiConfigError when no company has been verified: there is no
        default backend to fall back to.
        """

        if not self._base_url:
            raise ApiConfigError(
                "No company has been verified. "
                "Enter and verify a Company Code first."
            )

        return self._base_url

    @property
    def company_id(self) -> str | None:
        """
        Company id of the verified company, or None.

        Deliberately does not resolve anything: falling back to the default
        company here would report one company's id while another code is
        entered.
        """

        return self._company_id

    @property
    def company_code(self) -> str | None:
        """The Company Code that produced the current configuration."""

        return self._company_code

    @property
    def details(self) -> dict:
        """The verified company's details exactly as the service returned."""

        return dict(self._details)

    @property
    def is_verified(self) -> bool:
        """True when a company has been successfully verified."""

        return bool(self._base_url and self._company_code)

    @property
    def logo_url(self) -> str | None:
        """Logo URL of the verified company, or None. Does not resolve."""

        return self._logo_url

    @property
    def activity_tracker_version(self) -> str | None:
        """Latest tracker version configured in AppController."""
        return self._details.get("activity_tracker_version")

    @property
    def activity_tracker_link(self) -> str | None:
        """Tracker download or version URL configured in AppController."""
        return self._details.get("activity_tracker_link")

    @property
    def version_url(self) -> str | None:
        """Version URL configured in AppController (fallback to activity_tracker_link)."""
        return self._details.get("version_url") or self._details.get("activity_tracker_link")

    def get_platform_update_info(self, platform_name: str | None = None) -> dict:
        """
        Extract platform-specific update metadata dictionary from verified AppController details.

        Example structure from AppController data:
            "apps": {
                "WINDOWS": {"version_code": "1", "file_name": "https://indovisionservices.in/workpulse/Workpulse-Installer.exe", "force_to_update": "0"},
                "MAC": {"version_code": "1", "file_name": "https://indovisionservices.in/workpulse/Workpulse.dmg", "force_to_update": "0"}
            }
        """
        if platform_name is None:
            platform_name = "MAC" if sys.platform == "darwin" else "WINDOWS"

        details = self._details or {}
        # 1. Look in details["apps"][platform_name]
        apps = details.get("apps")
        if isinstance(apps, dict) and platform_name in apps and isinstance(apps[platform_name], dict):
            return apps[platform_name]

        # 2. Look in details[platform_name]
        if platform_name in details and isinstance(details[platform_name], dict):
            return details[platform_name]

        # 3. Look in details["data"]["apps"][platform_name] if details is the full payload
        data = details.get("data")
        if isinstance(data, dict):
            data_apps = data.get("apps")
            if isinstance(data_apps, dict) and platform_name in data_apps and isinstance(data_apps[platform_name], dict):
                return data_apps[platform_name]
            if platform_name in data and isinstance(data[platform_name], dict):
                return data[platform_name]

        return {}

    @property
    def punch_url(self) -> str | None:
        """Configurable punch endpoint URL from AppController, environment, or default endpoint."""
        url = (
            os.environ.get("IHRMS_PUNCH_API_URL")
            or self._details.get("punch_url")
            or self._details.get("punch_api_url")
            or (self.endpoint("punch/get_punch_time") if self.is_verified else None)
        )
        if url and not (url.lower().endswith("get_punch_time") or url.lower().endswith("get_punch_time/")):
            if url.rstrip("/").lower().endswith("punch"):
                url = f"{url.rstrip('/')}/get_punch_time"
            else:
                url = f"{url.rstrip('/')}/punch/get_punch_time"
        return url

    @property
    def login_url(self) -> str:
        """Configurable login endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_LOGIN_API_URL")
            or self._details.get("login_url")
            or self._details.get("login_api_url")
            or self.endpoint("login/login")
        )

    @property
    def enroll_device_url(self) -> str:
        """Configurable device enrollment endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_ENROLL_DEVICE_API_URL")
            or self._details.get("enroll_device_url")
            or self._details.get("enroll_url")
            or self.endpoint("workpulse/enroll_device")
        )

    @property
    def get_settings_url(self) -> str:
        """Configurable get_settings endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_GET_SETTINGS_API_URL")
            or self._details.get("get_settings_url")
            or self._details.get("settings_url")
            or self.endpoint("workpulse/get_settings")
        )

    @property
    def save_activity_batch_url(self) -> str:
        """Configurable activity batch save endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_SAVE_ACTIVITY_BATCH_API_URL")
            or self._details.get("save_activity_batch_url")
            or self._details.get("activity_batch_url")
            or self.endpoint("workpulse/save_activity_batch")
        )

    @property
    def upload_screenshot_url(self) -> str:
        """Configurable screenshot upload endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_UPLOAD_SCREENSHOT_API_URL")
            or self._details.get("upload_screenshot_url")
            or self._details.get("screenshot_url")
            or self.endpoint("workpulse/upload_screenshot")
        )

    @property
    def check_version_url(self) -> str:
        """Configurable check new version endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_CHECK_VERSION_API_URL")
            or self._details.get("check_version_url")
            or APP_CONTROLLER_URL
        )

    @property
    def report_error_url(self) -> str:
        """Configurable error report endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_REPORT_ERROR_API_URL")
            or self._details.get("report_error_url")
            or self.endpoint("workpulse/report_error")
        )

    @property
    def get_kra_url(self) -> str | None:
        """Configurable KRA / Task fetch endpoint URL from AppController, environment, or default endpoint."""
        url = (
            os.environ.get("IHRMS_GET_KRA_API_URL")
            or self._details.get("get_kra_url")
            or self._details.get("kra_url")
            or (self.endpoint("TaskPMS/get_kra") if self.is_verified else None)
        )
        return url

    @property
    def get_draft_kra_date_url(self) -> str | None:
        """Configurable Draft KRA fetch endpoint URL from AppController, environment, or default endpoint."""
        url = (
            os.environ.get("IHRMS_GET_DRAFT_KRA_DATE_API_URL")
            or self._details.get("get_draft_kra_date_url")
            or self._details.get("draft_kra_date_url")
            or (self.endpoint("TaskPMS/get_draft_kra_date") if self.is_verified else None)
        )
        return url

    @property
    def get_submit_kra_date_url(self) -> str | None:
        """Configurable Submit KRA fetch endpoint URL from AppController, environment, or default endpoint."""
        url = (
            os.environ.get("IHRMS_GET_SUBMIT_KRA_DATE_API_URL")
            or self._details.get("get_submit_kra_date_url")
            or self._details.get("submit_kra_date_url")
            or (self.endpoint("TaskPMS/get_submit_kra_date_v2") if self.is_verified else None)
        )
        return url

    @property
    def fill_time_sheet_url(self) -> str | None:
        """Configurable fill timesheet endpoint URL from AppController, environment, or default endpoint."""
        url = (
            os.environ.get("IHRMS_FILL_TIME_SHEET_API_URL")
            or self._details.get("fill_time_sheet_url")
            or self._details.get("fill_timesheet_url")
            or (self.endpoint("TaskPMS/fill_time_sheet") if self.is_verified else None)
        )
        return url

    @property
    def save_additional_task_url(self) -> str | None:
        """Configurable save additional task endpoint URL from AppController, environment, or default endpoint."""
        url = (
            os.environ.get("IHRMS_SAVE_ADDITIONAL_TASK_API_URL")
            or self._details.get("save_additional_task_url")
            or (self.endpoint("TaskPMS/save_additional_task") if self.is_verified else None)
        )
        return url

    @property
    def get_attendance_record_url(self) -> str:
        """Configurable attendance record endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_GET_ATTENDANCE_RECORD_API_URL")
            or self._details.get("get_attendance_record_url")
            or self._details.get("attendance_record_url")
            or self.endpoint("attendance/get_attendance_record")
        )

    @property
    def leave_quota_url(self) -> str:
        """Configurable leave quota endpoint URL from AppController, environment, or default endpoint."""
        return (
            os.environ.get("IHRMS_LEAVE_QUOTA_API_URL")
            or self._details.get("leave_quota_url")
            or self._details.get("leave_balance_url")
            or self.endpoint("leave/leave_quota")
        )


    def endpoint(
        self,
        path: str,
    ) -> str:
        """
        Build a full URL for an API path.

        Example:

            ApiConfig().endpoint("workpulse/enroll_device")
        """

        return f"{self.base_url}/{path.lstrip('/')}"
