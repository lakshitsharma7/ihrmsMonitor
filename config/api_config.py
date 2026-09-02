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

APP_CONTROLLER_URL = (
    "https://info.indovisionservices.in/dev/v15/hrms_api/v7/api"
    "/appcontroller/appcontroller"
)

# How long to wait for the App Controller bootstrap call.
APP_CONTROLLER_TIMEOUT_SECONDS = 15


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
    device id this deployment has enrolled.
    """

    override = os.environ.get(DEVICE_ID_ENV_VAR, "").strip()

    if override:
        logger.info(
            "Using device id from %s",
            DEVICE_ID_ENV_VAR,
        )

        return override

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
                logger.warning(
                    "App Controller request failed: %s",
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
                        logger.info("Using cached company configuration for %s: %s", cc, self._base_url)
                        return
                except Exception as cache_err:
                    logger.debug("Could not read cached config: %s", cache_err)

                # Never fall back to another company's configuration.
                self._clear_state()

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

    def endpoint(
        self,
        path: str,
    ) -> str:
        """
        Build a full URL for an API path.

        Example:

            ApiConfig().endpoint("tracking/enroll_device")
        """

        return f"{self.base_url}/{path.lstrip('/')}"
